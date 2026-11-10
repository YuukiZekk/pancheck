"""CloudDrive2 目录缓存（dir_cache.sqlite）读取：盘点的主数据源，零网盘请求。

表结构（schema_version = 1）：
  cached_item(id, path, insert_time)        被 CD2 列过的每个文件夹一行，path 为完整虚拟路径
  files(id, parent_id → cached_item.id, name, file_type 3=夹/4=文件, size, api_name, api_user, ...)
口径：
  - 全路径 = 父夹 cached_item.path + '/' + files.name（根是 '/'，别拼出双斜杠）
  - 只认目标网盘：按 api_name 过滤（115 = '115open'），可选再按 api_user 区分账号
  - 文件夹 size 恒 0，体积只能汇总文件行
  - 缓存是「CD2 列到哪算哪」的采样，结果以缓存时刻为准；要回显 insert_time 范围
  - 只读打开；库带 WAL，拷快照时连 -wal 一起（见 sources.open_ro）
产出与挂载遍历（sources.walk_zone）同形同序的条目，后面生成五张 CSV 的代码两种来源共用。
"""
import os
import threading
from collections import defaultdict

from . import sources as S


def find_db(cfg):
    db = S.find_file(cfg.get('cd2_config'), 'dir_cache.sqlite')
    if not db:
        raise FileNotFoundError('在 CD2 配置目录 %r 下没找到 dir_cache.sqlite' % cfg.get('cd2_config'))
    return db


def _api_where(cfg, alias='f'):
    sql, args = '%s.api_name = ?' % alias, [cfg.get('cd2_api_name') or '115open']
    if cfg.get('cd2_api_user'):
        sql += ' and %s.api_user = ?' % alias
        args.append(str(cfg['cd2_api_user']))
    return sql, args


def _under(col='ci.path'):
    """路径等于分区根，或以「根/」开头（不用 LIKE，免得片名里的 % _ 被当通配符）。"""
    return '(%s = ? or substr(%s, 1, ?) = ?)' % (col, col)


def _under_args(root):
    rs = root.rstrip('/') + '/'
    return [root, len(rs), rs]


def _stamp(db):
    out = []
    for ext in ('', '-wal'):
        try:
            st = os.stat(db + ext)
            out.append((st.st_size, st.st_mtime))
        except OSError:
            out.append(None)
    return tuple(out)


# ---------------- 目录树（盘点页勾选、按目录名建议） ----------------
_tree_lock = threading.Lock()
_tree = {'key': None, 'children': None}


def _children_map(cfg):
    db = find_db(cfg)
    key = (db, _stamp(db))
    with _tree_lock:
        if _tree['key'] != key:
            conn, _ = S.open_ro(db)
            try:
                ch = defaultdict(set)
                for (p,) in conn.execute('select path from cached_item'):
                    p = (p or '').rstrip('/')
                    if not p:
                        continue
                    parent, _, name = p.rpartition('/')
                    ch[parent or '/'].add(name)
                    # 补齐中间层（缓存里只有深层目录、父层没被单独列过时）
                    while parent:
                        gp, _, pn = parent.rpartition('/')
                        ch[gp or '/'].add(pn)
                        parent = gp
            finally:
                conn.close()
            _tree.update(key=key, children=ch)
        return _tree['children']


def list_dirs(cfg, vpath='/'):
    ch = _children_map(cfg)
    base = '/' + vpath.strip('/') if vpath.strip('/') else '/'
    parent, _, name = base.rpartition('/')
    if base != '/' and name not in ch.get(parent or '/', ()):
        raise FileNotFoundError('缓存里没有这个目录：%s' % vpath)
    names = sorted(ch.get(base, ()))
    pre = '' if base == '/' else base
    return [{'name': n, 'path': pre + '/' + n} for n in names]


_tops = {'key': None, 'tops': None}


def api_tops(cfg):
    """目标网盘（api_name/api_user）的文件落在哪些顶层目录下，比如 {'115'}；按目录名给建议时只看这些。"""
    db = find_db(cfg)
    api_sql, api_args = _api_where(cfg)
    key = (db, _stamp(db), tuple(api_args))
    with _tree_lock:
        if _tops['key'] != key:
            conn, _ = S.open_ro(db)
            try:
                tops = set()
                for (p,) in conn.execute('select distinct ci.path from files f join cached_item ci on ci.id = f.parent_id '
                                         'where ' + api_sql, api_args):
                    seg = (p or '').strip('/').split('/', 1)[0]
                    if seg:
                        tops.add(seg)
            finally:
                conn.close()
            _tops.update(key=key, tops=tops)
        return _tops['tops']


