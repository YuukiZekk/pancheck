"""首启向导：用户只给两个目录（CD2 配置目录、Emby 数据目录），其余自动识别，用户只确认。

每一步都是「填一页、验一页、过一页」：返回验收数字；识别不了时返回人话说明差什么（error + hint），
不把原始报错丢给用户。全部只读。
"""
import os
import re
import sqlite3
from collections import Counter

from . import config as C
from . import sources as S

DOCKER_HINT = {
    'cd2': 'Docker 部署时，这个目录是 docker-compose.yml 里「CD2 配置目录」那一行挂载进来的：'
           '把冒号左边改成 NAS 上 CD2 的实际数据目录，再执行 docker compose up -d。',
    'emby': 'Docker 部署时，这个目录是 docker-compose.yml 里「Emby 数据目录」那一行挂载进来的：'
            '把冒号左边改成 NAS 上 Emby 的数据目录（Emby 后台「关于」页能看到原样路径），再执行 docker compose up -d。',
}


def _dir_problem(path, what):
    """目录本身有问题时的人话；没问题返回 None。"""
    if not path:
        return {'error': '还没填%s。' % what, 'hint': ''}
    if not os.path.isdir(path):
        return {'error': '找不到目录 %s。' % path, 'hint': ''}
    try:
        if not os.listdir(path):
            return {'error': '目录 %s 是空的，多半是挂载没生效（冒号左边的路径写错了，或那边就是空目录）。' % path, 'hint': ''}
    except OSError:
        return {'error': '目录 %s 读不了（权限不够）。' % path, 'hint': '给容器只读权限即可，面板不会写这个目录。'}
    return None


def check_cd2(path, cfg=None):
    cfg = dict(cfg or C.load(), cd2_config=path, cd2_api_user='')
    bad = _dir_problem(path, ' CD2 配置目录')
    if bad:
        bad['hint'] = bad['hint'] or DOCKER_HINT['cd2']
        return dict(bad, ok=False)
    db = S.find_sqlite(path, 'dir_cache.sqlite', {'cached_item', 'files'})
    if not db:
        return {'ok': False, 'error': '在 %s 里没找到 CD2 的目录缓存数据库（dir_cache.sqlite）。' % path,
                'hint': '确认填的是 CD2 的配置/数据目录（装 CD2 时指定的那个，里面通常有 config 之类的文件）；'
                        '另外 CD2 要至少打开过一次网盘目录才会生成缓存。'}
    try:
        conn, how = S.open_ro(db)
        try:
            folders, tmin, tmax = conn.execute(
                'select count(*), min(insert_time), max(insert_time) from cached_item').fetchone()
            accts = conn.execute('select api_name, count(*) from files where file_type = 4 group by 1 order by 2 desc').fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {'ok': False, 'error': '找到了 %s，但读不出来（文件可能损坏，或 CD2 版本太新、结构变了）。' % db,
                'hint': '先重启一次 CD2 再识别；还不行就把 CD2 版本号告诉维护者。'}
    if not accts:
        return {'ok': False, 'error': '缓存里还没有任何网盘文件记录。',
                'hint': '先在 CD2 里把网盘的影视目录点开几层（缓存是「打开过才有」），再回来识别。'}
    names = [{'api_name': a, 'files': nf} for a, nf in accts]
    chosen = cfg.get('cd2_api_name') if any(x['api_name'] == cfg.get('cd2_api_name') for x in names) else names[0]['api_name']
    cfg['cd2_api_name'] = chosen
    from . import cd2cache
    tops = sorted(cd2cache.api_tops(cfg))
    top_dirs = []
    for t in tops[:5]:
        try:
            top_dirs += [d['path'] for d in cd2cache.list_dirs(cfg, '/' + t)][:12]
        except OSError:
            top_dirs.append('/' + t)
    return {'ok': True, 'db': db, 'open_mode': how, 'folders': folders, 'time_min': tmin, 'time_max': tmax,
            'api_names': names, 'api_name': chosen, 'need_choice': len(names) > 1,
            'files': next(x['files'] for x in names if x['api_name'] == chosen),
            'tops': ['/' + t for t in tops], 'top_dirs': top_dirs}


def check_emby(path, cfg=None):
    cfg = dict(cfg or C.load(), emby_data=path)
    bad = _dir_problem(path, ' Emby 数据目录')
    if bad:
        bad['hint'] = bad['hint'] or DOCKER_HINT['emby']
        return dict(bad, ok=False)
    if not S.find_emby_db(path):
        return {'ok': False, 'error': '在 %s 里没找到 Emby 的片库数据库（library.db）。' % path,
                'hint': 'Emby 数据目录下面一般有个 data 文件夹，library.db 就在里面；填它的上一级或 data 本身都行。'}
    try:
        items, meta = S.emby_items(cfg)
    except Exception:
        return {'ok': False, 'error': '找到了 library.db，但读不出片库（Emby 版本结构不认识）。',
                'hint': '把 Emby 版本号告诉维护者；不连 Emby 也能先用，只是少了「对比 Emby」这一类。'}
    movies = [i for i in items if i['movie']]
    if not movies:
        return {'ok': False, 'error': 'Emby 库里一部电影都没有。',
                'hint': '确认 Emby 已建电影库并扫描完成。'}
    return {'ok': True, 'db': meta.get('db') or S.find_emby_db(path), 'open_mode': meta.get('open_mode'),
            'movies': len(movies), 'movies_tmdb': sum(1 for i in movies if i['tmdb']),
            'movie_rule': meta.get('movie_rule'), 'prefix': guess_emby_prefix(cfg, movies)}


