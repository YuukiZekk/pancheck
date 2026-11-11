#!/usr/bin/env python3
"""115 存量电影筛选内核 —— 手工两刀的收编版（只读分析，只出清单）

流水线：片级展开 → 分组 → 定档 → 选参照/保留份 → 分类。
  第一刀：合集区 × 原盘区同片（原盘侧先按文件簇展开到片级，Emby 实测分辨率优先于文件名标注）
  第三刀：小文件低质层（原盘份→区内锚点→Emby 纵向 三级判定链）
  纵向轴：三刀后合集剩余片 × Emby 库 —— 洗版提醒/入库提醒（TMDB 精确才出，疑似只标注）
  第二刀：合集区内互重（第一刀 A/B 出局后的人口；可信度过滤 + 剧集塌缩守卫）

口径即手工账本身，两处已知毛边如实保留并注明：
  1) 无标注 ISO 按 55GB 线体积推断档位，且推断档按面值参与比较（第二刀 A 类里约千条属此）；
  2) 第一刀的 DIY 判定含大包级继承（至尊宝/SGNB/Blucook/不撸酷客 整包视为 DIY 来源）。
保护：合集榜单包（豆瓣Top250/IMDB Top 250/戛纳电影节，见 LP_RE）不筛；金庸/动漫/ADWEB 第二刀不碰。
"""
import csv, re
from collections import defaultdict, Counter

# ================= 通用：身份键 =================
BAD = r'(原盘|字幕|国语|国配|简繁|双语|特效|菜单|修改|新增|按钮|花絮|中字|原生|全景声|次世代|公映|台配|粤语|导评|双格式|架构|版本|标准收藏|传媒|国版|美版|欧版|日版|港版|台版|韩版|法版|德版|意版|英版|蓝光|修复|重制|剪辑|加长|终极|限量|独家|系列|合集|全集|三部曲|二部曲|文件|文件夹)'
AUTH = r'(至尊宝|雅典娜|碟影|殿堂级|老K|老k)'

def yearof(s):
    m = re.search(r'(19|20)\d{2}', s or '')
    return m.group(0) if m else ''

def keyof1(name):
    """第一刀键：取第一个像片名的中文片段 + 年份（原盘/合集两侧同口径）。"""
    s = name or ''
    s = re.sub(r'@\S+', '', s)
    s = re.sub(r'\.(iso|mkv|mp4|m2ts|ts|avi)$', '', s, flags=re.I)
    s = re.sub(r'\[\d+(\.\d+)?\s*[GT]B?\]', '', s)
    s = re.sub(r'[\{\}\[\]]', ' ', s)
    y = yearof(s)
    cjk = re.findall(r'[一-鿿㐀-䶿][一-鿿㐀-䶿\w ·：:、，]{1,30}', s)
    cjk = [c.strip(' ·：:、，') for c in cjk]
    cjk = [c for c in cjk if len(re.sub(r'[\s·：:、，]', '', c)) >= 2
           and not re.search(BAD, c) and not re.fullmatch(AUTH, c.strip())]
    if cjk:
        return (re.sub(r'[\s·：:、，]+', '', cjk[0]).lower(), y)
    s2 = re.sub(r'(?i)\b(2160p|1080p|720p|4k|uhd|ultra hd|remux|blu-?ray|bd|iso|diy|web-?dl|hdtv|'
                r'x264|x265|h\.?264|h\.?265|hevc|avc|dts|truehd|atmos|ddp?5\.1|aac|flac|hdr10?\+?|'
                r'dv|dolby|vision|extended|remastered|complete|repack|v\d)\b', '', s)
    return (re.sub(r'[\s\.\-_·：:、，]+', '', s2).lower(), y)

TMDB2 = re.compile(r'tmdb[=:\-]?(\d{3,7})', re.I)
YEAR2 = re.compile(r'(?<!\d)(19[3-9]\d|20[0-2]\d)(?!\d)')
LEAD = re.compile(r'^[#\d\s\.\-_、：:【】\[\]（）()]+')
CJK = re.compile(r'[一-鿿]+')
PURE = {'至尊宝', '雅典娜', '碟影'}

