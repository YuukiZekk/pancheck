"""重复副本：一次扫描，同一部片的所有副本归成一组（反馈 15，取代原来分趟的合集×原盘 / 合集内 / 小文件 / 合集×REMUX / REMUX×原盘）。

人口（一份 = 一个能整体搬走的东西）：
  - 合集区：每个影片文件（heji_films.csv）
  - 原盘区：按片展开——盘片夹整个一份；一夹一部的整夹一份；一夹多部的逐文件一份（同原 A3 展开）
  - REMUX 区 / 整夹合集区：每个单元（直接放着视频的夹或盘片夹，cross_units.csv）
认片：一个函数（ident）——TMDB 编号，或「片名 + 年份」（片名用反馈 13 修好的取法：先挖规格词再取片名；
      纯拉丁名去掉年份和规格词后比）。两种键用并查集连起来：带 TMDB 的和不带的同名同年副本归同一组。
判档：分辨率档（原盘区：Emby 实测 > 主文件名 > ISO/盘片夹体积推断；其他：文件名，ISO ≥55GB / 文件 ≥40GB 推断 4K）
      + 来源类（原盘 > DIY > REMUX > 压制）。
保留份（用户 2026-11-11 拍板；反馈 16 加特效字幕版）：先比分辨率，同分辨率再比来源类（特效字幕版 > 原盘 > DIY > REMUX > 压制），再比命名（带 {tmdb}、在已刮削目录、规格写得全的优先，
      裸名靠后），最后比体积。
组内其余每份：
  - 版本对：保留份不是 DIY 时，最好的那份 DIY 两边都留；保留份是 DIY 时，最好的那份原盘两边都留 → 不同版本
  - 剪辑版本不同（导演剪辑 / 加长 / 未分级 …）的分开成小组各自比
  - 任一边分辨率看不出 → 需人工确认；例外：REMUX 没标分辨率、保留份是已确认（非推断）4K 原盘 → 可清理（沿用 2026-11-11 D1 改判）
  - 其余（分辨率更低或同档）→ 可清理
不碰：榜单包、内置排除词（金庸/动漫/ADWEB）与用户追加的排除 / 榜单词命中的副本——可以当保留份，自己永远不进可清理。
挂起：合集区里 ≥3 份在同一个夹、或 ≥2 份带集号 → 像剧集，整组不判（只计数）。原盘区一个夹里平铺很多 ISO 是常态，不算。
"""
import os
import re
from collections import Counter, defaultdict

import sieve as S
from . import sources
from .tables import tables_of

GIB = 1024 ** 3
STAGE = '重复副本'
RES_R = {'U': 3, 'H': 2, '?': 1, 'S': 0}
KIND_R = {'T': 5, 'I': 4, 'D': 3, 'R': 2, 'O': 1}    # 特效字幕版 > 原盘 > DIY > REMUX > 压制（反馈 16）
KIND_NAME = {'T': '特效字幕版', 'I': '原盘', 'D': 'DIY', 'R': 'REMUX', 'O': '压制'}
DIY_FAMILY = ('D', 'T')                              # 在原盘上加了字幕的：和原版成「版本对」
RES_NAME = {'U': '4K', 'H': '1080p', 'S': '720p 及以下', '?': '画质未知'}
ZONE_NAME = {'heji': '合集区', 'yuanpan': '原盘区', 'remux': 'REMUX 区', 'pack': '整夹合集区'}
BUCKET = {'A': '可切', 'B': '可切', 'N': '可切', 'V': '版本型', 'U': '待定'}
SMALL_GB, LOW_GB = 8, 15                             # 小文件层（同原第三刀人口口径）
_TAG = re.compile(r'(?i)[\[【][^\]】]*(豆瓣|评分|imdb|tt\d{6,})[^\]】]*[\]】]')     # [豆瓣电影评分8.8] [tt0440963]
_MULTI = re.compile(r'[一-鿿]{2,}\s*[+＋]\s*[一-鿿]{2,}|三部曲|四部曲|全\s*\d+\s*部|\d+\s*部合集|合集|系列\s*\d+\s*部')
_LAT_JUNK = re.compile(r'(?i)\b(4k|diy|uhd|hdr\d*|dv|bd|iso|remux|bluray|blu ray|web|dl|cc|criterion|collection|'
                       r'extended|remastered|repack|proper|complete|edition|cut|version|v\d)\b')