def guess_emby_prefix(cfg, movies):
    """从 Emby 电影路径推断「Emby 里看到的 CD2 挂载根」：路径里出现网盘顶层目录（如 /115/）之前的部分。
    再拿去掉前缀后的目录去缓存里核对，对得上才算数；对不上（如 strm 镜像库）就说明这一项不用设。"""
    from . import cd2cache
    sample = [m['path'] for m in movies if m['path']][:3]
    try:
        tops = cd2cache.api_tops(cfg)
    except Exception:
        tops = set()
    votes, hits = Counter(), Counter()
    example = {}                                   # 每个前缀第一条对得上的路径，界面上当佐证
    checked = 0
    for m in movies:
        p = m['path'] or ''
        for t in tops:
            i = p.find('/' + t + '/')
            if i < 0:
                continue
            pre, rest = p[:i], p[i:]
            votes[pre] += 1
            if checked < 3000:
                checked += 1
                if cd2cache.dir_exists(cfg, rest.rsplit('/', 1)[0]):
                    hits[pre] += 1
                    example.setdefault(pre, p)
            break
    out = {'sample': sample, 'current': cfg.get('emby_prefix') or ''}
    if hits:
        pre, h = hits.most_common(1)[0]
        n = min(votes[pre], checked)
        out.update(ok=True, prefix=pre, hits=h, checked=n, example=example.get(pre, ''),
                   say='你的 Emby 路径长这样：%s。去掉开头的 %s 就是网盘里的路径（抽查 %d 部，%d 部对得上），对吗？'
                       % (sample[0] if sample else '', pre or '（无）', n, h))
    else:
        out.update(ok=False, prefix='',
                   say='Emby 里的路径（如 %s）对不上网盘目录，像是 strm 镜像库。不影响使用：原盘的实测分辨率改按 TMDB 编号配对，这一项不用设。'
                       % (sample[0] if sample else '—'))
    return out


# ---------------- 第 3 步：分区候选（分组勾选） ----------------
# 只列「装着电影的目录」，不列「本身就是一部电影的目录」；只有高置信的名字才预勾，含糊的放「未归类」等用户自己勾。
# 改的只是向导的呈现和预填；判定内核、配置结构（zones 仍是四组路径列表）不动。
_NUM = re.compile(r'^\s*\d+\s*[-_.、·\s]\s*')
JUNK = ('删除', '回收', 'recycle', 'trash', '@eadir')                 # 别的工具的工作区 / 回收站：本身和下面都不列
NOT_ZONE = ('未整理', '待整理', '下载', '临时', 'incoming', 'download', 'temp', 'tmp')   # 本身不当分区，下面的放「未归类」
QUALIFIERS = ('动漫', '动画', 'uhd', '测试', '样片', 'bdmv', '未整理', '待整理', '下载', '临时', '剧', '纪录', '演唱会')
_TOKEN_Q = re.compile(r'(^|[^a-z])(pt|mv)([^a-z]|$)')
STRONG = (('remux', ('remux',)), ('yuanpan', ('原盘',)), ('heji', ('电影合集', '电影包')))   # REMUX 优先
MIN_UNITS = 5                       # 子树里影片单元少于这个数的，当成「一部片 / 一季剧」的夹，不进候选


def _core(name):
    return _NUM.sub('', name or '').strip().lower()


def _has(core, words):
    return any(w in core for w in words)


def _qualified(core):
    return _has(core, QUALIFIERS) or bool(_TOKEN_Q.search(core))


def zone_guess(path):
    """→ (高置信分区或 None, 名字里的提示词或 '')。高置信：名字（去掉序号）含原盘 / REMUX / 电影合集，
    且自己和上层目录都不带「动漫 / UHD / 测试 / PT / 未整理…」这类限定词。"""
    parts = [x for x in path.strip('/').split('/') if x]
    core = _core(parts[-1]) if parts else ''
    up = [_core(x) for x in parts[1:-1]]          # 第一段是网盘名（如 115），不算
    strong = None
    if not _qualified(core) and not any(_qualified(u) or _has(u, NOT_ZONE) for u in up):
        for z, words in STRONG:
            if _has(core, words):
                strong = z
                break
    hint = ''
    for z in ('remux', 'yuanpan', 'heji'):
        w = next((h for h in S.ZONE_HINTS[z] if h in core), '')
        if w:
            hint = w
            break
    return strong, hint