# 规格短语（反馈 13，2026-11-11 修）：字幕/音轨/盘型词，片名里不会出现。
# 原先取「最长中文片段」时不挖掉它们，DIY 盘的「双语特效字幕」比片名长，就被当成了片名，
# 同年两张无关的 DIY 盘因此撞键（神偷奶爸4 × 沙丘2、十二怒汉 × 第七封印……）。
SPEC_CUT = re.compile(r'(字幕|特效|双语|三语|多语|简繁|繁简|简中|繁中|简体|繁体|中字|双字|中英|国英|国粤|'
                      r'国配|国语|粤语|台配|粤配|音轨|花絮|菜单|原盘|导评|全景声|次世代|内封|蓝光|杜比|上译|长影|内参|公映|译制|正片|高清|'
                      # 版本 / 地区版词（「奇蹟(完整版)」「W的悲剧 日角川版」里比片名还长的那段）
                      r'导演剪辑版|剪辑版|加长版|未删减版|无删减版|删减版|完整版|终极版|收藏版|典藏版|珍藏版|纪念版|'
                      r'修复版|重制版|特别版|国际版|影院版|公映版|标准版|豪华版|角川版|北美版|大陆版|'
                      r'国版|港版|台版|美版|日版|韩版|欧版|英版|法版|德版|意版|俄版)')
# 判「片名其实是规格短语」用的词表：规格短语 + 少量只在规格里出现的词。不放「修复 / 导演 / 终极」这类
# 也会出现在片名里的词（真库里有《修复体》《终极标靶》）。挖掉这些后剩不到两个字的，不当片名用
SPEC_ALL = re.compile(SPEC_CUT.pattern[:-1] + r'|版本|无中字|中文|英文|版)', re.I)
# 方括号里的网站广告（【高清MP4电影www.xxx.com】[BD影视分享bd2020.co]）：整段不算片名
SITE_TAG = re.compile(r'[【\[][^】\]]*(?:www\.|\.com|\.co\b|\.net|\.cc|\.org|\.top|\.vip)[^】\]]*[】\]]', re.I)
_SPEC_LAT = re.compile(r'(?i)\b(4k|diy|uhd|hdr\d*|dv|bd|iso|remux|v\d)\b')

def _norm(x):
    return re.sub(r'[\s\W_]+', '', x or '').lower()

def title_suspect(title, year=''):
    """分组键里的片名不像片名 → 整组不可信（反馈 13 修复要求 2）：
    空、只是年份本身、或挖掉规格词后才剩不到两个字（「双语特效字幕」「导演剪辑版」）。
    本来就是一个字（洞、影）或纯数字（2012、1917）的片名不算。"""
    t0 = _norm(title)
    if not t0 or t0 == year:
        return True
    t1 = _norm(_SPEC_LAT.sub(' ', SPEC_ALL.sub(' ', title)))
    return t1 != t0 and len(re.sub(r'\d', '', t1)) < 2

def _title2(s):
    """第二刀片名：先切到首个分辨率/来源词之前，再挖掉规格短语，最后取最长中文片段。
    片名就是一个数字的（2012 (2009)、1917(2019)），前导数字会被 LEAD 一并切掉，这里把它找回来。"""
    head0 = re.split(r'(?i)(2160p|1080p|720p|480p|uhd|remux|blu-?ray|bdrip|web-?dl|hdtv)', SITE_TAG.sub(' ', s))[0]
    head = SPEC_CUT.sub(' ', LEAD.sub('', head0))
    cjk = CJK.findall(head)
    if cjk:
        longest = max(cjk, key=len)
        return longest if len(longest) >= 2 else ''.join(cjk)
    t = re.sub(r'[\s\.\-_]+', ' ', head).strip().lower()
    if not t:
        m = re.match(r'\s*(\d{1,4})(?!\d)', head0)
        t = m.group(1) if m else ''
    return t