# ---------------- 认片 ----------------
def ident(name):
    """→ (tmdb 编号或 '', 片名, 年份)。片名为空 / 只是规格短语时返回空片名（不拿来连组）。"""
    m = S.TMDB2.search(name or '')
    tm = m.group(1) if m else ''
    s = re.sub(r'@\S+$', '', name or '')
    s = re.sub(r'\.(iso|mkv|mp4|m2ts|ts|avi|wmv|mov|rmvb|flv)$', '', s, flags=re.I)
    s = re.sub(r'\{[^}]*\}', ' ', s)
    s = _TAG.sub(' ', s)
    ys = S.YEAR2.findall(s)
    year = ys[-1] if ys else ''
    t = S._title2(s)
    if S.CJK.search(t):
        t = re.sub(r'[\s·・：:、，,.\-_!！?？\'"]+', '', t)
    else:
        if year:
            t = re.sub(r'(?<!\d)%s(?!\d)' % year, ' ', t)       # 只去掉年份本身（2012 (2009) 的片名 2012 要留着）
        t = _LAT_JUNK.sub(' ', t)
        t = re.sub(r'[^a-z0-9]+', '', t.lower())
        # 纯数字片名（2012、1917、21）要另有年份才算；「E21」「EP03」这类集号、单个字母不是片名
        if t.isdigit():
            if not year or t == year:
                t = ''
        elif re.fullmatch(r'(s\d{1,2})?(e|ep)\d{1,3}', t) or len(re.sub(r'\d', '', t)) <= 1:
            t = ''
    if t in S.PURE or S.title_suspect(t, year):
        t = ''
    # 剧集的不同季 / 全 N 季合集不是同一部片（反馈 19 放开裸「豆瓣」后露出来的：嗜血法医 第2季 被当成 第1季 的重复）
    se = season_of(name)
    if se:
        t = t and t + '~' + se
        tm = tm and tm + '~' + se
    return tm, t, year


_CN_NUM = {'一': '1', '二': '2', '三': '3', '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'}
_SEASON = re.compile(r'(?i)(全)\s*([\d一二三四五六七八九十]+)\s*季|第\s*([\d一二三四五六七八九十]+)\s*季'
                     r'|(?<![a-z0-9])season[\s._]*(\d{1,2})(?![0-9])|(?<![a-z0-9])s(\d{1,2})(?![0-9]|\s*[._]?e\d)(?![a-z])')


def season_of(name):
    """名字里的季号 → 's2' / 'all6'；没有返回 ''。只认「第 N 季 / Season N / S02（后面不跟集号）/ 全 N 季」。"""
    m = _SEASON.search(name or '')
    if not m:
        return ''
    if m.group(1):
        return 'all' + _CN_NUM.get(m.group(2), m.group(2))
    v = next(g for g in m.groups()[2:] if g)
    v = _CN_NUM.get(v, v)
    return 's' + str(int(v)) if v.isdigit() else 's' + v


# ---------------- 特效字幕版识别（反馈 16）----------------
# 名字里写了「…特效…字幕」（简繁特效字幕、双语特效字幕、国配简繁英特效四字幕、特效+导评五字幕）
SUBFX_WORD = re.compile(r'特效.{0,4}?字幕')


def subfx_matcher(names):
    """特效字幕组名单 → 判定函数 hit(文本) → 命中的名单项或 ''。
    拉丁名大小写不敏感，且前后不能紧挨字母数字（SGNB 不命中 LSGNBX；nn@CHDBits 不命中 Ann@CHDBits）；
    纯中文名按子串匹配，但片名本身不算（《逃往雅典娜》不是雅典娜做的盘）。"""
    pats = []
    for n in names or []:
        n = str(n).strip()
        if not n:
            continue
        if re.search(r'[A-Za-z0-9]', n):
            pats.append((n, re.compile(r'(?<![A-Za-z0-9])' + re.escape(n) + r'(?![A-Za-z0-9])', re.I), False))
        else:
            # 写成发布标签的样子（@雅典娜、-雅典娜、雅典娜@站、雅典娜小组@站）：不管在哪都算
            tag = re.compile(r'[@\-]\s*' + re.escape(n) + r'|' + re.escape(n) + r'(?:小组|字幕组)?\s*@')
            pats.append((n, re.compile(re.escape(n)), tag))

    def hit(text, titles=()):
        for n, p, tag in pats:
            t = text or ''
            if tag:
                if tag.search(t):
                    return n
                for ti in titles:                         # 中文名：先把片名挖掉再找
                    if ti:
                        t = t.replace(ti, ' ')
            if p.search(t):
                return n
        return ''
    return hit


