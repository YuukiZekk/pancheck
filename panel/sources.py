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
# 不计入的其他视频格式：只用来统计「被体积/格式门槛挡掉的文件」，帮对账定位人口差
OTHER_VIDEO_EXT = {'.mpg', '.mpeg', '.vob', '.m4v', '.webm', '.f4v', '.divx', '.3gp', '.rm', '.asf', '.mts', '.m2t', '.dat'}
# 提取层分集口径 = 手工流程 heji_film.py 原文：只认 SxxExx 与「第N集」，只看文件名
# （内核 sieve.EP 更宽，还认 EP01/第N话，那是判定层「疑似剧集」用的，不拿来分人口）
SPLIT_EP = re.compile(r'(?i)(s\d{1,2}e\d{1,3}|第\s*\d+\s*集)')
TMDB_TAG = re.compile(r'tmdb(?:id)?[=:\-]?(\d{3,7})', re.I)


def drop_note(drops, zone, vp, size, minb):
    """记一笔被门槛挡掉的视频文件（体积太小 / 不在计入格式里）。"""
    ext = os.path.splitext(vp)[1].lower()
    if ext in VIDEO_EXT and size < minb:
        drops[zone]['small'] += 1
    elif ext in OTHER_VIDEO_EXT:
        drops[zone]['ext' + ext] += 1


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


_NORM = re.compile(r'[\s\.\-_·：:、，,\[\]【】()（）]+')


def is_video_path(vp):
    return os.path.splitext(vp)[1].lower() in VIDEO_EXT


def film_unit_dirs(paths):
    """认出「单片夹」：夹内只有直接放着的视频文件、按内核 keyof1 只成一簇、且夹名里含这部片名。
    这类夹名里的简介字样（如「豆瓣9.1分」）不当保护词命中；拿不准的一律不算单片夹（偏向保护）。
    paths：虚拟路径列表；带视频扩展名的是文件，否则是一张盘（BDMV/VIDEO_TS 片夹本身）。"""
    import sieve                                       # 只借内核的 keyof1，不改内核
    direct = defaultdict(list)
    deep = set()                                       # 底下还有子层内容的夹，不算单片夹
    for vp in paths:
        parts = vp.rstrip('/').split('/')
        if is_video_path(vp):
            direct['/'.join(parts[:-1])].append(parts[-1])
            anc = parts[:-2]
        else:
            anc = parts[:-1]
        for i in range(2, len(anc) + 1):
            deep.add('/'.join(anc[:i]))
    units = set()
    for folder, names in direct.items():
        if folder in deep:
            continue
        keys = {sieve.keyof1(n) for n in names}
        if len(keys) != 1:
            continue
        title = next(iter(keys))[0]
        if len(title) >= 2 and title in _NORM.sub('', folder.rsplit('/', 1)[-1]).lower():
            units.add(folder)
    return units


def protect_hit(vp, names, units):
    """保护判定（扫描剪枝与可切守卫共用同一口径）：只看路径的目录组件，
    不看最后一段（文件名 / 盘片夹名），也不看被认作单片夹的那一层。返回命中的保护词。"""
    parts = vp.rstrip('/').split('/')
    for i in range(1, len(parts) - 1):
        comp = parts[i]
        if not comp or '/'.join(parts[:i + 1]) in units:
            continue
        n = hit_any(comp, names)
        if n:
            return n
    return None


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


# ---------------- 首次引导：按目录名建议分区 + 保护名模板 ----------------
ZONE_HINTS = {
    'heji': ('合集', '电影包', '打包', 'collection', 'pack'),
    'yuanpan': ('原盘', '蓝光', 'bdmv', 'blu-ray', 'bluray', 'iso'),
    'remux': ('remux',),
    'pack': (),                 # 整夹合集区靠用户手动指定
}
PROTECT_TEMPLATES = ['系列合集', '系列电影', '出品公司', '导演合集', '已刮削', '刮削完成',
                     '漫威', 'DC', '皮克斯', '迪士尼', '吉卜力', '宫崎骏', '收藏']