def keyof2(name):
    """第二刀键：TMDB 优先；片名取首个规格词之前、挖掉规格短语后的最大中文片段。"""
    m = TMDB2.search(name)
    tm = m.group(1) if m else ''
    s = re.sub(r'@\w+$', '', name)
    s = re.sub(r'\.(iso|mkv|mp4|m2ts|ts|avi|wmv|mov|rmvb|flv)$', '', s, flags=re.I)
    ys = YEAR2.findall(s)
    year = ys[-1] if ys else ''
    title = _title2(s)
    if title in PURE or (title and all(w in PURE for w in CJK.findall(title))):
        title = ''
    return (('T' + tm) if tm else ''), title + '|' + year

# ================= 第一刀 =================
TR = {'U': 3, 'H': 2, 'S': 1, '?': 0}
DIY_PACKS = ('至尊宝', 'SGNB', 'Blucook', '不撸酷客')
# 榜单包（反馈 19）：只认榜单组合词——豆瓣/IMDb + Top N / 榜单、Top 250、戛纳 + 电影节/金棕榈/获奖……
# 「豆瓣8.3分」「豆瓣排名117」「IMDb 7.5」「戛纳影帝」这类评分 / 简介字样不算（旧版拿裸「豆瓣」做整路径子串，误伤剧集和单片）
LP_RE = re.compile(r'(?i)top\s*250|(?:豆瓣|imdb)[^/]{0,6}?(?:top\s*\d{2,3}|榜单|排行榜)'
                   r'|戛纳[^/]{0,4}?(?:电影节|影展|金棕榈|获奖|入围|参展|主竞赛|历届)')
LP_OFF = ()          # 用户在面板里点过「不算榜单包」的目录（路径），面板跑判定前设


def listpack_word(text):
    m = LP_RE.search(text or '')
    return m.group(0) if m else None


def is_listpack(path):
    if any(path == o or path.startswith(o.rstrip('/') + '/') for o in LP_OFF):
        return False
    return bool(LP_RE.search(path or ''))

PRE = '/115/01-好康的/01-电影原盘'

def tier_of(name, vh=None):
    if vh:
        return 'U' if vh >= 1600 else ('H' if vh >= 900 else 'S')
    s = name or ''
    if re.search(r'(?i)2160p|\buhd\b|ultra hd', s): return 'U'
    if re.search(r'(?i)1080p', s): return 'H'
    if re.search(r'(?i)720p|480p', s): return 'S'
    return '?'

def tier2(name, iso, gb, vh=None):
    t = tier_of(name, vh)
    if t != '?':
        return t, '标记'
    if iso:
        return ('U', '体积推断') if gb >= 55 else ('H', '体积推断')
    return '?', '未知'

