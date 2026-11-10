"""数据源适配：CD2 挂载目录扫描、CD2/Emby 数据库只读识别、Emby 片库读取、生成内核所需五张 CSV。

红线：CD2 缓存与 Emby 库只以 SQLite 只读模式打开（打不开时拷快照到 DATA_DIR 再读副本），
从不写回；挂载目录只做 listdir/stat。本模块没有任何删除、移动、改名调用。
"""
import csv
import os
import re
import shutil
import sqlite3
from collections import Counter, defaultdict

from . import config as C

VIDEO_EXT = {'.iso', '.mkv', '.mp4', '.m2ts', '.ts', '.avi', '.wmv', '.mov', '.rmvb', '.flv'}
DISC_DIRS = {'bdmv', 'video_ts'}
GB = 1024 ** 3


# ---------------- 路径换算 ----------------
def to_real(cfg, vpath):
    return os.path.join(cfg['cd2_mount'], *[p for p in vpath.split('/') if p])


def to_virtual(cfg, real):
    rel = os.path.relpath(real, cfg['cd2_mount']).replace(os.sep, '/')
    return '/' if rel == '.' else '/' + rel


def blocked_names(cfg):
    return list(cfg['protect_names']) + list(cfg['listpack_names'])


def hit_any(text, names):
    return next((n for n in names if n and n in text), None)


# ---------------- 目录树（盘点页勾选用） ----------------
def list_dirs(cfg, vpath='/'):
    if not cfg['cd2_mount'] or not os.path.isdir(cfg['cd2_mount']):
        raise FileNotFoundError('CD2 挂载目录不存在：%r' % cfg['cd2_mount'])
    real = to_real(cfg, vpath)
    out = []
    with os.scandir(real) as it:
        for e in it:
            try:
                if e.is_dir(follow_symlinks=False):
                    out.append(e.name)
            except OSError:
                pass
    out.sort()
    base = vpath.rstrip('/')
    return [{'name': n, 'path': base + '/' + n} for n in out]


# ---------------- 扫描 ----------------
def dir_size(real):
    tot = 0
    for dp, _, fns in os.walk(real, onerror=lambda e: None):
        for fn in fns:
            try:
                tot += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return tot


def walk_zone(cfg, vroot, errors, progress=None):
    """遍历一个分区，产出 ('disc', 虚拟夹路径, 字节) / ('file', 虚拟文件路径, 字节)。
    保护区 / 榜单包目录整枝剪掉（判定层排除）。"""
    blocked = blocked_names(cfg)
    minb = cfg['min_video_mb'] * 1024 * 1024
    real_root = to_real(cfg, vroot)
    if not os.path.isdir(real_root):
        errors.append('分区目录不存在：' + vroot)
        return
    n = 0
    for dp, dns, fns in os.walk(real_root, onerror=lambda e: errors.append(str(e))):
        dns[:] = sorted(d for d in dns if not hit_any(d, blocked))
        n += 1
        if progress and n % 200 == 0:
            progress('扫描 %s … 已过 %d 个目录' % (vroot, n))
        if any(d.lower() in DISC_DIRS for d in dns):
            yield 'disc', to_virtual(cfg, dp), dir_size(dp)
            dns[:] = []
            continue
        for fn in sorted(fns):
            if os.path.splitext(fn)[1].lower() not in VIDEO_EXT:
                continue
            try:
                size = os.path.getsize(os.path.join(dp, fn))
            except OSError as e:
                errors.append(str(e))
                continue
            if size >= minb:
                yield 'file', to_virtual(cfg, os.path.join(dp, fn)), size


def gb(b):
    return round(b / GB, 3)