def subfx_reason(name, hit):
    if SUBFX_WORD.search(name or ''):
        return '名字里写了「特效字幕」'
    g = hit(name, (_first_frag(name), S._title2(name or '')))
    return ('特效字幕组名单：' + g) if g else ''


# ---------------- 判档 ----------------
def _kind(name, zone, form, fx=''):
    n = (name or '').lower()
    if fx:
        return 'T'
    if 'diy' in n:
        return 'D'
    if zone == 'yuanpan':
        return 'I'
    if 'remux' in n or zone == 'remux':
        return 'R'
    if form in ('ISO', 'BDMV') or '原盘' in (name or '') or re.search(r'blu-?ray|bluray', n) and form == 'ISO':
        return 'I'
    return 'O'


def _res_name(s):
    n = (s or '').lower()
    if '2160p' in n or re.search(r'(?<![a-z0-9])(uhd|4k)(?![a-z0-9])', n):
        return 'U'
    if '1080p' in n or '1080i' in n:
        return 'H'
    if '720p' in n or '480p' in n or 'dvd' in n or '576p' in n:
        return 'S'
    return '?'


def _res(c):
    """→ (档 U/H/S/?, 来源：实测 / 文件名 / 体积推断 / 未知)。"""
    if c.get('vh'):
        v = c['vh']
        return ('U' if v >= 1600 else 'H' if v >= 900 else 'S'), '实测'
    r = _res_name(c['main_name']) if c['zone'] == 'yuanpan' else _res_name(c['name'] + ' ' + c['main_name'])
    if r != '?':
        return r, '文件名'
    if c['form'] in ('ISO', 'BDMV'):
        return ('U' if c['gb'] >= 55 else 'H'), '体积推断'
    if c['zone'] != 'yuanpan' and c['gb'] >= 40:
        return 'U', '体积推断'
    return '?', '未知'


def name_score(c):
    """命名座次（越大越该留）：带 {tmdb} / 在已刮削目录 / 规格写得全；裸名靠后。"""
    p = c['path']
    low = p.lower()
    s = 0
    if '{tmdb' in low or 'tmdbid' in low:
        s += 40
    if '刮削' in p:
        s += 50
    t = len(set(m.group(0).lower() for m in sieve_spec.finditer(c['name'] + ' ' + c['main_name'])))
    s += t if t else -100
    return s


sieve_spec = re.compile(r'(?i)(2160p|1080p|1080i|720p|480p|\buhd\b|4k|blu-?ray|remux|bdrip|web-?dl|webrip|hdtv|x264|x265|'
                        r'h\.?264|h\.?265|hevc|avc|dts|truehd|atmos|ddp|aac|flac|lpcm|hdr|dolby|\bdv\b|diy|字幕|国配|国语|'
                        r'粤语|特效|双语|简繁|中字|花絮|加长)')


ZONE_R = {'yuanpan': 3, 'remux': 2, 'pack': 1, 'heji': 0}   # 同分辨率同来源：原盘区那份是参照库，优先留


def rank(c):
    return (RES_R[c['res']], KIND_R[c['kind']], ZONE_R[c['zone']] + (10 if c.get('main') else 0), name_score(c), c['gb'])