def stage1():
    units = list(csv.DictReader(open('yuanpan_units.csv', encoding='utf-8')))
    for r in units: r['totGB'] = float(r['totGB'])
    files_y = list(csv.DictReader(open('yuanpan_files.csv', encoding='utf-8')))
    for f in files_y: f['GB'] = float(f['GB'])
    meas = {}
    for r in csv.DictReader(open('emby_yp.csv', encoding='utf-8')):
        src = r['source_path'].replace('/CloudNAS/CloudDrive', '')
        try: vh = min(int(r['width']), int(r['height']))
        except Exception: vh = None
        meas[src] = vh
    # 原盘侧展开到片级：一夹一簇=一部；多簇则逐文件成片
    movies = []
    un_by_path = {u['path']: u for u in units}
    byfolder = defaultdict(list)
    for f in files_y:
        if '/BDMV/' in f['path']: continue
        byfolder[f['path'].rsplit('/', 1)[0]].append(f)
    for u in units:
        if u['kind'] == 'BDMV':
            movies.append(dict(name=u['name'], GB=u['totGB'], path=u['path'], main=u['path'], iso=True))
    for folder, fs in byfolder.items():
        fu = un_by_path.get(folder)
        clusters = defaultdict(list)
        for f in fs:
            clusters[keyof1(f['path'].rsplit('/', 1)[-1])].append(f)
        if len(clusters) <= 1:
            main = max(fs, key=lambda x: x['GB'])
            movies.append(dict(name=folder.rsplit('/', 1)[-1],
                               GB=fu['totGB'] if fu else sum(x['GB'] for x in fs),
                               path=folder, main=main['path'],
                               iso=main['path'].lower().endswith('.iso')))
        else:
            for ck, cfs in clusters.items():
                for f in cfs:
                    movies.append(dict(name=f['path'].rsplit('/', 1)[-1].rsplit('.', 1)[0],
                                       GB=f['GB'], path=f['path'], main=f['path'],
                                       iso=f['path'].lower().endswith('.iso')))
    yp_best = {}
    for m in movies:
        m['tier'], m['tsrc'] = tier2(m['name'], m.get('iso', False), m['GB'], meas.get(m['main']))
        if m['tsrc'] == '未知' and meas.get(m['main']):
            m['tier'], m['tsrc'] = tier_of(m['name'], meas.get(m['main'])), '实测'
        m['diy'] = bool(re.search(r'(?i)\bDIY\b|特效字幕', m['name']))
        k = keyof1(m['name'])
        if not k[0] or len(k[0]) < 2: continue
        cur = yp_best.get(k)
        if cur is None or TR[m['tier']] > TR[cur['tier']] or (m['tier'] == cur['tier'] and m['GB'] > cur['GB']):
            yp_best[k] = m
    print('原盘片级参照:', len(yp_best))
    rows = []
    for r in csv.DictReader(open('heji_films.csv', encoding='utf-8-sig')):
        top, title, gb, form, path = r['大包'], r['片名(文件名)'], float(r['GB']), r['形态'], r['路径']
        if listpack_word(top) and is_listpack(path):
            continue
        parent = path.rsplit('/', 1)[0].rsplit('/', 1)[-1]
        ctx = title + ' ' + parent                      # 档位/DIY 看文件名+父夹名
        pt, tsrc = tier2(ctx, form == 'ISO', gb)
        if pt == '?' and form != 'ISO' and gb >= 40:
            pt, tsrc = 'U', '体积推断'
        diy = any(k in top for k in DIY_PACKS) or bool(re.search(r'(?i)\bDIY\b|特效字幕', ctx))
        ym = yp_best.get(keyof1(title))
        if ym is None:
            continue
        yt = ym['tier']
        if diy and not ym['diy']: cls = 'C'
        elif pt != '?' and yt != '?' and TR[pt] < TR[yt]: cls = 'A'
        elif pt == yt and pt != '?': cls = 'B'
        elif pt != '?' and yt != '?' and TR[pt] > TR[yt]: cls = 'E'
        elif yt == '?': cls = 'D1'
        else: cls = 'D2'
        rows.append([cls, path, gb, ym['path'], ym['GB'],
                     pt + ('*' if tsrc == '体积推断' else ''), yt + ('*' if ym['tsrc'] == '体积推断' else '')])
    return rows

# ================= 第二刀 =================
RES_R = {'U': 3, 'U*': 3, 'H': 2, 'H*': 2, '?': 1, 'S': 0}
KIND_R = {'D': 4, 'I': 3, 'R': 2, 'O': 1}
EXCL = ('金庸', '动漫', 'ADWEB')
EP = re.compile(r'(?i)(s\d{1,2}e\d{1,3}|第\s*\d{1,3}\s*[集话話]|\bep\.?\s*\d{1,3}\b)')
EDITION = re.compile(r'(导演剪辑|加长版|扩展版|imax|未分级|终极版|theatrical|extended|director)', re.I)

