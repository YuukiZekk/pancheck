"""sieve 面板（第一期：设置 + 盘点 + 跑筛 + 清单导出，只读）。

红线（写进代码）：
- 本服务没有任何删除接口。移动只有一条路：第二期执行（panel/execute.py，只用改名），
  要 PANEL_ALLOW_MOVE=1 且 CD2 挂载可写两道开关都开才有入口；只执行用户批准过的条目。
- CD2 缓存、Emby 库只读打开（见 panel/sources.py）。
- 配置变了旧清单自动作废（指纹不符的结果不允许导出可切类）。
- 可切里命中保护区/榜单包 → 整批拒绝。
"""
import base64
import csv
import io
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from panel import config as C
from panel import keeps as K
from panel import labels as L
from panel import sources

app = FastAPI(title='sieve 面板', docs_url=None, redoc_url=None)
STATIC = C.APP_DIR / 'static'
PASSWORD = os.environ.get('PANEL_PASSWORD', '')

# ---------------- 可选的访问口令（HTTP Basic，用户名任意） ----------------
@app.middleware('http')
async def basic_auth(request: Request, call_next):
    if PASSWORD and request.url.path != '/healthz':
        ok = False
        h = request.headers.get('authorization', '')
        if h.lower().startswith('basic '):
            try:
                pw = base64.b64decode(h[6:]).decode('utf-8').split(':', 1)[1]
                ok = secrets.compare_digest(pw, PASSWORD)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={'WWW-Authenticate': 'Basic realm="sieve"'})
    return await call_next(request)