# ---------------- 人口 ----------------
def _yuanpan_copies(meas, tab):
    units = [dict(r, totGB=float(r['totGB'])) for r in tab.rows('yuanpan_units.csv')]
    files = [dict(r, GB=float(r['GB'])) for r in tab.rows('yuanpan_files.csv')]
    un = {u['path']: u for u in units}
    out = []
    for u in units:
        if u['kind'] == 'BDMV':
            out.append(dict(path=u['path'], name=u['name'], main_name=u['name'], form='BDMV', gb=u['totGB'],
                            mgb=u['totGB'], vh=meas.get(u['path'])))
    byfolder = defaultdict(list)
    for f in files:
        if '/BDMV/' not in f['path']:
            byfolder[f['path'].rsplit('/', 1)[0]].append(f)
    for folder, fs in byfolder.items():
        clusters = defaultdict(list)
        for f in fs:
            clusters[ident(f['path'].rsplit('/', 1)[-1])[1:]].append(f)
        if len(clusters) <= 1:
            main = max(fs, key=lambda x: x['GB'])
            mn = main['path'].rsplit('/', 1)[-1]
            out.append(dict(path=folder, name=folder.rsplit('/', 1)[-1], main_name=mn,
                            form='ISO' if mn.lower().endswith('.iso') else 'FILE',
                            gb=un[folder]['totGB'] if folder in un else sum(x['GB'] for x in fs),
                            mgb=main['GB'], vh=meas.get(main['path'])))
        else:
            for f in fs:
                mn = f['path'].rsplit('/', 1)[-1]
                out.append(dict(path=f['path'], name=mn.rsplit('.', 1)[0], main_name=mn,
                                form='ISO' if mn.lower().endswith('.iso') else 'FILE', gb=f['GB'], mgb=f['GB'],
                                vh=meas.get(f['path'])))
    for c in out:
        c['zone'] = 'yuanpan'
    return out


# ---------------- 多碟装（反馈 17）----------------
# 同一个夹里并排放着的一套多碟（Disc1/2/3、CD1/2、碟一/二、上/下集），名字只差碟号：是一份，不是几份互为重复
_DISC_TOK = re.compile(r'^(\d{1,2}|[一二三四五六上中下]|[A-Da-d])$')
_DISC_KW = re.compile(r'(?i)(disc|disk|cd|dvd|bd|part|pt|vol|d)[\s._\-]*\(?$|[碟盘集部第][\s._\-]*$')
_NOT_DISC = re.compile(r'(?i)(x26|h\.?26|\d[\.\-]|\d{3,})$')   # x264/x265、5.1/7.1、1080/2160 这类规格差一位数不算碟号
# 名字里任意位置写着的碟号（Disc2、DISC.01、CD1、D1、第二碟、碟一、上集 / (下)）；「2-Disc Edition」这种不算
DISC_MARK = re.compile(r'(?i)[\s._\-\[(（]*(?:dis[ck]|cd)[\s._\-]*0?(\d{1,2})(?!\d)[\])）]?'
                       r'|[\s._\-]*(?:第[一二三四五六]碟|碟[一二三四五六])|[\s._\-]*[(（]?[上下]集[)）]?|[\s._\-]*[(（][上下][)）]')


def _norm_stem(s):
    return re.sub(r'[\s._\-]+', ' ', s).strip().lower()


def has_disc(name):
    return bool(DISC_MARK.search(name or ''))


# 判「只是一部分」只认 Disc / CD / 碟 写法；「（上）（下）」多半是分上下两部上映的独立影片（嘲笑鸟、破晓），不算
PARTIAL_MARK = re.compile(r'(?i)(?:dis[ck]|cd)[\s._\-]*0?\d{1,2}(?!\d)|第[一二三四五六]碟|碟[一二三四五六]')


def disc_siblings(a, b, iso):
    """a、b：同夹两个文件名（不带扩展名）。只差一个碟号 / 分段词 → True。
    ISO 等盘片文件不要求前面写 Disc / CD（写法不在词表里也认）；普通视频文件要求碟号前有 Disc / CD / Part / 碟 / 集 之类，
    免得把「片名(1).mkv / 片名(2).mkv」这种下载重名副本当成一套。"""
    if a == b:
        return False
    # 挖掉碟号后两边一样（一张写 Disc2、另一张不写碟号；或碟号在名字中段，后面还跟着 .1080p.AVC…）
    if (has_disc(a) or has_disc(b)) and _norm_stem(DISC_MARK.sub(' ', a)) == _norm_stem(DISC_MARK.sub(' ', b)):
        return True
    p = len(os.path.commonprefix([a, b]))
    ra, rb = a[p:], b[p:]
    q = len(os.path.commonprefix([ra[::-1], rb[::-1]]))
    da, db = ra[:len(ra) - q], rb[:len(rb) - q]
    if not (_DISC_TOK.match(da) and _DISC_TOK.match(db)):
        return False
    before, after = a[:p], ra[len(da):]
    if _NOT_DISC.search(before) or re.match(r'[.\-]\d(?!\d)|[A-Za-z]', after):   # 5.1 / 7.1 声道；2Audio / 4Audio、5ch 这类规格
        return False
    if da in '上中下' or _DISC_KW.search(before):
        return True
    if iso:
        return not (before.endswith('(') and after.startswith(')'))     # 「(1)」「(2)」是重名副本记号
    return False