def tier_s2(name, form, gb):
    n = name.lower()
    if '2160p' in n or 'uhd' in n or '4k' in n: res = 'U'
    elif '1080p' in n or '1080i' in n: res = 'H'
    elif '720p' in n or '480p' in n or 'dvd' in n: res = 'S'
    elif form == 'ISO': res = 'U*' if gb >= 55 else 'H*'
    elif gb >= 40: res = 'U*'
    else: res = '?'
    if 'diy' in n or '特效字幕' in name: kind = 'D'
    elif 'remux' in n: kind = 'R'
    elif form == 'ISO' or '原盘' in name or 'blu-ray' in n or 'bluray' in n: kind = 'I'
    else: kind = 'O'
    return kind, res

def stage2(cut1):
    groups = defaultdict(list)
    for r in csv.DictReader(open('heji_films.csv', encoding='utf-8-sig')):
        path = r['路径']
        if path in cut1 or is_listpack(path) or any(e in path for e in EXCL):
            continue
        name, gb = r['片名(文件名)'], float(r['GB'])
        tm, key = keyof2(name)
        groups[(tm, key) if tm else ('', key)].append(
            dict(name=name, gb=gb, tier=tier_s2(name, r['形态'], gb), path=path, tm=tm, key=key))
    def credible(ms):
        if len({m['tm'] for m in ms if m['tm']}) == 1 and any(m['tm'] for m in ms):
            return True
        if any(title_suspect(*m['key'].split('|', 1)) for m in ms):   # 片名是规格短语/空：整组不可信
            return False
        def cjk4(m):
            mm = CJK.findall(m['key'].split('|')[0])
            return mm[0][:4] if mm else m['key'][:6]
        return len({cjk4(m) for m in ms}) == 1
    rowsA, rowsB, held = [], [], 0
    for gkey, ms in groups.items():
        if len(ms) < 2 or not credible(ms):
            continue
        foldercount = Counter(m['path'].rsplit('/', 1)[0] for m in ms)
        if max(foldercount.values()) >= 3 or sum(1 for m in ms if EP.search(m['name'])) >= 2:
            held += len(ms) - 1
            continue
        ms = sorted(ms, key=lambda m: (KIND_R[m['tier'][0]] * 10 + RES_R[m['tier'][1]], m['gb']), reverse=True)
        keep = ms[0]
        partner_taken = False
        for m in ms[1:]:
            kk, mk = keep['tier'][0], m['tier'][0]
            version_pair = (kk == 'D' and mk == 'I') or (kk == 'I' and mk == 'D')
            ed_diff = bool(EDITION.search(m['name'])) != bool(EDITION.search(keep['name']))
            if version_pair and not partner_taken and not ed_diff:
                cls = 'B'; partner_taken = True
            elif ed_diff:
                cls = 'B'
            else:
                cls = 'A'
            (rowsA if cls == 'A' else rowsB).append([cls, m['path'], m['gb'], keep['path']])
    return rowsA, rowsB, held

def keyof3(name):
    """第三刀键：与 keyof2 只差一处——纯片名作者过滤只认整名相等，
    不做「全词皆作者名」判定（keyof2 的该判定会把无中文的拉丁片名误清空，
    这是第二刀金标准本身的行为，保留在 keyof2 里，不带进第三刀）。"""
    tm, key = keyof2(name)
    if not key.startswith('|'):
        return tm, key
    s = re.sub(r'@\w+$', '', name)
    s = re.sub(r'\.(iso|mkv|mp4|m2ts|ts|avi|wmv|mov|rmvb|flv)$', '', s, flags=re.I)
    ys = YEAR2.findall(s)
    year = ys[-1] if ys else ''
    title = _title2(s)
    if title in PURE:
        title = ''
    return tm, title + '|' + year

# ================= 第三刀：小文件低质层 =================
LOWMARK = re.compile(r'(?i)(720p|480p|dvdrip|webrip|hdtv|标清|\bSD\b|576p|540p)')

