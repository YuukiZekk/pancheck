"""第二期：批准 → 预演 → 执行（只搬不删）→ 对账 → 回滚。

红线（写进代码）：
  - 搬移只有两种后端：挂载改名（os.rename）或 CD2 直连（gRPC MoveFile，服务端改名）。没有任何删除调用，
    失败不退回复制；直连出错就停批，不悄悄改用挂载（用户选了才换）。
  - 执行入口：环境变量 PANEL_ALLOW_MOVE=1 必须开；挂载改名还要挂载可写，直连要有带「移动」权限的 CD2 令牌。
  - 只有「可清理」能批准移到查重区；「主库缺口」能批准挪入待入库区（老配置是主库目录）；同时是「唯一副本」的由用户选去处。
  - 整夹搬运前验纯度：夹内视频只属于这一部片、且都被批准，才整夹搬；否则逐文件搬；多片夹拒绝整夹。
    搬完后对账夹内视频数，不等就停（成龙夹教训）。
  - 每条操作先写「打算」再动手，动完写结果；中途崩了按日志续，判不清的不动、报出来。
  - 真库第一次只许 ≤10 条的小批量，对账无误后才放开。
命令行：python -m panel.execute run|rollback <batch_dir>
"""
import json
import os
import sys
import time

from . import config as C
from . import sources as S

TRIAL_MAX = 10
BATCHES = C.DATA_DIR / 'batches'
STATE_FILE = C.DATA_DIR / 'exec_state.json'


def allowed():
    return os.environ.get('PANEL_ALLOW_MOVE', '') == '1'


def mount_writable(cfg):
    m = cfg.get('cd2_mount') or ''
    return bool(m) and os.path.isdir(m) and os.access(m, os.W_OK)


def state():
    try:
        return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'trial_ok': False}


def _save_state(st):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(st, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, STATE_FILE)


# ---------------- 批准 ----------------
def approvals_file(run_dir):
    return run_dir / 'approvals.json'