def dir_lister(cfg):
    """目录树来源：缓存模式读 dir_cache（零请求），其余模式列挂载目录。"""
    if cfg.get('data_source') == 'cache':
        from . import cd2cache
        return cd2cache.list_dirs
    return list_dirs


def suggest(cfg, max_depth=3, max_dirs=600):
    """只按目录名猜，只列目录（不 stat 文件），层数和数量都设上限，避免向网盘发大量请求。"""
    lister = dir_lister(cfg)
    seen, queue, out = 0, [('/', 0)], []
    while queue and seen < max_dirs:
        path, depth = queue.pop(0)
        try:
            dirs = lister(cfg, path)
        except OSError:
            continue
        for d in dirs:
            seen += 1
            out.append(d)
            if depth + 1 < max_depth:
                queue.append((d['path'], depth + 1))
    if cfg.get('data_source') == 'cache':
        # 缓存里可能混着别的网盘，只对目标网盘所在的顶层目录给分区建议
        from . import cd2cache
        tops = cd2cache.api_tops(cfg)
        out = [d for d in out if d['path'].strip('/').split('/', 1)[0] in tops]
    zones = {z: [] for z in ZONE_HINTS}
    for d in out:
        low = d['name'].lower()
        for z in ('remux', 'yuanpan', 'heji'):          # REMUX 优先，免得「REMUX 合集」被当成合集区
            if any(h in low for h in ZONE_HINTS[z]):
                # 父目录已被建议为同一分区的，不再重复建议子目录
                if not any(d['path'].startswith(p + '/') for p in zones[z]):
                    zones[z].append(d['path'])
                break
    names = [d['name'] for d in out]
    found = [t for t in PROTECT_TEMPLATES if any(t in n for n in names)]
    return {'zones': zones, 'protect_templates': PROTECT_TEMPLATES, 'protect_found': found,
            'scanned_dirs': seen, 'truncated': seen >= max_dirs}


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


def walk_zone(cfg, vroot, errors, progress=None, drops=None):
    """遍历一个分区，产出 ('disc', 虚拟夹路径, 字节) / ('file', 虚拟文件路径, 字节)。
    这里不按名字剪枝：保护判定要先认出单片夹，统一在 scan_inputs 里用 protect_hit 过滤。"""
    minb = cfg['min_video_mb'] * 1024 * 1024
    real_root = to_real(cfg, vroot)
    if not os.path.isdir(real_root):
        errors.append('分区目录不存在：' + vroot)
        return
    n = 0
    for dp, dns, fns in os.walk(real_root, onerror=lambda e: errors.append(str(e))):
        dns[:] = sorted(dns)
        n += 1
        if progress and n % 200 == 0:
            progress('扫描 %s … 已过 %d 个目录' % (vroot, n))
        if any(d.lower() in DISC_DIRS for d in dns):
            yield 'disc', to_virtual(cfg, dp), dir_size(dp)
            dns[:] = []
            continue
        for fn in sorted(fns):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in VIDEO_EXT:
                if drops is not None and ext in OTHER_VIDEO_EXT:
                    drops['ext' + ext] += 1
                continue
            try:
                size = os.path.getsize(os.path.join(dp, fn))
            except OSError as e:
                errors.append(str(e))
                continue
            if size >= minb:
                yield 'file', to_virtual(cfg, os.path.join(dp, fn)), size
            elif drops is not None:
                drops['small'] += 1


def gb(b):
    return round(b / GB, 3)