def load_emby():
    by_tmdb, by_title = {}, {}
    for r in csv.DictReader(open('emby_titles.csv', encoding='utf-8-sig')):
        vh = int(r['max_vh'] or 0)
        if r['tmdb']:
            by_tmdb[r['tmdb']] = max(vh, by_tmdb.get(r['tmdb'], 0))
        key = (r['name'] or '').strip() + '|' + (r['year'] or '')
        by_title[key] = max(vh, by_title.get(key, 0))
    return by_tmdb, by_title

def stage3(s1_rows, s2_rows, emby_tmdb):
    """人口：前两刀后剩余合集片（榜单/EXCL 除外）中的小文件层
    （主文件 <8GB，或明牌低档且 <15GB）。判定链：原盘份 → 区内锚点 → Emby 纵向。"""
    p1map = {r[1]: r for r in s1_rows}
    gone = {r[1] for r in s1_rows if r[0] in ('A', 'B')} | {r[1] for r in s2_rows}
    pop = []
    for r in csv.DictReader(open('heji_films.csv', encoding='utf-8-sig')):
        path = r['路径']
        if path in gone or is_listpack(path) or any(e in path for e in EXCL):
            continue
        gb = float(r['GB'])
        low = bool(LOWMARK.search(r['片名(文件名)']))
        if not (gb < 8 or (low and gb < 15)):
            continue
        tm, key = keyof3(r['片名(文件名)'])
        pop.append(dict(name=r['片名(文件名)'], gb=gb, path=path, tm=tm, key=key,
                        tier=tier_s2(r['片名(文件名)'], r['形态'], gb)))
    groups = defaultdict(list)
    for x in pop:
        groups[(x['tm'], x['key']) if x['tm'] else ('', x['key'])].append(x)
    def credible(ms):
        if len({m['tm'] for m in ms if m['tm']}) == 1 and any(m['tm'] for m in ms):
            return True
        if any(title_suspect(*m['key'].split('|', 1)) for m in ms):   # 片名是规格短语/空：整组不可信
            return False
        def cjk4(m):
            mm = CJK.findall(m['key'].split('|')[0])
            return mm[0][:4] if mm else m['key'][:6]
        return len({cjk4(m) for m in ms}) == 1
    def rank(t, gb):
        return (KIND_R[t[0]] * 10 + RES_R[t[1]], gb)
    rowsA, rowsB, lone = [], [], []
    for x in pop:
        cls, basis, keeper = None, '', ''
        r1 = p1map.get(x['path'])
        if r1:                                   # 1) 第一刀留下的 C/D 份：看原盘那份成色
            if r1[0] in ('C', 'E'):
                continue                         # 版本型/合集更高：规则挂起，不计孤本
            pgb = r1[4]
            if pgb >= 10 or pgb >= 2 * x['gb']:
                cls, basis, keeper = 'A', f"原盘有正经份({pgb}GB/{r1[6]})", r1[3]
            else:
                cls, basis, keeper = 'B', f"原盘份也不大({pgb}GB/{r1[6]})", r1[3]
        if cls is None:                          # 2) 区内锚点（同属小文件层，只合并看）
            ms = groups[(x['tm'], x['key']) if x['tm'] else ('', x['key'])]
            fc = Counter(m['path'].rsplit('/', 1)[0] for m in ms)
            ep_suspect = max(fc.values()) >= 3 or sum(1 for m in ms if EP.search(m['name'])) >= 2
            if len(ms) >= 2 and credible(ms) and not ep_suspect:
                anchor = max(ms, key=lambda m: rank(m['tier'], m['gb']))
                if anchor is not x and (rank(anchor['tier'], 0)[0] > rank(x['tier'], 0)[0]
                                        or anchor['gb'] >= 2 * x['gb']):
                    cls, basis, keeper = 'B', '区内有更好份但同属小文件层,合并看', anchor['path']
        if cls is None and x['tm']:              # 3) Emby 纵向：TMDB 精确且库内 ≥1080
            vh = emby_tmdb.get(x['tm'][1:])
            if vh and vh >= 1080:
                cls, basis, keeper = 'A', f'Emby库内有{vh}p(纵向)', 'Emby'
        if cls is None:
            lone.append(x)
        else:
            (rowsA if cls == 'A' else rowsB).append([cls, x['path'], x['gb'], basis, keeper])
    return rowsA, rowsB, lone, len(pop)

