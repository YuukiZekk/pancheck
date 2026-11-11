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
JUNK = ('删除', '回收', '排查', 'recycle', 'trash', '@eadir')         # 别的工具的工作区 / 回收站 / 排查区：本身和下面都不列
NOT_ZONE = ('未整理', '待整理', '归档失败', '下载', '临时', 'incoming', 'download', 'temp', 'tmp')   # 本身不当分区，下面的放「未归类」
QUALIFIERS = ('动漫', '动画', 'uhd', '测试', '样片', 'bdmv', '未整理', '待整理', '下载', '临时', '剧', '纪录', '演唱会')
_TOKEN_Q = re.compile(r'(^|[^a-z])(pt|mv)([^a-z]|$)')
STRONG = (('remux', ('remux',)), ('yuanpan', ('原盘',)), ('heji', ('电影合集', '电影包')))   # REMUX 优先
MIN_UNITS = 5                       # 子树里作品少于这个数的（季 / 集夹并成一部），当成「一部片 / 一部剧」的夹，不进候选


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


# 反馈 20：不合格的目录不再凭空消失，置灰并写原因（顶层全列；规则隐藏的在任何层都留一行灰字）
OFF_WHY = {
    'hidden': '按规则隐藏：像是别的工具的工作区 / 回收站 / 排查区，本身和下面都不扫',
    'quarantine': '面板的排查区：本身和下面都不扫',
    'mainlib': '面板的主库目录（主库缺口挪去这里），不当分区',
    'unique': '面板的唯一副本目录，不当分区',
    'unknown': 'CD2 还没打开过，内容未知——去 CD2 里把它点开一次，回来点「刷新」就能看到',
    'staging': '待整理 / 下载类目录，本身不当分区；下层够格的照常列出',
    'few': '部片太少（不到 %d 部），像是一部片 / 一部剧的夹，不当分区' % MIN_UNITS,
    'empty': '下面没有文件夹，像是一部片的夹，不当分区',
}


def _own_dirs(cfg):
    return [('/' + cfg[k].strip('/'), z) for k, z in (('quarantine_dir', 'quarantine'), ('main_lib_dir', 'mainlib'),
                                                       ('unique_dir', 'unique')) if (cfg.get(k) or '').strip('/')]


def _full_tree(cfg):
    """→ (kids, unopened, truncated)。缓存模式把「列过的父目录里出现、但自己没打开过」的目录也补进树里。"""
    kids, truncated = _tree(cfg)
    unopened = set()
    if cfg.get('data_source') == 'cache':
        from . import cd2cache
        unopened = cd2cache.unopened_dirs(cfg)
        if unopened:
            kids = {k: set(v) for k, v in kids.items()}
            for vp in unopened:
                par, _, nm = vp.rpartition('/')
                kids.setdefault(par or '/', set()).add(nm)
            kids = {k: sorted(v) for k, v in kids.items()}
    return kids, unopened, truncated


def zone_candidates(cfg, max_depth=3, tree=None):
    kids, unopened, truncated = tree or _full_tree(cfg)
    cache = cfg.get('data_source') == 'cache'
    units, tops = None, None
    if cache:
        from . import cd2cache
        units = cd2cache.work_dirs(cd2cache.unit_dirs(cfg))
        tops = cd2cache.api_tops(cfg)
    current = {p: z for z, ps in cfg['zones'].items() for p in ps}
    # 面板自己的去处（排查区 / 主库 / 唯一副本目录）绝不能当分区：本身留一行灰字，下面不列
    own = _own_dirs(cfg)
    out, queue = [], [('/', 0)]
    while queue:
        path, depth = queue.pop(0)
        for name in kids.get(path, ()):
            vp = ('' if path == '/' else path) + '/' + name
            core = _core(name)
            if depth == 0 and (tops is None or name in tops):
                queue.append((vp, depth + 1))
                continue                                      # 网盘根（/115）本身不当分区
            if tops is not None and vp.strip('/').split('/', 1)[0] not in tops:
                continue                                      # 缓存里别的网盘
            sub = len(kids.get(vp, ()))
            n_units = cd2cache.count_units(units, vp) if units is not None else None
            base = {'path': vp, 'subdirs': sub, 'units': n_units, 'strong': None, 'hint': '', 'current': current.get(vp)}
            ok = next((z for d, z in own if vp == d), None)
            if ok or (_has(core, JUNK) and vp not in current):
                out.append(dict(base, off=ok or 'hidden'))   # 连同下面整棵都不列
                continue
            if any(vp.startswith(d + '/') for d, _ in own):
                continue
            if depth + 1 < max_depth:
                queue.append((vp, depth + 1))
            off = None
            if vp in current:
                pass
            elif vp in unopened:
                off = 'unknown'
            elif _has(core, NOT_ZONE):
                off = 'staging'
            elif sub == 0 and (vp in kids or cache):
                off = 'empty'                                 # 没有下层文件夹：一部片 / 一季剧
            elif n_units is not None and n_units < MIN_UNITS:
                off = 'few'
            if off:
                if depth == 1:                                # 顶层全列；更深的不合格目录不单列（太多），靠上层的说明交代
                    out.append(dict(base, off=off))
                continue
            strong, hint = zone_guess(vp)
            if strong and _has(name, S.PROTECT_TEMPLATES + list(cfg['protect_names'])):
                strong = None                                 # 「01-系列电影合集」这类是保护目录，不预勾成分区
            out.append(dict(base, strong=strong, hint=hint))
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
        if c.get('off'):
            continue
        if c['strong'] and not c['current'] and any(c['path'].startswith(p + '/') for p in picked):
            c['strong'] = None
        elif c['strong'] or c['current']:
            picked.append(c['path'])
    for c in out:
        if c.get('off'):
            c['why'] = OFF_WHY[c['off']]
    out.sort(key=lambda c: (bool(c.get('off')), -(c['units'] or 0), c['path']))
    return out, truncated