def scan_inputs(cfg, workdir, progress):
    """扫 CD2 挂载目录 + 读 Emby，生成内核要的五张 CSV。返回 (盘点统计, 文件清单, 错误)。"""
    errors = []
    files = []                     # [(zone, vpath, gb, form)]
    stats = {}

    # 先拿到三个分区的全部条目，再按统一口径剔除保护区 / 榜单包
    if cfg['data_source'] == 'cache':
        # 主路：读 CD2 自己的目录缓存，不向网盘发请求
        from . import cd2cache
        raw, stats['source'] = cd2cache.zone_items(cfg, progress, errors)
        drops = stats['source'].pop('drops', {})
    else:
        # 兜底：遍历 CD2 挂载目录（大库很慢，且每个目录都会经 CD2 向网盘发请求）
        raw, drops = {}, {}
        for zone, label in C.ZONES:
            raw[zone], drops[zone] = [], Counter()
            for root in cfg['zones'][zone]:
                progress('扫描%s %s' % (label, root))
                raw[zone] += [(root, kind, vp, size) for kind, vp, size in walk_zone(cfg, root, errors, progress, drops[zone])]
        stats['source'] = {'kind': 'scan'}
    stats['dropped'] = {z: dict(c) for z, c in drops.items() if c}
    unit_dirs = film_unit_dirs([it[2] for z in raw for it in raw[z]])
    # 提取层只剔保护区。榜单包留在人口里（与金标准同口径），由内核判定层整包不筛，守卫兜底整批拒绝
    blocked = list(cfg['protect_names'])
    skipped = Counter()
    skipped_bytes = 0
    lp_n, lp_bytes = 0, 0
    for z in raw:
        kept = []
        for it in raw[z]:
            n = protect_hit(it[2], blocked, unit_dirs)
            if n:
                skipped[n] += 1
                skipped_bytes += it[3]
            else:
                kept.append(it)
                if z == 'heji' and protect_hit(it[2], cfg['listpack_names'], unit_dirs):
                    lp_n += 1
                    lp_bytes += it[3]
        raw[z] = kept
    stats['protected_skipped'] = dict(skipped)
    stats['protected_gb'] = round(skipped_bytes / GB, 1)
    stats['listpack_kept'] = {'count': lp_n, 'gb': round(lp_bytes / GB, 1)}

    # 原盘区 → yuanpan_units.csv / yuanpan_files.csv
    units, yfiles = [], []
    folder_tot = defaultdict(int)
    for root, kind, vp, size in raw['yuanpan']:
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
    # 带集号的文件（手工 heji_film.py 口径：SxxExx / 第N集，只看文件名）在提取层分出去，归「混入的剧集」
    heji, ep_n, ep_bytes = [], 0, 0
    for root, kind, vp, size in raw['heji']:
        rel = vp[len(root):].strip('/').split('/')
        top = rel[0] if len(rel) > 1 else root.rsplit('/', 1)[-1]
        name = vp.rsplit('/', 1)[-1]
        form = 'ISO' if kind == 'disc' else os.path.splitext(name)[1][1:].upper()
        if kind == 'file' and SPLIT_EP.search(name):
            files.append(('tv', vp, gb(size), form))
            ep_n += 1
            ep_bytes += size
            continue
        heji.append({'大包': top, '片名(文件名)': name, 'GB': gb(size), '形态': form, '路径': vp})
        files.append(('heji', vp, gb(size), form))
    stats['heji_episodes'] = {'count': ep_n, 'gb': round(ep_bytes / GB, 1)}
    _write(workdir, 'heji_films.csv', ['大包', '片名(文件名)', 'GB', '形态', '路径'], heji, 'utf-8-sig')

    # REMUX 区 / 整夹合集区：按「单元」出 cross_units.csv，给跨区比对模块用（口径同 union_units.csv）
    from . import cross
    urows = []
    for z in ('remux', 'pack'):
        for root, kind, vp, size in raw[z]:
            files.append((z, vp, gb(size), 'ISO' if kind == 'disc' else os.path.splitext(vp)[1][1:].upper()))
        for root in cfg['zones'][z]:
            items = [(vp, size, kind) for r, kind, vp, size in raw[z] if r == root]
            for u in cross.build_units(items, VIDEO_EXT):
                rel = u['path'][len(root):].strip('/').split('/')
                area = 'REMUX' if z == 'remux' else (rel[0] if len(rel) > 1 else root.rsplit('/', 1)[-1])
                urows.append({'分区': z, '来源区域': area, '电影': u['name'], '主视频文件': u['main'],
                              '单元总GB': u['gb'], '路径': u['path']})
    _write(workdir, 'cross_units.csv', CROSS_UNIT_COLS, urows, 'utf-8-sig')
    stats['cross_units'] = {'remux': sum(1 for u in urows if u['分区'] == 'remux'),
                            'pack': sum(1 for u in urows if u['分区'] == 'pack')}

    # Emby → emby_yp.csv / emby_titles.csv
    progress('读取 Emby 片库')
    emby_info = write_emby_csvs(cfg, workdir, errors, [u['path'] for u in units] + [f['path'] for f in yfiles])

    for z, _ in C.ZONES:
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
    stats['pack'] = {'count': 0, 'gb': 0}
    # 可选：union_units.csv（REMUX 区 + 整夹合集单元）→ 跨区比对；没有就跳过那个模块
    up = os.path.join(src, 'union_units.csv')
    if os.path.isfile(up):
        progress('载入 union_units.csv')
        urows, seen = [], set()
        with open(up, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if r['路径'] in seen:
                    continue
                seen.add(r['路径'])
                urows.append({'分区': 'remux' if r['来源区域'] == 'REMUX' else 'pack', '来源区域': r['来源区域'],
                              '电影': r['电影'], '主视频文件': r['主视频文件'], '单元总GB': r['单元总GB'], '路径': r['路径']})
        _write(workdir, 'cross_units.csv', CROSS_UNIT_COLS, urows, 'utf-8-sig')
        for z in ('remux', 'pack'):
            us = [u for u in urows if u['分区'] == z]
            stats[z] = {'count': len(us), 'gb': round(sum(float(u['单元总GB']) for u in us) * 1e9 / GB, 1)}
        stats['cross_units'] = {z: stats[z]['count'] for z in ('remux', 'pack')}
    return stats, files, errors


CROSS_UNIT_COLS = ['分区', '来源区域', '电影', '主视频文件', '单元总GB', '路径']


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
    from . import cd2cache
    try:
        out['cache'] = cd2cache.probe(cfg)
    except FileNotFoundError as e:
        out['cache'] = {'ok': False, 'missing': True, 'error': str(e)}
    except Exception as e:
        out['cache'] = {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
    return out


TMDB_RE = re.compile(r'tmdb=(\d+)', re.I)
VIDEO_STREAM_TYPE = 2      # Emby 流表 StreamType：视频流
EMBY_MOVIE_TYPE = 5        # Emby 4.x MediaItems.Type 为整数时：5 = 电影（真库实测与金标准电影数一致）


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

    def tnorm(t):
        return int(t) if isinstance(t, str) and t.strip().isdigit() else t

    types = Counter(tnorm(g(it, 'type')) for it in rows) if 'type' in cols else Counter()
    type_is_str = any(isinstance(t, str) for t in types)
    if type_is_str:
        rule = '类型名以 Movie 结尾'
    elif EMBY_MOVIE_TYPE in types:
        rule = '类型 %d = 电影（Emby 4.x 约定）' % EMBY_MOVIE_TYPE
    else:
        rule = '推断：非剧集、非文件夹（库里没有类型 %d，请核对电影数）' % EMBY_MOVIE_TYPE
    out = []
    for it in rows:
        t = tnorm(g(it, 'type'))
        if type_is_str:
            movie = str(t).endswith('Movie')
        elif EMBY_MOVIE_TYPE in types:
            movie = t == EMBY_MOVIE_TYPE
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
                 'type_is_str': type_is_str, 'movie_rule': rule,
                 'type_dist': [[str(k), v] for k, v in types.most_common(8)]}


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
                movies_tmdb_res=sum(1 for i in movies if i['tmdb'] and i['width']),
                under_prefix=sum(1 for i in items if pre and i['path'].startswith(pre + '/')),
                path_prefixes=path_prefixes(items),
                sample_paths=[i['path'] for i in movies[:5]])


