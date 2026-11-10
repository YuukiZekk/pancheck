"""首启向导：用户只给两个目录（CD2 配置目录、Emby 数据目录），其余自动识别，用户只确认。

每一步都是「填一页、验一页、过一页」：返回验收数字；识别不了时返回人话说明差什么（error + hint），
不把原始报错丢给用户。全部只读。
"""
import os
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
            break
    out = {'sample': sample, 'current': cfg.get('emby_prefix') or ''}
    if hits:
        pre, h = hits.most_common(1)[0]
        n = min(votes[pre], checked)
        out.update(ok=True, prefix=pre, hits=h, checked=n,
                   say='你的 Emby 路径长这样：%s。去掉开头的 %s 就是网盘里的路径（抽查 %d 部，%d 部对得上），对吗？'
                       % (sample[0] if sample else '', pre or '（无）', n, h))
    else:
        out.update(ok=False, prefix='',
                   say='Emby 里的路径（如 %s）对不上网盘目录，像是 strm 镜像库。不影响使用：原盘的实测分辨率改按 TMDB 编号配对，这一项不用设。'
                       % (sample[0] if sample else '—'))
    return out


def check_zones(cfg=None):
    """第 3 步：按目录名建议分区 + 保护/榜单包模板预勾 + 缓存覆盖。"""
    cfg = cfg or C.load()
    try:
        sg = S.suggest(cfg)
    except Exception:
        return {'ok': False, 'error': '读不出网盘目录树。', 'hint': '回到第 1 步重新识别 CD2。'}
    roots = [p for z in sg['zones'].values() for p in z]
    cov = {}
    if cfg.get('data_source') == 'cache' and roots:
        from . import cd2cache
        try:
            cov = cd2cache.coverage(cfg, roots)
        except Exception:
            cov = {}
    return dict(sg, ok=True, coverage=cov)