# ---------------- 识别回显 ----------------
def probe(cfg):
    db = find_db(cfg)
    conn, how = S.open_ro(db)
    try:
        tabs = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        if not {'cached_item', 'files'} <= tabs:
            return {'db': db, 'open_mode': how, 'ok': False,
                    'error': '库里没有 cached_item / files 表，可能不是 CD2 的目录缓存或版本不同（表：%s）' % '、'.join(sorted(tabs))}
        ver = None
        if 'schema_version' in tabs:
            r = conn.execute('select max(version) from schema_version').fetchone()
            ver = r[0] if r else None
        folders, tmin, tmax = conn.execute('select count(*), min(insert_time), max(insert_time) from cached_item').fetchone()
        accounts = [{'api_name': a, 'api_user': u, 'files': nf or 0, 'folders': nd or 0} for a, u, nf, nd in conn.execute(
            'select api_name, api_user, sum(file_type = 4), sum(file_type = 3) from files group by 1, 2 order by 3 desc')]
    finally:
        conn.close()
    want = cfg.get('cd2_api_name') or '115open'
    mine = [a for a in accounts if a['api_name'] == want
            and (not cfg.get('cd2_api_user') or a['api_user'] == str(cfg['cd2_api_user']))]
    return {'db': db, 'open_mode': how, 'ok': True, 'schema_version': ver, 'cached_folders': folders,
            'time_min': tmin, 'time_max': tmax, 'accounts': accounts, 'api_name': want,
            'matched_files': sum(a['files'] for a in mine), 'matched_accounts': len(mine)}


# ---------------- 盘点条目 ----------------
def _walk_key(vp, is_disc):
    """复刻 os.walk(自上而下、子目录与文件都按名排序) 的产出顺序：同一目录里先文件、后子目录。
    内核对同档同体积的并列按出现顺序取舍，顺序一致两种数据源的结果才逐条一致。"""
    parts = vp.strip('/').split('/')
    if is_disc:
        return tuple((1, p) for p in parts)
    return tuple((1, p) for p in parts[:-1]) + ((0, parts[-1]),)


def zone_items(cfg, progress, errors):
    """返回 ({zone: [(root, kind, vp, size_bytes)]}, 元信息)。与挂载遍历同形同序。"""
    db = find_db(cfg)
    progress('打开 CD2 目录缓存 ' + db)
    conn, how = S.open_ro(db)
    minb = cfg['min_video_mb'] * 1024 * 1024
    api_sql, api_args = _api_where(cfg)
    raw, tmins, tmaxs, rows_read, drops = {}, [], [], 0, {}
    try:
        for zone, label in (('yuanpan', '原盘区'), ('heji', '合集区'), ('remux', 'REMUX 区')):
            raw[zone], drops[zone] = [], S.Counter()
            for root in cfg['zones'][zone]:
                progress('从缓存读取%s %s' % (label, root))
                tmin, tmax, nd = conn.execute(
                    'select min(insert_time), max(insert_time), count(*) from cached_item ci where ' + _under(),
                    _under_args(root)).fetchone()
                if not nd:
                    errors.append('缓存里没有 %s 的记录（CD2 还没打开过这个目录，或路径填错了）' % root)
                    continue
                tmins.append(tmin)
                tmaxs.append(tmax)
                files, disc_roots = [], set()
                for ppath, name, ftype, size in conn.execute(
                        'select ci.path, f.name, f.file_type, f.size from files f join cached_item ci on ci.id = f.parent_id '
                        'where ' + api_sql + ' and ' + _under(), api_args + _under_args(root)):
                    rows_read += 1
                    ppath = ppath.rstrip('/')
                    vp = ppath + '/' + name
                    if ftype == 3:
                        if name.lower() in S.DISC_DIRS:
                            disc_roots.add(ppath)
                    elif ftype == 4:
                        files.append((vp, size or 0))
                        for comp_i, comp in enumerate(vp.split('/')[:-1]):
                            if comp.lower() in S.DISC_DIRS:       # 父链里有 BDMV（夹行没被缓存时兜底）
                                disc_roots.add('/'.join(vp.split('/')[:comp_i]))
                                break
                # 和挂载遍历一致：自上而下遇到的第一层盘片夹整夹算一张盘，夹内所有文件计入体积
                disc_roots = {d for d in disc_roots if d == root or d.startswith(root.rstrip('/') + '/')}
                tops = {d for d in disc_roots if not any(d != o and d.startswith(o + '/') for o in disc_roots)}
                disc_size = defaultdict(int)
                items = []
                for vp, size in files:
                    parts = vp.split('/')
                    disc = next(('/'.join(parts[:i]) for i in range(2, len(parts))
                                 if '/'.join(parts[:i]) in tops), None)
                    if disc:
                        disc_size[disc] += size
                    elif os.path.splitext(vp)[1].lower() in S.VIDEO_EXT and size >= minb:
                        items.append((_walk_key(vp, False), 'file', vp, size))
                    else:
                        S.drop_note(drops, zone, vp, size, minb)
                for d in tops:
                    items.append((_walk_key(d, True), 'disc', d, disc_size.get(d, 0)))
                items.sort(key=lambda x: x[0])
                raw[zone] += [(root, kind, vp, size) for _, kind, vp, size in items]
    finally:
        conn.close()
    meta = {'kind': 'cache', 'db': db, 'open_mode': how, 'rows_read': rows_read, 'drops': drops,
            'time_min': min(tmins) if tmins else None, 'time_max': max(tmaxs) if tmaxs else None,
            'api_name': api_args[0], 'api_user': cfg.get('cd2_api_user') or ''}
    return raw, meta