def _walk(kids, cfg, max_seg=5):
    """目录树按层遍历（网盘根算第 1 段，最多 max_seg 段），跳过规则隐藏和面板自己的去处。→ [(路径, 名字)]"""
    own = [d for d, _ in _own_dirs(cfg)]
    out, queue = [], ['/']
    while queue:
        path = queue.pop(0)
        for name in kids.get(path, ()):
            vp = ('' if path == '/' else path) + '/' + name
            if _has(_core(name), JUNK) or any(vp == d or vp.startswith(d + '/') for d in own):
                continue
            out.append((vp, name))
            if vp.count('/') < max_seg:
                queue.append(vp)
    return out


def protect_scan(cfg, kids, max_seg=5):
    """反馈 19：保护目录（系列电影合集、出品公司…）多在分区根的下一层，按名字往下多看两层；
    只看「装着好几部片」的目录，免得片名里的「收藏版」被当保护目录。→ {模板词: [示例路径]}"""
    units = None
    if cfg.get('data_source') == 'cache':
        from . import cd2cache
        units = cd2cache.work_dirs(cd2cache.unit_dirs(cfg))
    found = {}
    for vp, name in _walk(kids, cfg, max_seg):
        t = next((t for t in S.PROTECT_TEMPLATES if t in name), None)
        if not t or t in cfg['protect_names'] or any(vp.startswith(p + '/') for ps in found.values() for p in ps):
            continue
        if any(S.hit_any(comp, cfg['protect_names']) for comp in vp.strip('/').split('/')[:-1]):
            continue                                          # 上层已经是保护目录了，不再单提
        if units is not None and cd2cache.count_units(units, vp) < 2:
            continue
        if units is None and not kids.get(vp):
            continue
        found.setdefault(t, [])
        if len(found[t]) < 3:
            found[t].append(vp)
    return found


def listpack_scan(cfg, kids, max_seg=5):
    """反馈 19：自动认出的榜单包（内置组合词规则 + 用户追加的名字），每条带来源，界面上可逐条移除。
    上层已算榜单包的，下层不再单列。用户移除过的（listpack_off）也列出来，能加回去。"""
    import sieve
    out = []
    for vp, name in _walk(kids, cfg, max_seg):
        if any(vp.startswith(o['path'] + '/') for o in out):
            continue
        w, by = sieve.listpack_word(name), 'rule'
        if not w:
            w, by = S.hit_any(name, cfg['listpack_names']), 'name'
        if w:
            out.append({'path': vp, 'word': w, 'by': by, 'off': bool(S.lp_off(vp, cfg))})
    listed = {o['path'] for o in out}
    out += [{'path': p, 'word': '', 'by': 'rule', 'off': True} for p in cfg.get('listpack_off') or () if p not in listed]
    return out[:40]