def merge_sets(cs):
    """同区、同夹、同片名年份的单文件副本里，两两只差碟号的并成一套：路径列表 + 体积加总，按一份参与分组。"""
    buckets = defaultdict(list)
    for c in cs:
        if c['path'].rsplit('/', 1)[-1] == c['main_name'] or c['zone'] == 'heji':      # 单文件副本
            buckets[(c['zone'], c['path'].rsplit('/', 1)[0], c['tm'], c['title'], c['year'])].append(c)
    drop, add = set(), []
    for key, ms in buckets.items():
        if len(ms) < 2 or not (key[2] or key[3]):
            continue
        parent = list(range(len(ms)))

        def find(i):
            while parent[i] != i:
                i = parent[i]
            return i
        stem = [os.path.splitext(m['path'].rsplit('/', 1)[-1])[0] for m in ms]
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                iso = ms[i]['form'] in ('ISO', 'BDMV') and ms[j]['form'] in ('ISO', 'BDMV')
                if disc_siblings(stem[i], stem[j], iso):
                    parent[find(j)] = find(i)
        sets = defaultdict(list)
        for i in range(len(ms)):
            sets[find(i)].append(ms[i])
        for parts in sets.values():
            if len(parts) < 2:
                continue
            parts.sort(key=lambda m: m['path'])
            u = dict(parts[0])
            u['parts'] = [(m['path'], round(m['gb'], 2)) for m in parts]
            u['gb'] = sum(m['gb'] for m in parts)
            u['mgb'] = u['gb']
            u['small'] = False
            if any(m['res'] != '?' for m in parts):           # 档位取各碟里认得出的最高那个
                best = max(parts, key=lambda m: RES_R[m['res']])
                u['res'], u['res_src'] = best['res'], best['res_src']
            if u['form'] in ('ISO', 'BDMV') and u['res_src'] == '体积推断':
                u['res'] = 'U' if max(m['gb'] for m in parts) >= 55 else 'H'     # 按单碟体积推断，不按加总
            drop.update(id(m) for m in parts)
            add.append(u)
    return [c for c in cs if id(c) not in drop] + add