# ---------------- 任务（一次只跑一个） ----------------
class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.state = {'running': False}

    def start_exec(self, kind, bdir, backend=''):
        """执行 / 回滚一个批次（同样一次只跑一个任务）。"""
        with self.lock:
            if self.proc and self.proc.poll() is None:
                raise HTTPException(409, '已有任务在跑')
            log = open(bdir / ('%s.log' % kind), 'a', encoding='utf-8')
            env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', SIEVE_DATA=str(C.DATA_DIR))
            if backend:
                env['PANEL_EXEC_BACKEND'] = backend
            self.proc = subprocess.Popen([sys.executable, '-m', 'panel.execute', kind, str(bdir)],
                                         cwd=str(C.APP_DIR), env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            self.state = {'running': True, 'run_id': bdir.name, 'mode': kind, 'pct': 0, 'msg': '启动中',
                          'started': time.time(), 'tail': []}
            threading.Thread(target=self._pump, args=(self.proc, log), daemon=True).start()
            return self.state

    def start(self, mode):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                raise HTTPException(409, '已有任务在跑')
            C.RUNS_DIR.mkdir(parents=True, exist_ok=True)
            base, n = time.strftime('%Y%m%d-%H%M%S') + '-' + mode, 1
            run_id = base
            while (C.RUNS_DIR / run_id).exists():
                n += 1
                run_id = '%s-%d' % (base, n)
            run_dir = C.RUNS_DIR / run_id
            run_dir.mkdir()
            log = open(run_dir / 'run.log', 'w', encoding='utf-8')
            env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', SIEVE_DATA=str(C.DATA_DIR))
            self.proc = subprocess.Popen([sys.executable, '-m', 'panel.runner', mode, str(run_dir)],
                                         cwd=str(C.APP_DIR), env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            self.state = {'running': True, 'run_id': run_id, 'mode': mode, 'pct': 0, 'msg': '启动中',
                          'started': time.time(), 'tail': []}
            threading.Thread(target=self._pump, args=(self.proc, log), daemon=True).start()
            return self.state

    def _pump(self, proc, log):
        for line in proc.stdout:
            log.write(line)
            log.flush()
            line = line.rstrip('\n')
            if line.startswith('@@P '):
                try:
                    p = json.loads(line[4:])
                    self.state['msg'] = p['msg']
                    if p.get('pct') is not None:
                        self.state['pct'] = p['pct']
                except ValueError:
                    pass
            else:
                self.state['tail'] = (self.state['tail'] + [line])[-30:]
        code = proc.wait()
        log.close()
        self.state.update(running=False, exit=code, finished=time.time())
        if self.state.get('cancelled'):
            # 结果文件只在跑完时原子写入，停掉的任务不会留下半份结果
            self.state['msg'] = '已停止（这次没有产出结果，之前的结果不受影响）'
        elif code != 0 and not self.state['msg'].startswith('失败'):
            self.state['msg'] = '失败（退出码 %s），见日志' % code
        elif self.state.get('mode') == 'full':
            try:
                rep = carry_after_run(self.state['run_id'])
                if rep and rep['prev']:
                    self.state['msg'] += '；上轮批准 %d 条：带过来 %d 条、已失效 %d 条' % (
                        rep['prev'], rep['carried'], len(rep['dropped']))
            except Exception as e:              # 带不过来不影响结果本身；批准照旧清空，用户重新勾
                self.state['msg'] += '；上轮批准没能带过来（%s），请重新批准' % e

    def cancel(self):
        with self.lock:
            proc = self.proc
            if not proc or proc.poll() is not None:
                raise HTTPException(409, '当前没有在跑的任务')
            self.state['cancelled'] = True
            self.state['msg'] = '正在停止…'
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return self.state


JOB = Job()


# ---------------- 结果读取 ----------------
def list_runs():
    if not C.RUNS_DIR.exists():
        return []
    out = []
    for d in C.RUNS_DIR.iterdir():
        f = d / 'result.json'
        if f.exists():
            try:
                r = json.loads(f.read_text(encoding='utf-8'))
                out.append({'run_id': d.name, 'mode': r.get('mode'), 'fingerprint': r.get('fingerprint'),
                            'finished': r.get('finished')})
            except ValueError:
                pass
    out.sort(key=lambda r: r['finished'] or 0, reverse=True)   # 最新完成的在前
    return out


def load_run(run_id=None, mode='full'):
    runs = [r for r in list_runs() if r['mode'] == mode]
    if run_id:
        runs = [r for r in runs if r['run_id'] == run_id]
    if not runs:
        return None, None
    d = C.RUNS_DIR / runs[0]['run_id']
    res = json.loads((d / 'result.json').read_text(encoding='utf-8'))
    res['run_id'] = runs[0]['run_id']
    res['stale'] = res.get('fingerprint') != C.fingerprint(C.load())
    return res, d


_rows_cache = {}


def load_rows(d):
    key = str(d)
    if key not in _rows_cache:
        _rows_cache.clear()
        _rows_cache[key] = json.loads((d / 'rows.json').read_text(encoding='utf-8'))
    return _rows_cache[key]


def shown_rows(d):
    """清单 / 导出看到的行：去掉「已确认保留」命中的待定行（见 panel/keeps.py）。→ (显示的, 隐藏的)"""
    return K.split(load_rows(d))


def _hidden_info(hidden):
    return {'count': len(hidden), 'gb': round(sum(r['gb'] for r in hidden), 1)}


def _name_key(r):
    return r['path'].rstrip('/').rsplit('/', 1)[-1].lower()


# 分面筛选：每组可多选（逗号分隔）；子类用「来源|判定」；标记组：体积推断 / 肉酱盘 / 整夹 / 单文件
FLAGS = {'infer': lambda r: '按体积推断' in (r.get('basis') or ''), 'roujiang': lambda r: bool(r.get('flag')),
         'whole': lambda r: r.get('move') == '整夹', 'file': lambda r: r.get('move') == '单文件'}
FACET_KEY = {'bucket': lambda r: [r['bucket']], 'stage': lambda r: [r['stage']],
             'cls': lambda r: ['%s|%s' % (r['stage'], r['cls'])], 'flag': lambda r: [k for k, f in FLAGS.items() if f(r)],
             'tag': lambda r: r.get('tags') or []}


def _sel(v):
    return {x for x in (v or '').split(',') if x}


def _match(r, g, want):
    return not want or bool(want.intersection(FACET_KEY[g](r)))


def _q_ok(r, q):
    return not q or q in r['path'].lower() or q in (r.get('keep') or '').lower() or q in (r.get('flag') or '').lower()


def filter_rows(rows, bucket='', stage='', cls='', q='', flag='', tag=''):
    q = (q or '').strip().lower()
    want = {'bucket': _sel(bucket), 'stage': _sel(stage), 'flag': _sel(flag), 'tag': _sel(tag),
            'cls': {c if '|' in c else c for c in _sel(cls)}}
    # 兼容旧调用：cls 只给了判定码（没有「来源|」）时按判定码匹配
    bare = {c for c in want['cls'] if '|' not in c}
    if bare:
        want['cls'] -= bare
    return [r for r in rows if all(_match(r, g, w) for g, w in want.items()) and (not bare or r['cls'] in bare) and _q_ok(r, q)]


def facet_counts(rows, bucket='', stage='', cls='', q='', flag='', tag=''):
    """每组的计数 = 其他组的条件都生效、本组不限时的分布（OpenStatus 式联动）。"""
    args = {'bucket': bucket, 'stage': stage, 'cls': cls, 'flag': flag, 'tag': tag}
    out = {}
    for g in FACET_KEY:
        rs = filter_rows(rows, q=q, **dict(args, **{g: ''}))
        c = {}
        for r in rs:
            for k in FACET_KEY[g](r):
                c[k] = c.get(k, 0) + 1
        out[g] = c
    return out


# ---------------- API ----------------
@app.get('/healthz')
def healthz():
    return {'ok': True}


# 反馈 24：换版后浏览器还拿着旧前端。index.html 一律不缓存；app.css / app.js 带内容指纹（?v=），
# 换版 = 换地址，旧缓存自然用不上；带对指纹的请求可以放心长缓存。页面上显示版本号，方便对版。
NO_CACHE = {'Cache-Control': 'no-cache, must-revalidate'}
APP_VERSION = (os.environ.get('PANCHECK_VERSION') or 'dev')[:7]


def _static_ver():
    import hashlib
    h = hashlib.sha1()
    for n in ('index.html', 'app.css', 'app.js'):
        h.update((STATIC / n).read_bytes())
    return h.hexdigest()[:10]


STATIC_VER = _static_ver()


@app.get('/')
def index():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    html = html.replace('href="app.css"', 'href="app.css?v=%s"' % STATIC_VER).replace('src="app.js"', 'src="app.js?v=%s"' % STATIC_VER)
    html = html.replace('<title>', '<meta name="pancheck-version" content="%s %s" />\n    <title>' % (APP_VERSION, STATIC_VER), 1)
    return Response(html, media_type='text/html; charset=utf-8', headers=NO_CACHE)


def _asset(name, media, v):
    hdr = {'Cache-Control': 'public, max-age=31536000, immutable'} if v == STATIC_VER else NO_CACHE
    return FileResponse(STATIC / name, media_type=media, headers=hdr)


@app.get('/app.css')
def app_css(v: str = ''):
    return _asset('app.css', 'text/css', v)


@app.get('/app.js')
def app_js(v: str = ''):
    return _asset('app.js', 'text/javascript', v)


@app.get('/api/version')
def version():
    return {'version': APP_VERSION, 'static': STATIC_VER}


@app.get('/api/config')
def get_config():
    c = C.load()
    return {'config': c, 'fingerprint': C.fingerprint(c), 'auth_enabled': bool(PASSWORD), 'builtin': {
        'listpack': C.BUILTIN_LISTPACK, 'listpack_rule': C.LISTPACK_RULE, 'exclude': C.BUILTIN_EXCLUDE}}


@app.get('/api/suggest')
def suggest():
    try:
        return sources.suggest(C.load())
    except OSError as e:
        raise HTTPException(400, str(e))


@app.put('/api/config')
async def put_config(request: Request):
    body = await request.json()
    old = C.load()
    # 保护词只能加不能减：内置词由 normalize 补回；用户已有的保护目录名不允许在面板里删
    removed = [x for x in old['protect_names'] if x not in (body.get('protect_names') or [])]
    # 反馈 23：在向导里改成勾选模型时，保护名换成具体目录的「不勾」（skip_dirs），由向导「完成」这一下显式确认
    if removed and body.get('tree_model') and body.get('skip_dirs') is not None and body.get('confirm_tree_model'):
        removed = []
    if removed and not body.get('confirm_remove_protect'):
        raise HTTPException(400, '要移除保护目录名：%s。确认请勾选「我确认移除保护」' % '、'.join(removed))
    c = C.save(body)
    return {'config': c, 'fingerprint': C.fingerprint(c)}


@app.post('/api/setup/{step}')
async def setup_step(step: str, request: Request):
    """向导每一步的识别验收（只读、不保存；用户点「下一步」时前端再存配置）。"""
    from panel import setup as W
    body = await request.json() if (await request.body()) else {}
    c = C.load()
    if step == 'cd2':
        return W.check_cd2(str(body.get('cd2_config') or c['cd2_config']).strip(),
                           dict(c, cd2_api_name=body.get('cd2_api_name') or c['cd2_api_name']))
    if step == 'emby':
        return W.check_emby(str(body.get('emby_data') or c['emby_data']).strip(), c)
    if step == 'zones':
        return W.check_zones(c)
    if step == 'children':
        try:
            return W.children(c, str(body.get('path') or '/'))
        except OSError as e:
            raise HTTPException(400, str(e))
    raise HTTPException(404, '没有这一步')


@app.post('/api/probe')
def probe():
    c = C.load()
    return {'cd2': sources.probe_cd2(c), 'emby': sources.probe_emby(c)}


# ---------------- 第二期：批准 / 预演 / 执行 / 回滚 ----------------
from panel import execute as X


def carry_after_run(run_id):
    """全量跑完：把紧挨着的上一轮全量结果里的批准带到这一轮（只做一次；规则见 execute.carry_over）。"""
    ids = [r['run_id'] for r in list_runs() if r['mode'] == 'full']
    if not ids or ids[0] != run_id or len(ids) < 2:
        return None
    new, old = C.RUNS_DIR / run_id, C.RUNS_DIR / ids[1]
    if X.approvals_file(new).exists() or X.carry_file(new).exists():
        return None
    rd = lambda d, f: json.loads((d / f).read_text(encoding='utf-8'))
    old_res, new_res = rd(old, 'result.json'), rd(new, 'result.json')
    return X.carry_over(old, old_res.get('fingerprint'), rd(old, 'rows.json'), new, new_res.get('fingerprint'),
                        rd(new, 'rows.json'), bool(new_res.get('rejected')))


def _carry_report(d):
    try:
        return json.loads(X.carry_file(d).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _latest_full():
    res, d = load_run(None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    return res, d


def _batch_dir(bid):
    b = X.BATCHES / bid
    if not bid.startswith('B') or '/' in bid or '\\' in bid or '..' in bid or not (b / 'plan.json').exists():
        raise HTTPException(404, '没有这个批次')
    return b


@app.get('/api/exec/status')
def exec_status():
    c = C.load()
    res, d = load_run(None)
    n = len(X.load_approvals(d, res['fingerprint'])) if res and not res['stale'] else 0
    from panel import cd2api
    mode = c.get('exec_mode') or 'auto'
    has_tok = bool(cd2api._token_candidates(c.get('cd2_config')))
    direct = cd2api.mode_status(c) if (mode == 'cd2' or (mode == 'auto' and has_tok)) else None
    return {'allowed': X.allowed(), 'mount_writable': X.mount_writable(c), 'trial_ok': X.state().get('trial_ok', False),
            'exec_mode': mode, 'backend': 'mount' if mode == 'mount' or (mode == 'auto' and not has_tok) else 'cd2',
            'direct': direct,
            'trial_max': X.TRIAL_MAX,
            'dirs': X.dest_dirs(c), 'dir_names': X.dest_names(c), 'staging_on': c['staging_on'], 'tree_model': c['tree_model'],
            'main_lib': c['main_lib_dir'],
            'run_id': res and res['run_id'], 'stale': bool(res and res['stale']),
            'rejected': bool(res and res.get('rejected')), 'approvals': n}


@app.get('/api/approvals')
def approvals_get():
    res, d = _latest_full()
    b = {}
    for r in load_rows(d):
        b.setdefault(r['path'], set()).add(r['bucket'])
    overlap = [p for p, s in b.items() if {'缺口', '孤本'} <= s]       # 去处要用户选的
    return {'run_id': res['run_id'], 'items': X.load_approvals(d, res['fingerprint']) if not res['stale'] else {},
            'overlap': overlap, 'carry': _carry_report(d)}


@app.put('/api/approvals')
async def approvals_put(request: Request):
    """add: [{path, dest?}]，remove: [path]。只认最新一份、没过期、没被整批拒绝的结果。"""
    body = await request.json()
    res, d = _latest_full()
    if res['stale']:
        raise HTTPException(409, '设置改过，这份清单已过期：重新跑筛后再批准')
    if res.get('rejected'):
        raise HTTPException(409, '这份清单被保护守卫整批拒绝，不能批准')
    rows_by_path = {}
    for r in load_rows(d):
        rows_by_path.setdefault(r['path'], []).append(r)
    items = X.load_approvals(d, res['fingerprint'])
    errors = []
    for a in body.get('add') or []:
        action, err = X.approvable(rows_by_path, a.get('path'), a.get('dest'), C.load())
        if err:
            errors.append({'path': a.get('path'), 'reason': err})
        else:
            items[a['path']] = {'action': action, 'dest': a.get('dest') or action, 'at': time.time()}
    for p in body.get('remove') or []:
        items.pop(p, None)
    X.save_approvals(d, res['fingerprint'], items)
    return {'count': len(items), 'errors': errors}


def _new_batch_id():
    base, n = time.strftime('B%Y%m%d-%H%M%S'), 1
    bid = base
    while (X.BATCHES / bid).exists():
        n += 1
        bid = '%s-%d' % (base, n)
    return bid


@app.post('/api/exec/plan')
def exec_plan(action: str = ''):
    """预演：按批准生成搬运计划（实时列一次被批准的目录），不动任何文件。"""
    res, d = _latest_full()
    if res['stale'] or res.get('rejected'):
        raise HTTPException(409, '清单已过期或被整批拒绝')
    c = C.load()
    items = _by_action(X.load_approvals(d, res['fingerprint']), action)
    if not items:
        raise HTTPException(400, '还没有批准任何条目' + ('（这个去向）' if action else ''))
    fs = _backend_or_400(c)
    p = X.plan(c, load_rows(d), items, _new_batch_id(), fs)
    p['action'] = action
    return p


def _by_action(items, action):
    """排查区 / 挪入主库 / 唯一副本目录按去向分批，不混批。"""
    if action not in ('', 'quarantine', 'mainlib', 'unique'):
        raise HTTPException(400, '去向只能是 quarantine / mainlib / unique')
    return {p: a for p, a in items.items() if not action or a.get('action') == action}


def _backend_or_400(c, force=None):
    try:
        fs = X.backend(c, force)
    except X.BackendError as e:
        raise HTTPException(400, str(e))
    if fs.name == 'mount' and (not c['cd2_mount'] or not os.path.isdir(c['cd2_mount'])):
        raise HTTPException(400, '挂载改名要用 CD2 挂载目录：设置 → 高级里填「CD2 挂载根」，compose 里把挂载那行打开')
    return fs


@app.post('/api/exec/run')
def exec_run(action: str = ''):
    # 防重复（真库试跑实测：连点三次，4 秒内建了三个一样的批次）：先抢锁、先查有没有任务在跑，再预演、建批次
    if not EXEC_LOCK.acquire(blocking=False):
        raise HTTPException(409, '已有一次执行正在准备（预演中），不重复建批次')
    try:
        if JOB.state.get('running'):
            raise HTTPException(409, '已有任务在跑（%s），不重复建批次' % JOB.state.get('run_id'))
        return _exec_run_locked(action)
    finally:
        EXEC_LOCK.release()


EXEC_LOCK = threading.Lock()


def _exec_run_locked(action=''):
    if not X.allowed():
        raise HTTPException(403, '执行开关没开：compose 里设 PANEL_ALLOW_MOVE=1 并把 CD2 挂载改成可写，重启后才有执行入口')
    c = C.load()
    fs = _backend_or_400(c)
    if fs.name == 'mount' and not X.mount_writable(c):
        raise HTTPException(403, '挂载改名要挂载可写：compose 里把挂载那行的 :ro 改成 :rw（或改用 CD2 直连）')
    res, d = _latest_full()
    if res['stale'] or res.get('rejected'):
        raise HTTPException(409, '清单已过期或被整批拒绝')
    allitems = X.load_approvals(d, res['fingerprint'])
    items = _by_action(allitems, action)
    if not items:
        raise HTTPException(400, '还没有批准任何条目' + ('（这个去向）' if action else ''))
    if not X.state().get('trial_ok') and len(items) > X.TRIAL_MAX:
        raise HTTPException(409, '第一次执行只许 ≤%d 条的小批量试跑，对账无误后才放开（现在批准了 %d 条）'
                            % (X.TRIAL_MAX, len(items)))
    bid = _new_batch_id()
    p = X.plan(c, load_rows(d), items, bid, fs)
    if not p['ops']:
        raise HTTPException(400, '预演后没有可执行的搬运（都被拒绝或源已不在）')
    bdir = X.BATCHES / bid
    bdir.mkdir(parents=True)
    p.update(run_id=res['run_id'], created=time.time(), action=action)
    (bdir / 'plan.json').write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding='utf-8')
    # 批准随批次带走，不留在清单上重复执行（只带走这个去向的）
    X.save_approvals(d, res['fingerprint'], {k: v for k, v in allitems.items() if k not in items})
    return JOB.start_exec('run', bdir)


@app.get('/api/exec/batches')
def exec_batches():
    out = []
    if X.BATCHES.exists():
        for b in sorted(X.BATCHES.iterdir(), reverse=True):
            item = {'batch_id': b.name}
            for f in ('plan', 'reconcile', 'rollback'):
                try:
                    item[f] = json.loads((b / (f + '.json')).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    pass
            if 'plan' in item:
                pl = item.pop('plan')
                acts = sorted({op['action'] for op in pl['ops']})
                item.update(ops=len(pl['ops']), rows=pl['rows'], gb=pl['gb'], created=pl.get('created'),
                            action=pl.get('action') or (acts[0] if len(acts) == 1 else ','.join(acts)),
                            backend=pl.get('backend'))
            out.append(item)
    return out


@app.get('/api/exec/batch/{bid}')
def exec_batch(bid: str):
    b = _batch_dir(bid)
    out = {f: json.loads((b / (f + '.json')).read_text(encoding='utf-8'))
           for f in ('plan', 'reconcile', 'rollback') if (b / (f + '.json')).exists()}
    # 逐条结果：每个操作日志里的最后状态（执行明细表用）
    states = {}
    for op_id, hist in X._journal(b).items():
        last = [e for e in hist if e['state'] in ('done', 'skip', 'fail', 'unknown', 'rolled_back', 'intent')]
        if last:
            e = last[-1]
            states[op_id] = {'state': e['state'], 'reason': e.get('reason') or e.get('note') or '', 'secs': e.get('secs')}
    out['states'] = states
    return out


@app.post('/api/exec/resume/{bid}')
def exec_resume(bid: str, backend: str = ''):
    """中途崩了 / 停了：按日志续跑同一个批次。backend=mount|cd2 由用户明确选择改用哪种（直连出错后不自动退回）。"""
    if not X.allowed():
        raise HTTPException(403, '执行开关没开')
    if backend not in ('', 'mount', 'cd2'):
        raise HTTPException(400, 'backend 只能是 mount 或 cd2')
    return JOB.start_exec('run', _batch_dir(bid), backend)


@app.post('/api/exec/rollback/{bid}')
def exec_rollback(bid: str):
    if not X.allowed():
        raise HTTPException(403, '执行开关没开')
    return JOB.start_exec('rollback', _batch_dir(bid))


@app.get('/api/tree')
def tree(path: str = '/'):
    try:
        c = C.load()
        return {'path': path, 'dirs': sources.dir_lister(c)(c, path)}
    except OSError as e:
        raise HTTPException(400, str(e))


@app.post('/api/run/{mode}')
def run(mode: str):
    if mode not in ('inventory', 'full'):
        raise HTTPException(404)
    c = C.load()
    if c['data_source'] != 'csv' and not any(c['zones'][z] for z in ('heji', 'yuanpan')):
        raise HTTPException(400, '先在「设置」里至少指定一个合集区或原盘区目录（重新走一遍首次设置也行）')
    return JOB.start(mode)


@app.get('/api/job')
def job():
    return JOB.state


@app.post('/api/job/cancel')
def job_cancel():
    return JOB.cancel()


@app.get('/api/labels')
def labels():
    return L.as_json()


@app.get('/api/runs')
def runs():
    return list_runs()


@app.get('/api/inventory')
def inventory():
    res, _ = load_run(mode='inventory')
    full, _ = load_run(mode='full')
    # 取最新的一次（盘点或全量都带盘点统计）
    cands = [r for r in (res, full) if r]
    if not cands:
        return JSONResponse(None)
    best = max(cands, key=lambda r: r.get('finished') or 0)
    return {k: best.get(k) for k in ('run_id', 'stats', 'errors', 'error_count', 'stale', 'finished')}


@app.get('/api/result')
def result(run_id: str = ''):
    res, d = load_run(run_id or None)
    if not res:
        return JSONResponse(None)
    st = res.get('stats') or {}
    st.pop('heji_packs', None)        # 总览只要各区体积，不要大包明细
    # 「已确认保留」从待定计数里扣掉，扣了多少单独报（不改 result.json，对账用的原始数在导出 zip 的 summary.json 里）
    _, hidden = shown_rows(d)
    res['kept_hidden'] = _hidden_info(hidden)
    if hidden:
        sm = (res.get('summary') or {}).get(K.BUCKET)
        if sm:
            sm['count'] -= len(hidden)
            sm['gb'] = round(max(0, sm['gb'] - res['kept_hidden']['gb']), 1)
        by = {}
        for r in hidden:
            k = (r['bucket'], r['stage'], r['cls'])
            by[k] = (by.get(k, (0, 0))[0] + 1, by.get(k, (0, 0))[1] + r['gb'])
        det = []
        for x in res.get('detail') or []:
            c, g = by.get((x.get('bucket'), x.get('stage'), x.get('cls')), (0, 0))
            if c:
                x = dict(x, count=x['count'] - c, gb=round(max(0, x['gb'] - g), 1))
            if x['count'] > 0:
                det.append(x)
        res['detail'] = det
    return res


@app.get('/api/rows')
def rows(bucket: str = '', stage: str = '', cls: str = '', q: str = '', flag: str = '', offset: int = 0, limit: int = 100,
         sort: str = 'gb', run_id: str = '', facets: int = 0, tag: str = ''):
    res, d = load_run(run_id or None)
    if not res:
        return {'total': 0, 'gb': 0, 'rows': [], 'all': 0, 'facets': {}, 'kept_hidden': {'count': 0, 'gb': 0}}
    allrows, hidden = shown_rows(d)
    rs = filter_rows(allrows, bucket, stage, cls, q, flag, tag)
    if sort in ('gb', 'gb_desc'):
        rs = sorted(rs, key=lambda r: -r['gb'])
    elif sort == 'gb_asc':
        rs = sorted(rs, key=lambda r: r['gb'])
    elif sort == 'path':
        rs = sorted(rs, key=lambda r: r['path'])
    elif sort == 'name':                      # 按路径最后一段（影片文件夹 / 文件名），约等于按片名
        rs = sorted(rs, key=lambda r: (_name_key(r), r['path']))
    limit = max(1, min(limit, 1000))
    out = {'total': len(rs), 'gb': round(sum(r['gb'] for r in rs), 1), 'rows': rs[offset:offset + limit], 'all': len(allrows),
           'kept_hidden': _hidden_info(hidden)}
    if facets:
        out['facets'] = facet_counts(allrows, bucket, stage, cls, q, flag, tag)
    return out


_groups_cache = {}


def load_groups(d):
    key = str(d)
    if key not in _groups_cache:
        _groups_cache.clear()
        f = d / 'groups.json'
        _groups_cache[key] = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    return _groups_cache[key]


@app.get('/api/cards')
def cards(bucket: str = '', stage: str = '', cls: str = '', q: str = '', flag: str = '', offset: int = 0, limit: int = 50,
          sort: str = 'gb', run_id: str = '', facets: int = 0, tag: str = ''):
    """清单按片展示：同一组（同一部片）的行合成一张卡，留的那份和要清的并排；没有组的行（主库缺口、孤本…）一行一张卡。
    筛选口径和 /api/rows 完全一样，只是按卡分页；每张卡带上整组成员（保留份、版本对、不碰的也在里面）。"""
    res, d = load_run(run_id or None)
    if not res:
        return {'total': 0, 'rows_total': 0, 'gb': 0, 'cards': [], 'all': 0, 'facets': {}, 'kept_hidden': {'count': 0, 'gb': 0}}
    allrows, hidden = shown_rows(d)
    rs = filter_rows(allrows, bucket, stage, cls, q, flag, tag)
    by = {}
    for r in rs:
        k = ('g:' + r['grp']) if r.get('grp') else ('p:' + r['path'] + '|' + r['stage'])
        by.setdefault(k, []).append(r)
    cs = [{'key': k, 'grp': v[0].get('grp') or '', 'rows': v, 'gb': round(sum(r['gb'] for r in v), 3)} for k, v in by.items()]
    if sort in ('gb', 'gb_desc'):
        cs.sort(key=lambda c: -c['gb'])
    elif sort == 'gb_asc':
        cs.sort(key=lambda c: c['gb'])
    elif sort == 'path':
        cs.sort(key=lambda c: c['rows'][0]['path'])
    elif sort == 'name':
        cs.sort(key=lambda c: (_name_key(c['rows'][0]), c['rows'][0]['path']))
    limit = max(1, min(limit, 200))
    page = cs[offset:offset + limit]
    gs = load_groups(d) if any(c['grp'] for c in page) else {}
    from panel import nametags
    ex = C.load().get('subfx_groups') or []
    def tagged(x):                     # 反馈 25 / 26：名字里的标签（只做展示）；nfx = 其中特效字幕组名单上的，淡色标
        t = nametags.tags(x['path'], ex)
        return dict(x, ntags=t, nfx=nametags.listed(t, ex))
    for c in page:
        g = gs.get(c['grp']) if c['grp'] else None
        if g:
            c['title'] = g.get('title') or ''
            c['members'] = [tagged(m) for m in g.get('members') or []]
        c['rows'] = [tagged(r) for r in c['rows']]
    out = {'total': len(cs), 'rows_total': len(rs), 'gb': round(sum(r['gb'] for r in rs), 1), 'cards': page,
           'all': len(allrows), 'kept_hidden': _hidden_info(hidden)}
    if facets:
        out['facets'] = facet_counts(allrows, bucket, stage, cls, q, flag, tag)
    return out


@app.get('/api/group/{gid}')
def group_detail(gid: str, run_id: str = ''):
    """重复副本的一整组：保留份、版本对、可清理、需人工确认、不碰的，一次看全。"""
    res, d = load_run(run_id or None)
    if not res:
        raise HTTPException(404, '还没有扫描结果')
    f = d / 'groups.json'
    if not f.exists():
        raise HTTPException(404, '这一轮没有分组信息（旧版结果，重新扫描后才有）')
    g = json.loads(f.read_text(encoding='utf-8')).get(gid)
    if not g:
        raise HTTPException(404, '没有这个组')
    return g


@app.get('/api/rows/paths')
def rows_paths(bucket: str = '', stage: str = '', cls: str = '', q: str = '', flag: str = '', run_id: str = '', tag: str = ''):
    """「全选」作用于当前筛选的全部结果（跨页）：返回全部匹配路径。"""
    res, d = load_run(run_id or None)
    if not res:
        return {'paths': []}
    return {'paths': list(dict.fromkeys(r['path'] for r in filter_rows(shown_rows(d)[0], bucket, stage, cls, q, flag, tag)))}


# 导出给人看：分类/来源/判定用白话名，最后一列保留内部叫法便于对账
COLS = [('分类', lambda r: L.bucket(r['bucket'])), ('能不能动', lambda r: L.BUCKETS.get(r['bucket'], ('', '', ''))[2]),
        ('类别', lambda r: L.stage(r['stage'])), ('判定', lambda r: L.cls(r['stage'], r['cls'])),
        ('标签', lambda r: ' / '.join(r.get('tags') or [])),
        ('候选路径', lambda r: r['path']), ('GB', lambda r: r['gb']), ('保留的那份 / 参照', lambda r: r.get('keep', '')),
        ('依据', lambda r: r.get('basis', '')), ('组号', lambda r: r.get('grp', '')),
        ('内部分类', lambda r: '%s/%s/%s' % (r['bucket'], r['stage'], r['cls']))]


def _csv_bytes(rs):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[0] for c in COLS])
    for r in rs:
        w.writerow([c[1](r) for c in COLS])
    return ('﻿' + buf.getvalue()).encode('utf-8')


def _export_guard(res, buckets):
    if '可切' in buckets and res.get('stale'):
        raise HTTPException(409, '筛选完之后改过设置，这份结果已过期，请重新筛选后再导出「可清理」')
    if '可切' in buckets and res.get('rejected'):
        raise HTTPException(409, '「可清理」里有条目落在保护区/榜单包里，整批不能导出，请先修正设置再重新筛选')


def _export_resp(res, rs, label, fmt):
    _export_guard(res, {r['bucket'] for r in rs})
    if fmt == 'json':
        body = json.dumps([dict(r, 分类=L.bucket(r['bucket']), 类别=L.stage(r['stage']), 判定=L.cls(r['stage'], r['cls']))
                           for r in rs], ensure_ascii=False, indent=1).encode('utf-8')
        name, mt = 'sieve_%s_%s.json' % (res['run_id'], label), 'application/json; charset=utf-8'
    else:
        body, name, mt = _csv_bytes(rs), 'sieve_%s_%s.csv' % (res['run_id'], label), 'text/csv; charset=utf-8'
    return Response(body, media_type=mt, headers={'Content-Disposition': "attachment; filename*=UTF-8''" + _q(name)})


@app.get('/api/export')
def export(bucket: str = '', stage: str = '', cls: str = '', q: str = '', flag: str = '', run_id: str = '', fmt: str = 'csv',
           tag: str = ''):
    res, d = load_run(run_id or None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    rs = sorted(filter_rows(shown_rows(d)[0], bucket, stage, cls, q, flag, tag), key=lambda r: -r['gb'])
    return _export_resp(res, rs, L.bucket(bucket) if bucket else '全部', fmt)


@app.post('/api/export/selected')
async def export_selected(request: Request, fmt: str = 'csv'):
    """清单里勾选的条目单独导出（只导出，不批准、不执行）。"""
    body = await request.json()
    res, d = load_run(body.get('run_id') or None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    want = set(body.get('paths') or [])
    rs = sorted([r for r in shown_rows(d)[0] if r['path'] in want], key=lambda r: -r['gb'])
    if not rs:
        raise HTTPException(400, '没有勾选任何条目')
    return _export_resp(res, rs, '已勾选', fmt)


@app.get('/api/export.zip')
def export_zip(run_id: str = ''):
    res, d = load_run(run_id or None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    shown, hidden = shown_rows(d)
    allrows = sorted(shown, key=lambda r: -r['gb'])
    buckets = sorted({r['bucket'] for r in allrows})
    skip_reason = zip_withheld_reason(res)
    skip_cut = bool(skip_reason)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        for b in buckets:
            if b == '可切' and skip_cut:
                continue
            z.writestr('%s.csv' % L.bucket(b), _csv_bytes([r for r in allrows if r['bucket'] == b]))
        if hidden:
            # 已确认保留的待定行不进「需人工确认.csv」，但单独成表——不出现的东西也要有账
            z.writestr('已确认保留（已隐藏）.csv', _csv_bytes(sorted(hidden, key=lambda r: -r['gb'])))
        if skip_cut:
            # 不静默扣下：包里放一份说明，和页面上弹出的原因一致
            z.writestr('_未包含「可清理」的原因.txt', ('\ufeff' + skip_reason + '\r\n').encode('utf-8'))
        z.writestr('summary.json', json.dumps({k: res.get(k) for k in (
            'run_id', 'fingerprint', 'stale', 'rejected', 'summary', 'detail', 'groups', 'engine',
            'held_stage2', 'stage3_population', 'protect_violations')}, ensure_ascii=False, indent=2))
    mem.seek(0)
    return StreamingResponse(mem, media_type='application/zip', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + _q('sieve_%s.zip' % res['run_id'])})


def zip_withheld_reason(res):
    try:
        _export_guard(res, {'可切'})
        return ''
    except HTTPException as e:
        return '这个压缩包里没有「可清理」清单：' + e.detail


@app.get('/api/export.check')
def export_check(run_id: str = ''):
    """导出全部之前先问一句：会不会扣下「可清理」、为什么。"""
    res, _ = load_run(run_id or None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    return {'withheld': zip_withheld_reason(res)}


@app.get('/api/keeps')
def keeps_get():
    """「已确认保留」名单；hit = 最新结果里还命中（还会被隐藏）的条目。"""
    items = K.load()
    res, d = load_run(None)
    live = {r['path'] for r in (load_rows(d) if res else []) if r['bucket'] == K.BUCKET}
    out = [dict(v, path=p, hit=p in live, stage_name=L.stage(v.get('stage', '')), cls_name=L.cls(v.get('stage', ''), v.get('cls', '')))
           for p, v in items.items()]
    out.sort(key=lambda x: x.get('at', ''), reverse=True)
    return {'items': out}


@app.post('/api/keeps')
async def keeps_add(request: Request):
    """{paths: [...]} 记为「已确认保留」：只收最新结果里的「需人工确认」条目。"""
    body = await request.json()
    res, d = load_run(None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    by = {}
    for r in load_rows(d):
        by.setdefault(r['path'], []).append(r)
    ok, skipped = K.add(by, list(dict.fromkeys(body.get('paths') or [])))
    return {'added': len(ok), 'skipped': skipped}


@app.post('/api/keeps/remove')
async def keeps_remove(request: Request):
    """{paths: [...]} 撤销：下一次看清单 / 重跑时这些条目重新出现在「需人工确认」里。"""
    body = await request.json()
    return {'removed': K.remove(body.get('paths') or [])}


@app.get('/api/log')
def log(run_id: str = ''):
    rid = run_id or JOB.state.get('run_id')
    if not rid or '/' in rid or '\\' in rid or '..' in rid:
        raise HTTPException(404)
    f = C.RUNS_DIR / rid / 'run.log'
    if not f.exists():
        raise HTTPException(404)
    return Response(f.read_text(encoding='utf-8', errors='replace')[-200000:], media_type='text/plain; charset=utf-8')


def _q(s):
    from urllib.parse import quote
    return quote(s)