def scan_inputs(cfg, workdir, progress):
    """扫 CD2 挂载目录 + 读 Emby，生成内核要的五张 CSV。返回 (盘点统计, 文件清单, 错误)。"""
    errors = []
    files = []                     # [(zone, vpath, gb, form)]
    stats = {}

    # 原盘区 → yuanpan_units.csv / yuanpan_files.csv
    units, yfiles = [], []
    for root in cfg['zones']['yuanpan']:
        progress('扫描原盘区 ' + root)
        folder_tot = defaultdict(int)
        for kind, vp, size in walk_zone(cfg, root, errors, progress):
            if kind == 'disc':
                units.append({'path': vp, 'name': vp.rsplit('/', 1)[-1], 'kind': 'BDMV', 'totGB': gb(size)})
                files.append(('yuanpan', vp, gb(size), 'BDMV'))
            else:
                yfiles.append({'path': vp, 'GB': gb(size)})
                folder_tot[vp.rsplit('/', 1)[0]] += size
                files.append(('yuanpan', vp, gb(size), os.path.splitext(vp)[1][1:].upper()))
        for folder, size in folder_tot.items():
            units.append({'path': folder, 'name': folder.rsplit('/', 1)[-1], 'kind': 'FILES', 'totGB': gb(size)})
    _write(workdir, 'yuanpan_units.csv', ['path', 'name', 'kind', 'totGB'], units, 'utf-8')
    _write(workdir, 'yuanpan_files.csv', ['path', 'GB'], yfiles, 'utf-8')

    # 合集区 → heji_films.csv（大包 = 分区根下第一级目录）
    heji = []
    for root in cfg['zones']['heji']:
        progress('扫描合集区 ' + root)
        for kind, vp, size in walk_zone(cfg, root, errors, progress):
            rel = vp[len(root):].strip('/').split('/')
            top = rel[0] if len(rel) > 1 else root.rsplit('/', 1)[-1]
            name = vp.rsplit('/', 1)[-1]
            form = 'ISO' if kind == 'disc' else os.path.splitext(name)[1][1:].upper()
            heji.append({'大包': top, '片名(文件名)': name, 'GB': gb(size), '形态': form, '路径': vp})
            files.append(('heji', vp, gb(size), form))
    _write(workdir, 'heji_films.csv', ['大包', '片名(文件名)', 'GB', '形态', '路径'], heji, 'utf-8-sig')

    # REMUX 区：第一期只盘点（判定模块未收编）
    for root in cfg['zones']['remux']:
        progress('盘点 REMUX 区 ' + root)
        for kind, vp, size in walk_zone(cfg, root, errors, progress):
            files.append(('remux', vp, gb(size), 'ISO' if kind == 'disc' else os.path.splitext(vp)[1][1:].upper()))

    # Emby → emby_yp.csv / emby_titles.csv
    progress('读取 Emby 片库')
    emby_info = write_emby_csvs(cfg, workdir, errors)

    for z in ('heji', 'yuanpan', 'remux'):
        fz = [f for f in files if f[0] == z]
        stats[z] = {'count': len(fz), 'gb': round(sum(f[2] for f in fz), 1)}
    tops = Counter()
    topgb = Counter()
    for h in heji:
        tops[h['大包']] += 1
        topgb[h['大包']] += h['GB']
    stats['heji_packs'] = [{'name': k, 'count': v, 'gb': round(topgb[k], 1)} for k, v in tops.most_common(40)]
    stats['emby'] = emby_info
    return stats, files, errors