def copies(cfg, gone=frozenset(), tab=None):
    """全部副本。gone：已被别的线判掉的路径（原盘同名同大小），不再参与。
    tab：这一轮的中间表（panel.tables.Tables）；不给就读当前目录的 CSV（老结果复算 / 对账脚本）。"""
    tab = tables_of(tab)
    meas = {}
    if tab.has('emby_yp.csv'):
        for r in tab.rows('emby_yp.csv'):
            try:
                meas[r['source_path'].replace('/CloudNAS/CloudDrive', '')] = min(int(r['width']), int(r['height']))
            except (ValueError, KeyError):
                pass
    out = []
    for r in tab.rows('heji_films.csv'):
        nm = r['片名(文件名)']
        out.append(dict(zone='heji', path=r['路径'], name=nm, main_name='', form=r['形态'], gb=float(r['GB']),
                        mgb=float(r['GB']), vh=None, pack=r['大包']))
    if tab.has('yuanpan_units.csv'):
        out += _yuanpan_copies(meas, tab)
    if tab.has('cross_units.csv'):
        for u in tab.rows('cross_units.csv'):
            mn = u['主视频文件']
            form = 'ISO' if mn.lower().endswith('.iso') else ('BDMV' if '.' not in mn[-6:] else 'FILE')
            g = float(u['单元总GB']) * 1e9 / GIB                 # 单元体积是 1000 进制，换回 115 口径
            out.append(dict(zone=u['分区'], path=u['路径'], name=u['电影'], main_name=mn, form=form, gb=g, mgb=g, vh=None))
    extra = [x for x in cfg['exclude_names']]
    S.LP_OFF = tuple(cfg.get('listpack_off') or ())
    S.LP_ON = not cfg.get('tree_model')
    ml = (cfg.get('main_lib_dir') or '').rstrip('/') if cfg.get('tree_model') else ''
    hit = subfx_matcher(cfg.get('subfx_groups') or [])
    res = []
    gone_dirs = {g.rsplit('/', 1)[0] for g in gone}            # 被判掉的文件所在的夹：整夹那一份也不再参与
    for c in out:
        if c['path'] in gone or c['path'] in gone_dirs:
            continue
        p = c['path']
        c['main'] = bool(ml) and p.startswith(ml + '/')               # 反馈 23：主媒体库里的，同档时最优先留
        c['locked'] = bool(sources.lp_path(p, cfg) or any(e in p for e in S.EXCL) or sources.hit_any(p, extra))
        c['multi'] = bool(_MULTI.search(S.SPEC_CUT.sub(' ', c['name'])))           # 一份里装着几部片（红气球+白鬃野马）：可当保留份，自己不搬
        c['locked'] = c['locked'] or c['multi']
        c['subfx'] = subfx_reason(c['name'] + ' ' + c['main_name'], hit)
        c['kind'] = _kind(c['name'] + ' ' + c['main_name'], c['zone'], c['form'], c['subfx'])
        c['res'], c['res_src'] = _res(c)
        c['small'] = c['zone'] == 'heji' and (c['gb'] < SMALL_GB or (bool(S.LOWMARK.search(c['name'])) and c['gb'] < LOW_GB))
        # 认片看夹名（单元 / 盘片夹的名字就是片名）；夹名里缺的（TMDB / 片名 / 年份）再从主文件名补。两者拼起来会让拉丁片名重复一遍，对不上单文件
        c['tm'], c['title'], c['year'] = ident(c['name'])
        if c['main_name'] and c['main_name'] != c['name']:
            tm2, t2, y2 = ident(c['main_name'])
            c['tm'] = c['tm'] or tm2
            if not c['title']:
                c['title'], c['year'] = t2, c['year'] or y2
            elif not c['year'] and y2:
                c['year'] = y2
        c['f1'] = _first_frag(c['name'] + ' ' + c['main_name'])
        c['text'] = _flat(c['name'] + ' ' + c['main_name'])
        res.append(c)
    return merge_sets(res)


def _flat(s):
    return re.sub(r'[\s·・：:、，,.\-_！!？?\'"《》「」]+', '', s or '')


def _first_frag(name):
    """名字里第一个像样的中文片段（剥掉网站广告、目录号、规格词之后）——片名几乎总是写在最前面。"""
    s = _TAG.sub(' ', S.SITE_TAG.sub(' ', name or ''))
    s = S.SPEC_CUT.sub(' ', S.LEAD.sub('', s))
    for f in S.CJK.findall(s):
        if len(f) >= 2:
            return f
    return ''


def same_film(a, b):
    """同键的两份再核一次是不是同一部（防「英尤里卡版」这类比片名还长的发行商名撞键）：
    TMDB 相同 → 是；否则一方名字最前面的中文片段，要在另一方名字里出现。"""
    if a['tm'] and b['tm']:
        return a['tm'] == b['tm']
    fa, fb = a['f1'], b['f1']
    if not fa or not fb:
        return True
    return fa in b['text'] or fb in a['text']


def _split(ms):
    """按 same_film 把一组拆成「互相核得上」的小组：从最该留的那份起，逐份归到第一个核得上的小组。"""
    out = []
    for m in sorted(ms, key=rank, reverse=True):
        for sub in out:
            if same_film(sub[0], m):
                sub.append(m)
                break
        else:
            out.append([m])
    return out