# ================= 纵向轴：合集剩余片 × Emby 库 =================
NOMINAL = {'U': 2160, 'H': 1080, 'S': 720, 'U*': 2160, 'H*': 1080, '?': 0}

def vertical(cut_paths, emby_tmdb, emby_title):
    """只读提醒，不写 Emby：TMDB 精确才出提醒；片名疑似只标注；库里没有的出入库提醒。"""
    out = []
    for r in csv.DictReader(open('heji_films.csv', encoding='utf-8-sig')):
        path = r['路径']
        if path in cut_paths or is_listpack(path) or any(e in path for e in EXCL):
            continue
        name, gb = r['片名(文件名)'], float(r['GB'])
        tm, key = keyof3(name)
        kind, res = tier_s2(name, r['形态'], gb)
        mine = NOMINAL[res]
        if tm and tm[1:] in emby_tmdb:
            vh = emby_tmdb[tm[1:]]
            if mine >= 2160 and vh < 1600 or mine == 1080 and vh < 900:
                out.append(['洗版提醒', path, gb, f'手里{res}档 vs 库内{vh}p'])
            else:
                out.append(['库内已有同档+', path, gb, f'库内{vh}p'])
        elif key in emby_title:
            out.append(['疑似同片(仅标注)', path, gb, f'片名命中,库内{emby_title[key]}p'])
        else:
            out.append(['入库提醒', path, gb, '库内无此片'])
    return out

def tally(rows, idx=2):
    c = Counter(); v = Counter()
    for r in rows:
        c[r[0]] += 1; v[r[0]] += r[idx]
    return {k: (c[k], round(v[k])) for k in sorted(c)}

if __name__ == '__main__':
    s1 = stage1()
    print('第一刀（金标准 A553 B3759 C165 D1069 E72）:', tally(s1))
    cut1 = {r[1] for r in s1 if r[0] in ('A', 'B')}
    rowsA, rowsB, held = stage2(cut1)
    all2 = rowsA + rowsB
    print('第二刀（金标准 A4394 B376，守卫挂起 10032）:', tally(all2), '| 守卫挂起:', held)
    emby_tmdb, emby_title = load_emby()
    s3A, s3B, lone, popn = stage3(s1, all2, emby_tmdb)
    print(f'第三刀（金标准 人口9308 A413 B32 孤本8862）: 人口 {popn} |',
          tally(s3A + s3B), '| 孤本:', len(lone))
    cut_all = cut1 | {r[1] for r in rowsA} | {r[1] for r in s3A}
    vert = vertical(cut_all, emby_tmdb, emby_title)
    vc = Counter(r[0] for r in vert)
    print('纵向轴（合集剩余片 × Emby 库）:', dict(vc))
    with open('sieve_stage1.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(['类', '候选路径', 'GB', '原盘保留份', '原盘GB', '合集档', '原盘档']); w.writerows(s1)
    with open('sieve_stage2.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(['类', '候选路径', 'GB', '保留份']); w.writerows(all2)
    with open('sieve_stage3.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(['类', '候选路径', 'GB', '依据', '更优副本']); w.writerows(s3A + s3B)
    with open('sieve_lone.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(['路径', 'GB']); w.writerows([[x['path'], x['gb']] for x in lone])
    with open('sieve_vertical.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f); w.writerow(['提醒类', '路径', 'GB', '说明']); w.writerows(vert)