def csv_inputs(cfg, workdir, progress):
    """CSV 模式：从 csv_dir 拷五张表进工作目录（不改内容）。"""
    errors = []
    src = cfg['csv_dir']
    need = ['yuanpan_units.csv', 'yuanpan_files.csv', 'emby_yp.csv', 'heji_films.csv', 'emby_titles.csv']
    missing = [n for n in need if not os.path.isfile(os.path.join(src, n))]
    if missing:
        raise FileNotFoundError('CSV 目录 %s 缺少：%s' % (src, '、'.join(missing)))
    for n in need:
        progress('载入 ' + n)
        shutil.copyfile(os.path.join(src, n), os.path.join(workdir, n))
    files = []
    with open(os.path.join(workdir, 'heji_films.csv'), encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            files.append(('heji', r['路径'], float(r['GB']), r['形态']))
    with open(os.path.join(workdir, 'yuanpan_files.csv'), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            files.append(('yuanpan', r['path'], float(r['GB']), os.path.splitext(r['path'])[1][1:].upper()))
    stats = {z: {'count': sum(1 for x in files if x[0] == z),
                 'gb': round(sum(x[2] for x in files if x[0] == z), 1)} for z in ('heji', 'yuanpan')}
    stats['remux'] = {'count': 0, 'gb': 0}
    return stats, files, errors


def _write(workdir, name, header, rows, enc):
    with open(os.path.join(workdir, name), 'w', newline='', encoding=enc) as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


# ---------------- SQLite 只读 ----------------
def find_file(root, name, maxdepth=6):
    if not root or not os.path.isdir(root):
        return None
    root = os.path.abspath(root)
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dp, dns, fns in os.walk(root, onerror=lambda e: None):
        if name in fns:
            return os.path.join(dp, name)
        if dp.count(os.sep) - base_depth >= maxdepth:
            dns[:] = []
    return None


def open_ro(path):
    """只读打开；失败（如目录只读导致 -shm 建不了）则拷快照读副本。"""
    try:
        uri = 'file:' + path.replace('\\', '/').replace('?', '%3f') + '?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
        conn.execute('select count(*) from sqlite_master').fetchone()
        return conn, '只读直连'
    except sqlite3.Error:
        snap = C.DATA_DIR / 'snapshot'
        snap.mkdir(parents=True, exist_ok=True)
        dst = snap / os.path.basename(path)
        for ext in ('', '-wal'):
            if os.path.exists(path + ext):
                shutil.copyfile(path + ext, str(dst) + ext)
        return sqlite3.connect(str(dst)), '快照副本'


def probe_cd2(cfg):
    out = {'mount': cfg['cd2_mount'], 'mount_ok': bool(cfg['cd2_mount']) and os.path.isdir(cfg['cd2_mount'])}
    if out['mount_ok']:
        try:
            out['mount_top'] = [d['name'] for d in list_dirs(cfg, '/')][:30]
        except OSError as e:
            out['mount_error'] = str(e)
    db = find_file(cfg['cd2_config'], 'dir_cache.sqlite')
    out['dir_cache'] = db
    if db:
        try:
            conn, how = open_ro(db)
            with conn:
                tabs = [r[0] for r in conn.execute("select name from sqlite_master where type='table'")]
                out['tables'] = {t: conn.execute('select count(*) from "%s"' % t.replace('"', '""')).fetchone()[0]
                                 for t in tabs[:20]}
            conn.close()
            out['open_mode'] = how
        except Exception as e:
            out['error'] = str(e)
    return out


TMDB_RE = re.compile(r'tmdb=(\d+)', re.I)
VIDEO_STREAM_TYPE = 2      # Emby 流表 StreamType：视频流


def nominal_vh(w, h):
    """宽银幕片按宽度折回名义档：3840x1600 → 2160，1920x800 → 1080。"""
    w, h = int(w or 0), int(h or 0)
    if w >= 3200: return max(h, 2160)
    if w >= 1800: return max(h, 1080)
    if w >= 1200: return max(h, 720)
    return h


def emby_items(cfg):
    db = find_file(cfg['emby_data'], 'library.db')
    if not db:
        raise FileNotFoundError('在 %r 下没找到 library.db' % cfg['emby_data'])
    conn, how = open_ro(db)
    conn.row_factory = sqlite3.Row
    try:
        tabs = {r[0].lower(): r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        table = tabs.get('mediaitems') or tabs.get('typedbaseitems')
        if not table:
            raise RuntimeError('library.db 里没有 MediaItems / TypedBaseItems 表')
        cols = {r[1].lower(): r[1] for r in conn.execute('pragma table_info("%s")' % table)}
        want = ['id', 'type', 'path', 'name', 'productionyear', 'providerids', 'width', 'height',
                'seriesname', 'indexnumber', 'parentindexnumber', 'isfolder']
        sel = [cols[w] for w in want if w in cols]
        if 'path' not in cols:
            raise RuntimeError('%s 表没有 Path 列' % table)
        rows = [dict(r) for r in conn.execute('select %s from "%s" where %s is not null' %
                                              (','.join('"%s"' % s for s in sel), table, cols['path']))]
        # 新版 Emby 分辨率可能只在流表里：4.8.x 叫 MediaStreams2，更早叫 MediaStreams
        stab = tabs.get('mediastreams2') or tabs.get('mediastreams')
        if stab and 'id' in cols:
            mcols = {r[1].lower(): r[1] for r in conn.execute('pragma table_info("%s")' % stab)}
            if {'itemid', 'width', 'height'} <= set(mcols):
                res = {}
                where = '"%s">0' % mcols['width']
                if 'streamtype' in mcols:           # 只取视频流，别混进音频/字幕
                    where += ' and "%s"=%d' % (mcols['streamtype'], VIDEO_STREAM_TYPE)
                for r in conn.execute('select "%s","%s","%s" from "%s" where %s' % (
                        mcols['itemid'], mcols['width'], mcols['height'], stab, where)):
                    if r[0] not in res or r[1] > res[r[0]][0]:
                        res[r[0]] = (r[1], r[2])
                for it in rows:
                    key = it.get(cols['id'])
                    if not it.get(cols.get('width', '_')) and key in res:
                        it['__w'], it['__h'] = res[key]
    finally:
        conn.close()

    def g(it, k):
        return it.get(cols[k]) if k in cols else None

    type_is_str = any(isinstance(g(it, 'type'), str) for it in rows[:200])
    out = []
    for it in rows:
        t = g(it, 'type')
        if type_is_str:
            movie = str(t).endswith('Movie')
        else:
            movie = not g(it, 'seriesname') and not (g(it, 'indexnumber') is not None
                                                        and g(it, 'parentindexnumber') is not None) \
                    and not g(it, 'isfolder')
        m = TMDB_RE.search(g(it, 'providerids') or '')
        out.append({
            'path': str(g(it, 'path')).replace('\\', '/'),
            'name': g(it, 'name') or '',
            'year': str(g(it, 'productionyear') or ''),
            'tmdb': m.group(1) if m else '',
            'width': int(g(it, 'width') or it.get('__w') or 0),
            'height': int(g(it, 'height') or it.get('__h') or 0),
            'movie': movie,
        })
    return out, {'db': db, 'open_mode': how, 'table': table, 'type_col': 'type' in cols,
                 'type_is_str': type_is_str}


def probe_emby(cfg):
    try:
        items, meta = emby_items(cfg)
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    pre = cfg['emby_prefix'].rstrip('/')
    movies = [i for i in items if i['movie']]
    return dict(meta, ok=True, items=len(items), movies=len(movies),
                movies_tmdb=sum(1 for i in movies if i['tmdb']),
                movies_res=sum(1 for i in movies if i['width']),
                under_prefix=sum(1 for i in items if pre and i['path'].startswith(pre + '/')),
                sample_paths=[i['path'] for i in movies[:5]])


def write_emby_csvs(cfg, workdir, errors):
    pre = cfg['emby_prefix'].rstrip('/')
    try:
        items, meta = emby_items(cfg)
    except Exception as e:
        errors.append('Emby：' + str(e) + '（纵向轴与原盘实测分辨率将缺失）')
        items, meta = [], {}
    yp, titles = [], []
    for i in items:
        if pre and i['path'].startswith(pre + '/') and i['width']:
            # 内核写死 replace('/CloudNAS/CloudDrive','')，这里统一换成该前缀以对上挂载虚拟路径
            yp.append({'source_path': '/CloudNAS/CloudDrive' + i['path'][len(pre):],
                       'width': i['width'], 'height': i['height']})
        if i['movie'] and (i['tmdb'] or i['name']):
            titles.append({'tmdb': i['tmdb'], 'name': i['name'], 'year': i['year'],
                           'max_vh': nominal_vh(i['width'], i['height'])})
    _write(workdir, 'emby_yp.csv', ['source_path', 'width', 'height'], yp, 'utf-8')
    _write(workdir, 'emby_titles.csv', ['tmdb', 'name', 'year', 'max_vh'], titles, 'utf-8-sig')
    return {'items': len(items), 'movies': len(titles), 'matched_paths': len(yp), 'table': meta.get('table')}