# ---------------- 反馈 23：顶部三个位置 + 下面一棵只管勾选的目录树 ----------------
# 勾上的目录 = zones 里的根（分区类型由这里按名字自动定，界面上不出现）；根下面没勾的 = skip_dirs。
# 置灰只是提示（内容未知 / 部片太少 / 规则隐藏），不挡勾选；只有查重区本身不能勾（它不进扫描）。
TREE_WHY = {
    'hidden': '按规则隐藏的目录（别的工具的工作区 / 回收站 / 排查类），默认不勾',
    'unknown': 'CD2 还没打开过，内容未知——去 CD2 里点开一次，回来点「刷新」',
    'todo': '待整理 / 下载类目录，默认不勾',
    'few': '部片太少，像是一部片 / 一部剧的夹',
    'empty': '下面没有文件夹，像是一部片的夹',
}
PLACE_NAME = {'mainlib': '主媒体库', 'quarantine': '查重区', 'staging': '待入库区'}
MAX_CHILDREN = 500


class _Ctx:
    """一次请求里共用的目录树信息（缓存模式全是现成的，零网盘请求）。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.kids, self.unopened, self.truncated = _full_tree(cfg)
        self.cache = cfg.get('data_source') == 'cache'
        self.units, self.tops = None, None
        if self.cache:
            from . import cd2cache
            self.units = cd2cache.work_dirs(cd2cache.unit_dirs(cfg))
            self.tops = cd2cache.api_tops(cfg)
        self.current = {p: z for z, ps in cfg['zones'].items() for p in ps}

    def n_units(self, vp):
        if self.units is None:
            return None
        from . import cd2cache
        return cd2cache.count_units(self.units, vp)

    def children_names(self, vp):
        names = self.kids.get(vp or '/', ())
        if (vp or '/') == '/' and self.tops is not None:
            names = [n for n in names if n in self.tops]
        return names


def auto_zone(vp, current=None):
    """勾上的目录按名字自动归类（界面上不出现）：已绑过的照旧；名字里有 REMUX → REMUX 区；
    原盘 / 蓝光 / BDMV / ISO → 原盘区（自己没有就看上层）；其余 → 合集区。"""
    if current and vp in current:
        return current[vp]
    strong, _ = zone_guess(vp)
    if strong:
        return strong
    parts = [_core(x) for x in vp.strip('/').split('/')[1:]]
    for core in reversed(parts):
        if 'remux' in core:
            return 'remux'
        if _has(core, S.ZONE_HINTS['yuanpan']) and not _has(core, ('合集', '电影包')):
            return 'yuanpan'
        if _has(core, ('合集', '电影包')):
            return 'heji'
    return 'heji'


def _entry(ctx, vp, depth):
    name = vp.rsplit('/', 1)[-1]
    core = _core(name)
    sub = len(ctx.kids.get(vp, ()))
    units = ctx.n_units(vp)
    off = None
    if _has(core, JUNK):
        off = 'hidden'
    elif vp in ctx.unopened:
        off = 'unknown'
    elif _has(core, NOT_ZONE):
        off = 'todo'
    elif sub == 0 and (vp in ctx.kids or ctx.cache):
        off = 'empty'
    elif units is not None and units < MIN_UNITS:
        off = 'few'
    e = {'path': vp, 'name': name, 'kids': sub, 'units': units, 'auto': auto_zone(vp, ctx.current)}
    if off:
        e['off'], e['why'] = off, TREE_WHY[off]
    return e


def children(cfg, vp, ctx=None):
    """一个目录下面的子目录（展开时按需取）。网盘根（/）只列目标网盘的顶层（如 /115）。"""
    ctx = ctx or _Ctx(cfg)
    vp = '/' + vp.strip('/') if vp.strip('/') else '/'
    names = ctx.children_names(vp)
    pre = '' if vp == '/' else vp
    out = [_entry(ctx, pre + '/' + n, pre.count('/') + 1) for n in names[:MAX_CHILDREN]]
    return {'path': vp, 'dirs': out, 'more': max(0, len(names) - MAX_CHILDREN)}


def _container(ctx, vp):
    """装着好几部片的目录（保护 / 榜单包类目录的预选只看这类，片名里的「收藏版」不算）。"""
    u = ctx.n_units(vp)
    return (u >= 2) if u is not None else bool(ctx.kids.get(vp))


def _preskip(ctx, roots):
    """预选里「父级已勾、它们未勾」的目录：系列电影合集 / 出品公司 / 已刮削大包 / 榜单包 / 已有的保护名。
    只取最上面那层；按整棵缓存树找（任意层），不限前三层。→ [(路径, 原因)]"""
    import sieve
    cfg = ctx.cfg
    names = list(cfg['protect_names']) + list(cfg['keep_first_names']) + list(S.PROTECT_TEMPLATES)
    lp_names = list(cfg['listpack_names'])
    out = []
    queue = list(roots)
    while queue:
        path = queue.pop(0)
        for n in ctx.kids.get(path, ()):
            vp = path + '/' + n
            if not _container(ctx, vp):
                continue
            why = None
            if S.hit_any(n, names):
                why = '保护类目录（名字含「%s」）' % S.hit_any(n, names)
            elif (sieve.listpack_word(n) or S.hit_any(n, lp_names)) and not S.lp_off(vp, cfg):
                why = '榜单包（%s）' % (sieve.listpack_word(n) or S.hit_any(n, lp_names))
            if why:
                out.append((vp, why))
            else:
                queue.append(vp)
    return out


def _place_guess(ctx):
    """顶部三个位置按名字猜：查重区 ← 含「排查 / 查重」；待入库区 ← 含「待入库 / 待整理 / 新入库」；
    主媒体库 ← 含「媒体库 / 主库」，没有就用唯一绑定的原盘区根。只看前三层，取最浅的。"""
    cands = []
    queue = [('/', 0)]
    while queue:
        path, d = queue.pop(0)
        for n in ctx.children_names(path):
            vp = ('' if path == '/' else path) + '/' + n
            if d >= 1:
                cands.append((d, vp, _core(n)))
            if d < 3:
                queue.append((vp, d + 1))
    cands.sort()

    def first(words):
        for w in words:
            for _, vp, core in cands:
                if w in core:
                    return vp
        return ''
    yp = ctx.cfg['zones']['yuanpan']
    return {'quarantine': first(('查重', '排查')), 'staging': first(('待入库', '待整理', '新入库')),
            'mainlib': first(('媒体库', '主库')) or (yp[0] if len(yp) == 1 else '')}


def check_zones(cfg=None):
    """第 3 步「确认筛查范围」：顶部三个位置 + 目录树预选（勾上的根 + 根下面没勾的）。只读，前端点「完成」时再存。"""
    cfg = cfg or C.load()
    try:
        ctx = _Ctx(cfg)
        cands, _ = zone_candidates(cfg, tree=(ctx.kids, ctx.unopened, ctx.truncated))
    except Exception:
        return {'ok': False, 'error': '读不出网盘目录树。', 'hint': '回到第 1 步重新识别 CD2。'}
    places = {'mainlib': cfg.get('main_lib_dir') or '', 'quarantine': cfg.get('quarantine_dir') or '',
              'staging': cfg.get('staging_dir') or ''}
    guess = _place_guess(ctx)
    guessed = [k for k in places if not places[k] and guess[k]]
    for k in guessed:
        places[k] = guess[k]
    if cfg.get('tree_model'):
        include = sorted(ctx.current)
        skip = [{'path': p, 'why': ''} for p in cfg.get('skip_dirs') or ()]
    else:
        # 老配置第一次进新向导：已绑的分区原样当「勾上」；没绑过的按原来的候选规则预勾名字明确的电影区
        include = sorted(ctx.current) or sorted(c['path'] for c in cands if c.get('strong') and not c.get('off'))
        q = places['quarantine']
        include = [p for p in include if not (q and (p == q or p.startswith(q + '/')))]
        skip = [{'path': p, 'why': w} for p, w in _preskip(ctx, include)]
    # 展开到能看见每个勾 / 不勾的位置：它们的各层上级的子目录都带上
    want = {'/'} | {t for t in ctx.children_names('/')}
    for p in include + [s['path'] for s in skip] + [v for v in places.values() if v]:
        parts = p.strip('/').split('/')
        for i in range(0, len(parts)):
            want.add('/' + '/'.join(parts[:i]) if i else '/')
    want = {('/' + w.strip('/')) if w.strip('/') else '/' for w in want}
    nodes = {w: children(cfg, w, ctx) for w in sorted(want) if w == '/' or w in ctx.kids}
    legacy = {'protect_names': cfg['protect_names'], 'listpack_names': cfg['listpack_names']} if not cfg.get('tree_model') else {}
    return {'ok': True, 'tree_model': cfg.get('tree_model'), 'places': places, 'guessed': guessed,
            'staging_on': cfg.get('staging_on', True), 'include': include, 'skip': skip,
            'auto': {p: auto_zone(p, ctx.current) for p in include}, 'nodes': nodes, 'legacy': legacy,
            'truncated': ctx.truncated}