def load_approvals(run_dir, fp):
    try:
        a = json.loads(approvals_file(run_dir).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return a.get('items', {}) if a.get('fingerprint') == fp else {}      # 配置变了，批准自动作废


def save_approvals(run_dir, fp, items):
    f = approvals_file(run_dir)
    tmp = f.with_suffix('.tmp')
    tmp.write_text(json.dumps({'fingerprint': fp, 'items': items, 'saved': time.time()}, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, f)


def dest_dirs(cfg):
    """各去处的目录。mainlib 这个动作名沿用（批准记录兼容），新模型下指「待入库区」（反馈 23：不直进主媒体库）。"""
    ml = cfg.get('staging_dir') or ('' if cfg.get('tree_model') else cfg.get('main_lib_dir') or '')
    return {'quarantine': cfg.get('quarantine_dir') or '', 'mainlib': ml, 'unique': cfg.get('unique_dir') or ''}


def dest_names(cfg):
    return {'quarantine': '查重区', 'mainlib': '待入库区' if (cfg.get('tree_model') or cfg.get('staging_dir')) else '主库目录',
            'unique': '唯一副本目录'}


def approvable(rows_by_path, path, dest, cfg=None):
    """返回 (动作, 错误)。动作：quarantine（查重区）/ mainlib（待入库区；老配置是主库目录）/ unique（唯一副本目录）。"""
    rs = rows_by_path.get(path) or []
    buckets = {r['bucket'] for r in rs}
    if '可切' in buckets:
        return 'quarantine', None
    if '缺口' in buckets:
        if cfg and cfg.get('tree_model') and not cfg.get('staging_on', True):
            return None, '待入库区的开关关着：留下的片留在原地，不搬'
        if '孤本' in buckets:
            if dest not in ('mainlib', 'unique'):
                return None, '这条同时是「主库缺口」和「唯一副本」，要你选去处：挪入%s，还是移到唯一副本目录' % (
                    dest_names(cfg or {})['mainlib'].replace('目录', ''))
            return dest, None
        return 'mainlib', None
    return None, '只有「可清理」和「主库缺口」能批准'


# ---------------- 重跑后把上轮批准带过来 ----------------
CARRY_BUCKETS = ('可切', '缺口', '孤本')


def _verdict(rs):
    """一条路径的判定指纹：可批准相关各桶的（分类, 模块, 判定, 保留份）。任何一项变了都算「判定变了」。"""
    return sorted({(r['bucket'], r['stage'], r['cls'], r.get('keep') or '') for r in rs if r['bucket'] in CARRY_BUCKETS})


def _by_path(rows):
    out = {}
    for r in rows:
        out.setdefault(r['path'], []).append(r)
    return out


def carry_file(run_dir):
    return run_dir / 'carry.json'


def carry_over(old_dir, old_fp, old_rows, new_dir, new_fp, new_rows, new_rejected=False):
    """上轮批准里：新结果里仍在、判定没变、去处不变的自动带过来；其余作废并逐条说原因。
    带过来的批准在预演阶段照样复核（存在性、纯度、目标冲突），这里不放松任何检查。
    写新一轮的 approvals.json 和 carry.json，返回报告。"""
    try:
        raw = json.loads(approvals_file(old_dir).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raw = {}
    # 上轮批准若早已因改设置作废，用户界面上本就看不到，不算「上轮批准」
    old_items = (raw.get('items') or {}) if raw.get('fingerprint') == old_fp else {}
    rep = {'from_run': old_dir.name, 'prev': len(old_items), 'carried': 0, 'dropped': [], 'note': '', 'at': time.time()}
    if not old_items:
        return rep                                   # 上轮没批准：什么都不写
    carried = {}
    if new_fp != old_fp:
        rep['note'] = '两轮之间改过设置，批准一律不带过来'
    elif new_rejected:
        rep['note'] = '新结果被保护守卫整批拒绝，批准不带过来'
    if rep['note']:
        rep['dropped'] = [{'path': p, 'reason': rep['note']} for p in old_items]
    else:
        ob, nb = _by_path(old_rows), _by_path(new_rows)
        for p, it in old_items.items():
            if p not in nb:
                rep['dropped'].append({'path': p, 'reason': '新结果里没有这条（可能已搬走、改名或不再入清单）'})
                continue
            if _verdict(ob.get(p, [])) != _verdict(nb[p]):
                rep['dropped'].append({'path': p, 'reason': '判定变了，请重新看过再批准'})
                continue
            action, err = approvable(nb, p, it.get('dest'))
            if err or action != it.get('action'):
                rep['dropped'].append({'path': p, 'reason': err or '去处变了，请重新批准'})
                continue
            carried[p] = dict(it, carried_from=old_dir.name)
    rep['carried'] = len(carried)
    if carried:
        save_approvals(new_dir, new_fp, carried)
    tmp = carry_file(new_dir).with_suffix('.tmp')
    tmp.write_text(json.dumps(rep, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, carry_file(new_dir))
    return rep


# ---------------- 预演（生成搬运计划，不动文件） ----------------
def _is_video(name):
    return os.path.splitext(name)[1].lower() in S.VIDEO_EXT


def _walk_real(real):
    """[(相对路径, 字节)]，含子目录；读不了的跳过。"""
    out = []
    for dp, dns, fns in os.walk(real):
        for fn in fns:
            fp = os.path.join(dp, fn)
            try:
                out.append((os.path.relpath(fp, real).replace(os.sep, '/'), os.path.getsize(fp)))
            except OSError:
                pass
    return out


# ---------------- 搬移后端：挂载改名 / CD2 直连 ----------------
class MountFS:
    """经 CD2 挂载做 os.rename（真库实测 1–2 分钟一部，只适合小批量）。"""
    name = 'mount'

    def __init__(self, cfg):
        self.cfg = cfg

    def r(self, vp):
        return S.to_real(self.cfg, vp)

    def exists(self, vp):
        return os.path.exists(self.r(vp))

    def isdir(self, vp):
        return os.path.isdir(self.r(vp))

    def walk(self, vp):
        return _walk_real(self.r(vp)) if self.isdir(vp) else []

    def size(self, vp):
        real = self.r(vp)
        return sum(s for _, s in _walk_real(real)) if os.path.isdir(real) else os.path.getsize(real)

    def move(self, src, dst):
        d = self.r(dst)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        os.rename(self.r(src), d)


class CD2FS:
    """经 CD2 接口（gRPC MoveFile）搬移：与 clouddrive mv 同源，服务端改名、秒完。"""
    name = 'cd2'

    def __init__(self, client):
        self.c = client

    def exists(self, vp):
        return self.c.exists(vp)

    def isdir(self, vp):
        st = self.c.stat(vp)
        return bool(st and st['dir'])

    def walk(self, vp):
        return self.c.walk(vp)

    def size(self, vp):
        return self.c.size(vp)

    def move(self, src, dst):
        self.c.move(src, dst)


def backend(cfg, force=None):
    """按「执行方式」选后端。auto：有 CD2 令牌就走直连（连不上就报错，不悄悄退回挂载）；没有令牌才用挂载改名。"""
    from . import cd2api
    mode = force or cfg.get('exec_mode') or 'auto'
    if mode == 'mount':
        return MountFS(cfg)
    if mode == 'auto' and not cd2api._token_candidates(cfg.get('cd2_config')):
        return MountFS(cfg)
    try:
        return CD2FS(cd2api.connect(cfg))
    except cd2api.CD2Error as e:
        raise BackendError('CD2 直连不可用：%s。可以修好后重试，或在设置 → 高级里把「执行方式」改成「挂载改名」（慢，只适合小批量）' % e)


class BackendError(Exception):
    pass


def _single_film(cfg, vfolder, listing):
    """夹内视频是否只属于一部片：盘片夹（BDMV/VIDEO_TS）算一部；否则要求是「单片夹」（与保护判定同口径）。"""
    if any(p.split('/')[0].lower() in S.DISC_DIRS or '/bdmv/' in '/' + p.lower() for p, _ in listing):
        return True
    vids = [vfolder + '/' + p for p, _ in listing if _is_video(p)]
    if not vids:
        return False
    return vfolder in S.film_unit_dirs(vids)


def _same_drive(a, b):
    return a.strip('/').split('/')[0] == b.strip('/').split('/')[0]


def _zone_roots(cfg):
    return [r.rstrip('/') for z in cfg['zones'].values() for r in z]


def plan(cfg, rows, approvals, batch_id, fs=None):
    """approvals: {path: {action, dest}}。返回 {'ops': [...], 'refused': [...], 'rows': 批准条数}。
    fs：搬移后端（实时核对源在不在、列目录验纯度都走它）；不给就按设置选。"""
    fs = fs or backend(cfg)
    rows_by_path = {}
    for r in rows:
        rows_by_path.setdefault(r['path'], []).append(r)
    dirs, names = dest_dirs(cfg), dest_names(cfg)
    roots = set(_zone_roots(cfg))
    refused, ops = [], []
    by_parent = {}
    approved = set(approvals)
    for path, a in sorted(approvals.items()):
        action, err = approvable(rows_by_path, path, a.get('dest'), cfg)
        if err:
            refused.append({'path': path, 'reason': err}); continue
        if a.get('action') and a['action'] != action:
            refused.append({'path': path, 'reason': '批准时的去处和现在的分类对不上，请重新批准'}); continue
        if not dirs[action]:
            refused.append({'path': path, 'reason': '设置里还没填%s' % names[action]}); continue
        if any(path == d.rstrip('/') or path.startswith(d.rstrip('/') + '/') for d in dirs.values() if d):
            refused.append({'path': path, 'reason': '已经在%s里了' % ' / '.join(names[k] for k in dirs if dirs[k])}); continue
        if S.guard_hit(cfg, path, set()):
            refused.append({'path': path, 'reason': '落在没勾的目录 / 保护目录 / 榜单包里（守卫拒绝）'}); continue
        if not _same_drive(path, dirs[action]):
            refused.append({'path': path, 'reason': '%s和这条不在同一个网盘上，同盘改名才是秒搬，跨盘会变成复制，拒绝' % names[action]}); continue
        if not fs.exists(path):
            refused.append({'path': path, 'reason': '源已不在（可能已经搬过或被改名）', 'skip': True}); continue
        if fs.isdir(path):
            listing = fs.walk(path)
            if not _single_film(cfg, path, listing):
                refused.append({'path': path, 'reason': '这是多片夹（夹里不止一部片），不许整夹搬'}); continue
            ops.append({'kind': 'folder', 'src': path, 'covers': [path], 'action': action,
                        'size': sum(s for _, s in listing), 'videos': sum(1 for p, _ in listing if _is_video(p))})
        else:
            by_parent.setdefault((path.rsplit('/', 1)[0], action), []).append(path)
    # 文件条目：父夹纯（单片夹、视频全被批准、不是分区根/包这一层）→ 整夹；否则逐文件
    for (parent, action), paths in sorted(by_parent.items()):
        listing = fs.walk(parent) if fs.isdir(parent) else []
        vids = {parent + '/' + p for p, _ in listing if _is_video(p)}
        rel = [r for r in roots if parent.startswith(r + '/')]
        depth_ok = bool(rel) and parent[len(rel[0]) + 1:].count('/') >= 1     # 至少在包下面一层，不搬包本身
        whole = (depth_ok and parent not in roots and vids and vids <= approved
                 and vids <= set(paths) and _single_film(cfg, parent, listing))
        if whole:
            ops.append({'kind': 'folder', 'src': parent, 'covers': sorted(paths), 'action': action,
                        'size': sum(s for _, s in listing), 'videos': len(vids)})
        else:
            for p in paths:
                ops.append({'kind': 'file', 'src': p, 'covers': [p], 'action': action,
                            'size': fs.size(p), 'videos': 1})
    for i, op in enumerate(ops):
        d = dirs[op['action']].rstrip('/')
        op['id'] = i
        op['dst'] = d + '/' + batch_id + op['src'] if op['action'] == 'quarantine' else d + '/' + op['src'].rsplit('/', 1)[1]
        if fs.exists(op['dst']):
            op['blocked'] = '目标位置已有同名（不覆盖）'
    blocked = [op for op in ops if op.get('blocked')]
    refused += [{'path': c, 'reason': op['blocked']} for op in blocked for c in op['covers']]
    ops = [op for op in ops if not op.get('blocked')]
    return {'batch_id': batch_id, 'ops': ops, 'refused': refused, 'rows': len(approvals), 'backend': fs.name,
            'gb': round(sum(op['size'] for op in ops) / S.GB, 2)}


# ---------------- 执行 / 续跑 ----------------
def _journal(bdir):
    out = {}
    jf = bdir / 'journal.jsonl'
    if jf.exists():
        for line in jf.read_text(encoding='utf-8').splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            out.setdefault(e['op'], []).append(e)
    return out


def _log(bdir, entry):
    with open(bdir / 'journal.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(dict(entry, t=time.time()), ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def _emit(msg, pct=None):
    print('@@P ' + json.dumps({'msg': msg, 'pct': pct}, ensure_ascii=False), flush=True)


def run_batch(bdir):
    cfg = C.load()
    p = json.loads((bdir / 'plan.json').read_text(encoding='utf-8'))
    ops = p['ops']
    # 后端按批次定（建批次时选好的）；续跑时用户可指定改用别的（PANEL_EXEC_BACKEND），不自动退回
    want = os.environ.get('PANEL_EXEC_BACKEND') or p.get('backend') or 'mount'
    try:
        fs = backend(cfg, force=want)
    except BackendError as e:
        _emit('停批：%s' % e, 100)
        print(str(e), flush=True)
        reconcile(bdir)
        return 4
    if fs.name != p.get('backend'):
        _log(bdir, {'op': -1, 'state': 'backend', 'from': p.get('backend'), 'to': fs.name})
    done = _journal(bdir)
    crash_after = int(os.environ.get('PANEL_EXEC_CRASH_AFTER') or 0)    # 演练用：搬了 N 条后模拟崩溃
    moved = 0
    for k, op in enumerate(ops):
        _emit('搬运 %d/%d：%s' % (k + 1, len(ops), op['src'].rsplit('/', 1)[1]), int(k * 100 / max(1, len(ops))))
        hist = done.get(op['id'], [])
        if any(e['state'] in ('done', 'skip', 'fail') for e in hist):
            continue
        src, dst = op['src'], op['dst']
        try:
            if any(e['state'] == 'intent' for e in hist):
                # 上次写了打算、没写结果（或结果未知）：看实际状态判断
                if fs.exists(dst) and not fs.exists(src):
                    _log(bdir, {'op': op['id'], 'state': 'done', 'note': '续跑：上次已搬成'})
                    continue
                if fs.exists(dst) and fs.exists(src):
                    _log(bdir, {'op': op['id'], 'state': 'fail', 'reason': '续跑：源和目标都在，判不清，不动'})
                    continue
            if not fs.exists(src):
                _log(bdir, {'op': op['id'], 'state': 'skip', 'reason': '源已不在'})
                continue
            if fs.exists(dst):
                _log(bdir, {'op': op['id'], 'state': 'fail', 'reason': '目标已存在（不覆盖）'})
                continue
            size = fs.size(src)
        except Exception as e:
            if fs.name == 'cd2':
                _log(bdir, {'op': op['id'], 'state': 'fail', 'reason': 'CD2 直连出错，已停批：%s' % e})
                _emit('CD2 直连出错，已停批（不会退回挂载改名）', 100)
                break
            raise
        if size != op['size']:
            _log(bdir, {'op': op['id'], 'state': 'fail', 'reason': '身份不符：体积 %d ≠ 预演时 %d' % (size, op['size'])})
            continue
        _log(bdir, {'op': op['id'], 'state': 'intent', 'src': op['src'], 'dst': op['dst'], 'size': size, 'via': fs.name})
        t0 = time.time()
        try:
            fs.move(src, dst)
        except Exception as e:
            if fs.name == 'cd2':
                # 直连断在搬移途中：服务端可能已经搬了，只是没能确认 → 记「结果未知」，续跑时按实地判，不当失败跳过
                _log(bdir, {'op': op['id'], 'state': 'unknown', 'reason': 'CD2 直连在搬移途中出错，结果未知（续跑时按实地核对）：%s' % e})
                _emit('CD2 直连搬移出错，已停批（不会退回挂载改名）', 100)
                break
            _log(bdir, {'op': op['id'], 'state': 'fail', 'reason': '搬移失败（不会改用复制）：%s' % e})
            continue
        moved += 1
        if crash_after and moved >= crash_after:
            os._exit(3)                                   # 演练：动完了、还没写结果就崩
        if op['kind'] == 'folder':
            n = sum(1 for p_, _ in fs.walk(dst) if _is_video(p_))
            if n != op['videos']:
                _log(bdir, {'op': op['id'], 'state': 'fail', 'reason': '整夹搬完后对账：夹内视频 %d ≠ 批准覆盖 %d，停下' % (n, op['videos'])})
                _emit('整夹对账不符，已停下', 100)
                break
        _log(bdir, {'op': op['id'], 'state': 'done', 'secs': round(time.time() - t0, 2)})
    rec = reconcile(bdir, fs)
    st = state()
    if rec['ok'] and rec['rows'] <= TRIAL_MAX and rec['moved_rows'] > 0 and not st.get('trial_ok'):
        st.update(trial_ok=True, trial_batch=p['batch_id'], trial_at=time.time())
        _save_state(st)
    _emit('完成：搬成 %d 条，跳过 %d，失败 %d%s' % (rec['moved_rows'], rec['skipped_rows'], rec['failed_rows'],
                                            '' if rec['ok'] else '（对账不平）'), 100)
    return 0 if rec['ok'] else 2


def reconcile(bdir, fs=None):
    """批准数 = 搬成 + 跳过（源已不在）+ 失败 + 预演拒绝，逐条点名；搬成的还要实地核对源没了、目标在。"""
    cfg = C.load()
    p = json.loads((bdir / 'plan.json').read_text(encoding='utf-8'))
    if fs is None:
        try:
            fs = backend(cfg, force=os.environ.get('PANEL_EXEC_BACKEND') or p.get('backend') or 'mount')
        except BackendError:
            fs = None
    j = _journal(bdir)
    moved = skipped = failed = 0
    fails, verify_bad = [], []
    for op in p['ops']:
        last = [e for e in j.get(op['id'], []) if e['state'] in ('done', 'skip', 'fail', 'rolled_back', 'unknown')]
        st = last[-1]['state'] if last else 'pending'
        n = len(op['covers'])
        if st == 'done':
            try:
                ok = fs is not None and fs.exists(op['dst']) and not fs.exists(op['src'])
                why = '日志说搬成了，实地核对不符' if fs is not None else '日志说搬成了，但现在核对不了（搬移后端不可用）'
            except Exception as e:
                ok, why = False, '日志说搬成了，但现在核对不了：%s' % e
            if ok:
                moved += n
            else:
                failed += n
                verify_bad.append({'op': op['id'], 'src': op['src'], 'reason': why})
        elif st == 'skip':
            skipped += n
        elif st == 'rolled_back':
            skipped += n
        else:
            failed += n
            fails.append({'op': op['id'], 'src': op['src'], 'reason': last[-1].get('reason') if last else '没执行到'})
    pre_skip = sum(1 for r in p['refused'] if r.get('skip'))
    pre_ref = len(p['refused']) - pre_skip
    rec = {'batch_id': p['batch_id'], 'rows': p['rows'], 'moved_rows': moved, 'skipped_rows': skipped + pre_skip,
           'failed_rows': failed, 'refused_rows': pre_ref, 'failures': fails + verify_bad, 'refused': p['refused'],
           'checked_at': time.time()}
    rec['balanced'] = rec['rows'] == moved + skipped + pre_skip + failed + pre_ref
    rec['ok'] = rec['balanced'] and not fails and not verify_bad
    (bdir / 'reconcile.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    return rec


# ---------------- 回滚 ----------------
def rollback(bdir):
    cfg = C.load()
    p = json.loads((bdir / 'plan.json').read_text(encoding='utf-8'))
    j = _journal(bdir)
    try:
        fs = backend(cfg, force=os.environ.get('PANEL_EXEC_BACKEND') or p.get('backend') or 'mount')
    except BackendError as e:
        _emit('回滚停止：%s' % e, 100)
        (bdir / 'rollback.json').write_text(json.dumps({'rolled_back': 0, 'problems': [{'op': -1, 'reason': str(e)}],
                                                        'at': time.time()}, ensure_ascii=False, indent=1), encoding='utf-8')
        return 4
    back, problems = 0, []
    for op in reversed(p['ops']):
        hist = j.get(op['id'], [])
        last = [e for e in hist if e['state'] in ('done', 'skip', 'fail', 'rolled_back')]
        if not last or last[-1]['state'] != 'done':
            continue
        src, dst = op['src'], op['dst']
        _emit('回滚：%s' % op['src'].rsplit('/', 1)[1])
        if not fs.exists(dst):
            problems.append({'op': op['id'], 'reason': '查重区里找不到这份了，不动'}); continue
        if fs.exists(src):
            problems.append({'op': op['id'], 'reason': '原位置已经有东西了，不覆盖'}); continue
        size = fs.size(dst)
        if size != op['size']:
            problems.append({'op': op['id'], 'reason': '身份不符：体积 %d ≠ 搬走时 %d，不覆盖' % (size, op['size'])}); continue
        _log(bdir, {'op': op['id'], 'state': 'rollback_intent'})
        try:
            fs.move(dst, src)
        except Exception as e:
            problems.append({'op': op['id'], 'reason': '搬回失败：%s' % e}); continue
        _log(bdir, {'op': op['id'], 'state': 'rolled_back'})
        back += 1
    out = {'rolled_back': back, 'problems': problems, 'at': time.time()}
    (bdir / 'rollback.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    _emit('回滚完成：搬回 %d 处，问题 %d' % (back, len(problems)), 100)
    return 0 if not problems else 2


if __name__ == '__main__':
    cmd, bdir = sys.argv[1], sys.argv[2]
    from pathlib import Path
    sys.exit(run_batch(Path(bdir)) if cmd == 'run' else rollback(Path(bdir)))