# ---------------- 分组 ----------------
def group(cs):
    """并查集：同 TMDB 编号，或同「片名|年份」→ 同一组。返回 [[副本…]]（含单份组）。"""
    parent = list(range(len(cs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    first = {}
    for i, c in enumerate(cs):
        keys = []
        if c['tm']:
            keys.append('T' + c['tm'])
        if c['title']:
            keys.append('K' + c['title'] + '|' + c['year'])
        for k in keys:
            if k in first:
                parent[find(i)] = find(first[k])
            else:
                first[k] = i
    g = defaultdict(list)
    for i, c in enumerate(cs):
        if c['tm'] or c['title']:
            g[find(i)].append(c)
        else:
            g[('solo', i)].append(c)                         # 认不出片名的：自成一组，不和任何人比
    return list(g.values())


def _held(ms):
    """像剧集：≥2 份带集号，或合集区 ≥3 份在同一个夹（原盘区一个夹里平铺很多 ISO 是常态，不算）。"""
    fc = Counter(m['path'].rsplit('/', 1)[0] for m in ms if m['zone'] == 'heji')
    return (max(fc.values()) if fc else 0) >= 3 or sum(1 for m in ms if S.EP.search(m['name'])) >= 2


def _desc(c):
    return '%s · %s · %s' % (ZONE_NAME[c['zone']], KIND_NAME[c['kind']],
                               RES_NAME[c['res']] + ('（按体积推断）' if c['res_src'] == '体积推断' else ''))


def _tags(x, keep):
    t = []
    zs = {x['zone'], keep['zone']}
    if 'yuanpan' in zs and 'heji' in zs:
        t.append('与原盘重复')
    if zs == {'heji'}:
        t.append('合集内重复')
    if zs & {'remux', 'pack'}:
        t.append('涉及 REMUX / 整夹合集')
    if zs == {'yuanpan'}:
        t.append('原盘区内重复')
    if x.get('small'):
        t.append('小文件低质')
    if x['kind'] == 'T' or keep['kind'] == 'T':
        t.append('特效字幕版')
    return t


def _partial(c):
    """没并成一套、名字里写着碟号的副本。单文件看文件名；整夹 / 单元看夹名（夹里装着整套时主文件名带碟号是正常的）。"""
    if c.get('parts'):
        return False
    single = c['zone'] == 'heji' or c['path'].rsplit('/', 1)[-1] == c['main_name']
    return bool(PARTIAL_MARK.search((c['main_name'] if single and c['main_name'] else c['name']) or ''))


def judge(ms):
    """一组（同片、同剪辑版本）→ [(副本, 类, 保留份, 依据)]，保留份本身不出行。"""
    ms = sorted(ms, key=rank, reverse=True)
    keep = ms[0]
    rest = ms[1:]
    fam = lambda c: 'DT' if c['kind'] in DIY_FAMILY else c['kind']
    if keep['kind'] not in DIY_FAMILY:
        partner = next((m for m in rest if m['kind'] in DIY_FAMILY), None)
    else:
        partner = next((m for m in rest if m['kind'] == 'I'), None)
    out = []
    for x in rest:
        if x is partner:
            out.append((x, 'V', keep, '%s 和 %s 是一对版本（加了中文字幕的和原版），两份都留' % (KIND_NAME[keep['kind']], KIND_NAME[x['kind']])))
            continue
        # 和版本对里同一家的那份比（多出来的 DIY / 特效字幕版跟留下的那份比），否则跟保留份比
        k = partner if (partner is not None and fam(x) == fam(partner)) else keep
        px, pk = _partial(x), _partial(k)
        if px or pk:                                         # 反馈 18：单张碟没凑成套（或同片两版各写碟号），不自动判
            out.append((x, 'U', k, '%s名字里写着碟号、没和同套其他碟并成一套，可能只是一部分（或是同片另一版本），请自己看'
                        % ('这份' if px else '保留的那份')))
            continue
        if x['res'] == '?' or k['res'] == '?':
            if x['kind'] == 'R' and x['res'] == '?' and k['kind'] in ('I', 'D', 'T') and k['res'] == 'U' and k['res_src'] != '体积推断':
                out.append((x, 'N', k, 'REMUX 没标分辨率，保留的那份是已确认的 4K 原盘'))
            elif x['res'] == '?' and x.get('small') and k['res'] in ('U', 'H') and (k['gb'] >= 10 or k['gb'] >= 2 * x['gb']):
                out.append((x, 'A', k, '小文件、没标分辨率，保留的那份是正经版本'))      # 同原小文件层「原盘有正经份」
            elif x['res'] == '?' and k['res'] == '?' and x['kind'] == k['kind']:
                out.append((x, 'B', k, '两份都没标分辨率、来源相同，留更大 / 命名更好的那份'))   # 同原合集内重复
            elif x['res'] == '?' and x['kind'] == 'O' and k['kind'] in ('I', 'D', 'T', 'R') and k['res'] in ('U', 'H'):
                out.append((x, 'A', k, '没标分辨率的压制版，保留的那份是%s %s' % (KIND_NAME[k['kind']], RES_NAME[k['res']])))
            else:
                out.append((x, 'U', k, '有一边分辨率看不出，没法比，请自己看'))
            continue
        if RES_R[x['res']] < RES_R[k['res']]:
            out.append((x, 'A', k, '分辨率比保留的那份低'))
        else:
            out.append((x, 'B', k, '和保留的那份同分辨率，保留的那份来源 / 位置 / 命名更好'))
    return keep, out


def scan(cfg, gone=frozenset(), tab=None):
    """→ (rows, groups_out, stats)。rows 用 runner.row 的字段；groups_out = {组号: 成员摘要}。"""
    cs = copies(cfg, gone, tab)
    gs = group(cs)
    rows, gout = [], {}
    st = Counter()
    by_path = {}
    gid = 0
    for ms in gs:
        if len(ms) < 2:
            continue
        st['groups'] += 1
        if _held(ms):
            st['held_groups'] += 1
            st['held_copies'] += len(ms)
            continue
        gid += 1
        g = 'g%d' % gid
        parts = defaultdict(list)                          # 剪辑版本不同的分开比
        for m in ms:
            parts[bool(S.EDITION.search(m['name'] + ' ' + m['main_name']))].append(m)
        members = []
        subs = [x for part in parts.values() for x in _split(part)]
        st['split'] += len(subs) - len(parts)
        for sub in subs:
            if len(sub) < 2:
                members += [dict(path=m['path'], role='keep', **_brief(m)) for m in sub]
                continue
            keep, res = judge(sub)
            members.append(dict(path=keep['path'], role='keep', **_brief(keep)))
            for x, cls, k, why in res:
                if x['locked']:                            # 榜单包 / 排除词：不进可清理，也不出行
                    members.append(dict(path=x['path'], role='locked', **_brief(x)))
                    st['locked'] += 1
                    continue
                b = BUCKET[cls]
                members.append(dict(path=x['path'], role=b, **_brief(x)))
                basis = '%s：这份 %s；留 %s' % (why, _desc(x), _desc(k))
                fx = '；'.join(z for z in (('这份是特效字幕版（%s）' % x['subfx']) if x['subfx'] else '',
                                          ('留的是特效字幕版（%s）' % k['subfx']) if k['subfx'] else '') if z)
                if k.get('parts'):
                    fx = '；'.join(z for z in (fx, '留的那份是 %d 碟一套' % len(k['parts'])) if z)
                tags = _tags(x, k)
                # 多碟装整套被判掉：每张碟一行（搬运按文件），都写明是一套、要一起处理
                for i, (pp, pg) in enumerate(x.get('parts') or [(x['path'], x['gb'])]):
                    extra = {'subfx': fx} if fx else {}
                    note = fx
                    if x.get('parts'):
                        note = '；'.join(z for z in (fx, '多碟装第 %d / %d 张，整套一起处理' % (i + 1, len(x['parts']))) if z)
                        extra['disc_set'] = len(x['parts'])
                    rows.append(dict(stage=STAGE, cls=cls, bucket=b, path=pp, gb=round(pg, 2), keep=k['path'],
                                     basis=basis + ('。' + note if note else ''), tags=tags + (['多碟装'] if x.get('parts') else []),
                                     grp=g, keep_gb=round(k['gb'], 2), **extra))
                    st[b] += 1
        gout[g] = {'title': _gtitle(ms), 'members': members}
    for c in cs:
        by_path[c['path']] = c
    st['copies'] = len(cs)
    return rows, gout, dict(st), gs


def _brief(c):
    return {'zone': c['zone'], 'kind': c['kind'], 'res': c['res'], 'res_src': c['res_src'], 'gb': round(c['gb'], 2),
            'subfx': c.get('subfx', ''), 'parts': [pp for pp, _ in c.get('parts') or []]}


def _gtitle(ms):
    for m in ms:
        if S.CJK.search(m['title'] or ''):
            return m['title'] + (' (%s)' % m['year'] if m['year'] else '')
    m = ms[0]
    return (m['title'] or m['name']) + (' (%s)' % m['year'] if m['year'] else '')


def lone_small(gs):
    """孤本（口径同原第三刀）：合集区小文件层、全库只有这一份（组里只有它自己）。"""
    out = []
    for ms in gs:
        if len(ms) == 1 and ms[0]['small'] and not ms[0]['locked']:
            out.append(ms[0])
    return out