def _tree(cfg, max_depth=4, max_dirs=3000):
    """→ ({路径: 下层文件夹名列表}, 是否截断)。缓存模式整棵树现成（零请求）；挂载模式只列到 max_depth 层。"""
    if cfg.get('data_source') == 'cache':
        from . import cd2cache
        ch = cd2cache._children_map(cfg)
        return {k: sorted(v) for k, v in ch.items()}, False
    lister, kids, queue, seen = S.dir_lister(cfg), {}, [('/', 0)], 0
    while queue and seen < max_dirs:
        path, depth = queue.pop(0)
        try:
            ds = lister(cfg, path)
        except OSError:
            continue
        kids[path] = [d['name'] for d in ds]
        for d in ds:
            seen += 1
            if depth + 1 < max_depth:
                queue.append((d['path'], depth + 1))
    return kids, seen >= max_dirs


def zone_candidates(cfg, max_depth=3):
    kids, truncated = _tree(cfg)
    cache = cfg.get('data_source') == 'cache'
    units, tops = None, None
    if cache:
        from . import cd2cache
        units = cd2cache.unit_dirs(cfg)
        tops = cd2cache.api_tops(cfg)
    current = {p: z for z, ps in cfg['zones'].items() for p in ps}
    # 面板自己的去处（排查区 / 主库 / 唯一副本目录）绝不能当分区：本身和下面都不列
    own = ['/' + d.strip('/') for d in (cfg.get('quarantine_dir'), cfg.get('main_lib_dir'), cfg.get('unique_dir')) if d and d.strip('/')]
    out, queue = [], [('/', 0)]
    while queue:
        path, depth = queue.pop(0)
        for name in kids.get(path, ()):
            vp = ('' if path == '/' else path) + '/' + name
            core = _core(name)
            if _has(core, JUNK) or any(vp == d or vp.startswith(d + '/') for d in own):
                continue                                      # 连同下面整棵都不列
            if depth + 1 < max_depth:
                queue.append((vp, depth + 1))
            if depth == 0 and (tops is None or name in tops):
                continue                                      # 网盘根（/115）本身不当分区
            if tops is not None and vp.strip('/').split('/', 1)[0] not in tops:
                continue                                      # 缓存里别的网盘
            if _has(core, NOT_ZONE) and vp not in current:
                continue
            sub = len(kids.get(vp, ()))
            n_units = cd2cache.count_units(units, vp) if units is not None else None
            if vp not in current and (sub == 0 if vp in kids or cache else False):
                continue                                      # 没有下层文件夹：一部片 / 一季剧
            if vp not in current and n_units is not None and n_units < MIN_UNITS:
                continue
            strong, hint = zone_guess(vp)
            out.append({'path': vp, 'subdirs': sub, 'units': n_units, 'strong': strong, 'hint': hint,
                        'current': current.get(vp)})
    # 已绑定、但不在前三层里的分区也要列出来（向导「完成」时按勾选结果整组覆盖，不能把它们丢了）
    listed = {c['path'] for c in out}
    for vp, z in current.items():
        if vp not in listed:
            strong, hint = zone_guess(vp)
            out.append({'path': vp, 'subdirs': len(kids.get(vp, ())), 'strong': strong, 'hint': hint, 'current': z,
                        'units': cd2cache.count_units(units, vp) if units is not None else None})
    # 高置信的父目录已预勾时，子目录不再预勾（同一片区不重复绑）
    picked = []
    for c in sorted(out, key=lambda c: c['path']):
        if c['strong'] and not c['current'] and any(c['path'].startswith(p + '/') for p in picked):
            c['strong'] = None
        elif c['strong'] or c['current']:
            picked.append(c['path'])
    out.sort(key=lambda c: (-(c['units'] or 0), c['path']))
    return out, truncated


def check_zones(cfg=None):
    """第 3 步：分区候选（分组勾选）+ 保护/榜单包模板预勾 + 缓存覆盖。"""
    cfg = cfg or C.load()
    try:
        cands, truncated = zone_candidates(cfg)
        sg = S.suggest(cfg)                                   # 保护 / 榜单包模板沿用原来的按名识别
    except Exception:
        return {'ok': False, 'error': '读不出网盘目录树。', 'hint': '回到第 1 步重新识别 CD2。'}
    cov = {}
    if cfg.get('data_source') == 'cache' and cands:
        from . import cd2cache
        try:
            cov = cd2cache.coverage(cfg, [c['path'] for c in cands])
        except Exception:
            cov = {}
    return {'ok': True, 'candidates': cands, 'truncated': truncated, 'coverage': cov,
            'protect_templates': sg['protect_templates'], 'protect_found': sg['protect_found'],
            'listpack_found': sg['listpack_found'], 'exclude_found': sg['exclude_found']}