def path_prefixes(items, depth=3, top=4):
    """Emby 条目路径的前几层分布，让用户一眼看出是直挂库还是 strm 镜像树。"""
    c = Counter('/' + '/'.join(i['path'].strip('/').split('/')[:depth]) for i in items if i['path'])
    return [[k, v] for k, v in c.most_common(top)]


def tmdb_of_path(vp):
    """从路径里取 TMDB 编号：先看文件名，再由近到远看各级目录名（{tmdb-9364} / {tmdbid-9364} 都认）。"""
    for comp in reversed(vp.strip('/').split('/')):
        m = TMDB_TAG.search(comp)
        if m:
            return m.group(1)
    return ''


def write_emby_csvs(cfg, workdir, errors, yuanpan_paths=()):
    """emby_titles.csv：电影条目。emby_yp.csv：原盘区实测分辨率，两种配对方式——
    ① 路径直配：Emby 路径去掉前缀 = 库存路径（直挂库成立）；
    ② TMDB 兜底：路径配不上时（如 strm 镜像库），从原盘路径里取 TMDB 编号，取 Emby 同编号电影的分辨率
       （同编号多个版本取最高，与 titles 的 max_vh 同口径）。行仍按原盘路径写，内核按原样查表即可。"""
    pre = cfg['emby_prefix'].rstrip('/')
    try:
        items, meta = emby_items(cfg)
    except Exception as e:
        errors.append('Emby：' + str(e) + '（纵向轴与原盘实测分辨率将缺失）')
        items, meta = [], {}
    yp, titles, seen = [], [], set()
    by_tmdb = {}
    for i in items:
        if pre and i['path'].startswith(pre + '/') and i['width']:
            # 内核写死 replace('/CloudNAS/CloudDrive','')，这里统一换成该前缀以对上挂载虚拟路径
            rel = i['path'][len(pre):]
            yp.append({'source_path': '/CloudNAS/CloudDrive' + rel, 'width': i['width'], 'height': i['height']})
            seen.add(rel)
        if i['movie'] and (i['tmdb'] or i['name']):
            titles.append({'tmdb': i['tmdb'], 'name': i['name'], 'year': i['year'],
                           'max_vh': nominal_vh(i['width'], i['height'])})
        if i['movie'] and i['tmdb'] and i['width']:
            cur = by_tmdb.get(i['tmdb'])
            if cur is None or min(i['width'], i['height']) > min(cur):
                by_tmdb[i['tmdb']] = (i['width'], i['height'])
    path_hits = len(yp)
    tmdb_tagged = 0
    for vp in yuanpan_paths:
        if vp in seen:
            continue
        tm = tmdb_of_path(vp)
        tmdb_tagged += bool(tm)
        if tm and tm in by_tmdb:
            w, h = by_tmdb[tm]
            yp.append({'source_path': '/CloudNAS/CloudDrive' + vp, 'width': w, 'height': h})
            seen.add(vp)
    tmdb_hits = len(yp) - path_hits
    if items and not yp:
        errors.append('原盘实测分辨率修正未生效：Emby 路径不在前缀 %s 下，原盘路径里也没有能配上的 TMDB 编号；'
                      '原盘档位只按文件名/体积判断' % (pre or '（空）'))
    _write(workdir, 'emby_yp.csv', ['source_path', 'width', 'height'], yp, 'utf-8')
    _write(workdir, 'emby_titles.csv', ['tmdb', 'name', 'year', 'max_vh'], titles, 'utf-8-sig')
    return {'items': len(items), 'movies': len(titles), 'matched_paths': path_hits, 'matched_tmdb': tmdb_hits,
            'yuanpan_paths': len(yuanpan_paths), 'yuanpan_tmdb_tagged': tmdb_tagged,
            'movie_rule': meta.get('movie_rule'), 'table': meta.get('table')}
