"""跨区比对模块（面板层，不改 sieve.py）。

合集 × REMUX（A1）：口径逐字复现 cross_remux.py 的 TASK 1（2026-11-10 当轮）。
  - 合集侧：合集区影片（heji_films 人口，去榜单包/排除词）+ 整夹合集区单元（如 10-合集）
  - REMUX 侧：REMUX 区单元，只当参照；同键多份时取 rank 最高者作保留份
  - A 档低 / B 同档 → 合集侧那份可清理；C DIY 与非 DIY → 两边留；
    D 合集更高 → REMUX 侧那份待议；E 任一侧分辨率推断不出且本会判 A/B → 待定
单元：直接放着视频文件的文件夹 = 一个单元，主视频 = 夹内最大的那个，单元名 = 夹名；
单元体积按 1000 进制 GB（当轮 union_units 的口径，复现必须一致）。
"""
import re
from collections import defaultdict

# ---------- keyof v3 / tier / rank：cross_remux.py 原文 ----------
TMDB = re.compile(r'tmdb[=:\-]?(\d{3,7})', re.I)
YEAR = re.compile(r'(?<!\d)(19[3-9]\d|20[0-2]\d)(?!\d)')
LEAD = re.compile(r'^[#\d\s\.\-_、：:【】\[\]（）()]+')
SEO = re.compile(r'[\s\.\-_]+')
CJK = re.compile(r'[一-鿿]+')
AUTHOR = re.compile(r'@(\w+)$')
PURE = {'至尊宝', '雅典娜', '碟影'}


def keyof(name):
    m = TMDB.search(name)
    tm = m.group(1) if m else ''
    s = AUTHOR.sub('', name)
    s = re.sub(r'\.(iso|mkv|mp4|m2ts|ts|avi|wmv|mov|rmvb|flv)$', '', s, flags=re.I)
    ys = YEAR.findall(s)
    year = ys[-1] if ys else ''
    head = re.split(r'(?i)(2160p|1080p|720p|480p|uhd|remux|blu-?ray|bdrip|web-?dl|hdtv)', s)[0]
    head = LEAD.sub('', head)
    cjk = CJK.findall(head)
    if cjk:
        longest = max(cjk, key=len)
        title = longest if len(longest) >= 2 else ''.join(cjk)
    else:
        title = SEO.sub(' ', head).strip().lower()
    if title in PURE:
        title = ''
    return (('T' + tm) if tm else ''), title + '|' + year


def tier(name, form, gb):
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


RES_R = {'U': 3, 'U*': 3, 'H': 2, 'H*': 2, '?': 1, 'S': 0}
KIND_R = {'D': 4, 'I': 3, 'R': 2, 'O': 1}


def rank(t, gb):
    return (KIND_R[t[0]] * 10 + RES_R[t[1]], gb)


def is_diy(name):
    return bool(re.search(r'(?i)\bdiy\b', name)) or '特效字幕' in name


def _keymap(items, use_main=False):
    d = defaultdict(list)
    for x in items:
        nm = (x['name'] + ' ' + x.get('main', '')) if use_main else x['name']
        x['tm'], x['key'] = keyof(nm)
        x['tier'] = tier(nm, x['form'], x['gb'])
        x['diy'] = is_diy(nm)
        d[(x['tm'], x['key']) if x['tm'] else ('', x['key'])].append(x)
    return d


def _credible(a, b):
    if a['tm'] and b['tm']:
        return a['tm'] == b['tm']

    def cjk4(x):
        mm = CJK.findall(x['key'].split('|')[0])
        return mm[0][:4] if mm else x['key'][:6]
    return cjk4(a) == cjk4(b) and cjk4(a) != ''


def heji_x_remux(heji_items, pack_units, remux_units):
    """heji_items: [{pack,name,gb,form,path}]；pack_units / remux_units: [{pack,name,gb,form:'',path,main}]
    返回 [(cls, src_label, x, ref)]，cls ∈ A/B/C/D/E，顺序与原脚本一致。"""
    rxmap = _keymap(remux_units, use_main=True)
    out = []
    for src_items, src_label in [(heji_items, '01-电影合集'), (pack_units, '10-合集')]:
        smap = _keymap(src_items)
        for k, ms in smap.items():
            refs = rxmap.get(k)
            if not refs:
                continue
            ref = max(refs, key=lambda m: rank(m['tier'], m['gb']))
            for x in ms:
                if not _credible(x, ref):
                    continue
                xr, rr = rank(x['tier'], 0)[0], rank(ref['tier'], 0)[0]
                if x['diy'] != ref['diy']:
                    cls = 'C'
                elif xr < rr:
                    cls = 'A'
                elif xr == rr:
                    cls = 'B'
                elif xr > rr:
                    cls = 'D'
                else:
                    cls = 'E'
                if (x['tier'][1] == '?' or ref['tier'][1] == '?') and cls in ('A', 'B'):
                    cls = 'E'
                out.append((cls, src_label, x, ref))
    return out


GOLD_LABEL = {'A': 'A-可切(合集侧)', 'B': 'B-同档可切(合集侧)', 'C': 'C-版本型(两边留)',
              'D': 'D-合集更高(REMUX侧待议)', 'E': 'E-待定'}


def build_units(files, video_ext, gb_div=1e9):
    """files: [(vpath, bytes, kind)] 某个分区下的条目（kind = 'file' | 'disc'）。
    直接放着视频文件的夹 = 单元；盘片夹整个算一个单元（主视频 = 盘片夹名）。"""
    by_dir = defaultdict(list)
    units = []
    for vp, size, kind in files:
        if kind == 'disc':
            units.append({'name': vp.rsplit('/', 1)[-1], 'main': vp.rsplit('/', 1)[-1], 'gb': round(size / gb_div, 2),
                          'form': '', 'path': vp})
        else:
            by_dir[vp.rsplit('/', 1)[0]].append((vp, size))
    for d, fs in by_dir.items():
        vids = [f for f in fs if '.' + f[0].rsplit('.', 1)[-1].lower() in video_ext]
        if not vids:
            continue
        main = max(vids, key=lambda f: f[1])
        units.append({'name': d.rsplit('/', 1)[-1], 'main': main[0].rsplit('/', 1)[-1],
                      'gb': round(sum(f[1] for f in fs) / gb_div, 2), 'form': '', 'path': d})
    return units


# ================= A3 REMUX × 原盘（口径逐字复现 cross_screen.py，2026-11-08 当轮） =================
# REMUX 侧 = REMUX 区 + 整夹合集区单元；原盘侧 = 原盘区按片聚成「原盘最佳份」（Emby 实测分辨率优先，其次文件名档位）。
# A 原盘 UHD × REMUX 低档 / B 双 UHD / C 双 1080 → REMUX 那份多余；A2 原盘 1080 × REMUX 更低；
# D1 REMUX 档未知 × 原盘 UHD / D2 原盘档未知 / D3 其他组合 → 人工确认；E REMUX 更高档 → 不处理。
# 注意：这里的 keyof 是 cross_screen.py 自己的一版（和上面 A1 的 keyof v3 不同），照原文保留。
BAD_S = r'(原盘|字幕|国语|国配|简繁|双语|特效|菜单|修改|新增|按钮|花絮|中字|原生|全景声|次世代|公映|台配|粤语|导评|双格式|架构|版本|标准收藏|传媒|国版|美版|欧版|日版|港版|台版|韩版|法版|德版|意版|英版|蓝光|修复|重制|剪辑|加长|终极|限量|独家|系列|合集|全集|三部曲|二部曲|文件|文件夹)'
AUTH_S = r'(至尊宝|雅典娜|碟影|殿堂级|老K|老k)'


def _yearof_s(s):
    m = re.search(r'(19|20)\d{2}', s or '')
    return m.group(0) if m else ''


def keyof_s(name):
    s = name or ''
    s = re.sub(r'@\S+', '', s)
    s = re.sub(r'\.(iso|mkv|mp4|m2ts|ts|avi)$', '', s, flags=re.I)
    s = re.sub(r'\[\d+(\.\d+)?\s*[GT]B?\]', '', s)
    s = re.sub(r'[\{\}\[\]]', ' ', s)
    y = _yearof_s(s)
    cjk = re.findall(r'[一-鿿㐀-䶿][一-鿿㐀-䶿\w ·：:、，]{1,30}', s)
    cjk = [c.strip(' ·：:、，') for c in cjk]
    cjk = [c for c in cjk if len(re.sub(r'[\s·：:、，]', '', c)) >= 2 and not re.search(BAD_S, c) and not re.fullmatch(AUTH_S, c.strip())]
    if cjk:
        return (re.sub(r'[\s·：:、，]+', '', cjk[0]).lower(), y)
    s2 = re.sub(r'(?i)\b(2160p|1080p|720p|4k|uhd|ultra hd|remux|blu-?ray|bd|iso|diy|web-?dl|hdtv|x264|x265|h\.?264|h\.?265|hevc|avc|dts|truehd|atmos|ddp?5\.1|aac|flac|hdr10?\+?|dv|dolby|vision|extended|remastered|complete|repack|v\d)\b', '', s)
    return (re.sub(r'[\s\.\-_·：:、，]+', '', s2).lower(), y)


def _tier_s(name, vh=None):
    if vh:
        return 'U' if vh >= 1600 else ('H' if vh >= 900 else 'S')
    s = name or ''
    if re.search(r'(?i)2160p|\buhd\b|ultra hd', s):
        return 'U'
    if re.search(r'(?i)1080p', s):
        return 'H'
    if re.search(r'(?i)720p|480p|hdtv', s):
        return 'S'
    return '?'


TIER_RANK_S = {'U': 3, 'H': 2, 'S': 1, '?': 0}


def remux_tier(u):
    s = (u['main'] or '') + ' ' + (u['title'] or '')
    if re.search(r'(?i)2160p', s):
        return 'U'
    if re.search(r'(?i)1080p', s):
        return 'H'
    if re.search(r'(?i)720p|480p|hdtv|web-?dl|webrip', s):
        return 'S'
    return '?'


def yuanpan_films(units, files, meas, sub_of):
    """units: [{path,name,kind,totGB}]；files: [{path,GB}]；meas: {原盘路径: 实测短边}。返回 {keyof_s: 原盘最佳份}。"""
    movies = []
    un_by_path = {u['path']: u for u in units}
    byfolder = defaultdict(list)
    for f in files:
        if '/BDMV/' in f['path']:
            continue
        byfolder[f['path'].rsplit('/', 1)[0]].append(f)
    for u in units:
        if u['kind'] == 'BDMV':
            movies.append(dict(name=u['name'], sub=sub_of(u['path']), kind='BDMV', GB=u['totGB'], path=u['path'], main=u['path']))
    for folder, fs in byfolder.items():
        fu = un_by_path.get(folder)
        clusters = defaultdict(list)
        for f in fs:
            clusters[keyof_s(f['path'].rsplit('/', 1)[-1])].append(f)
        sub = sub_of(folder + '/x')
        if len(clusters) <= 1:
            main = max(fs, key=lambda x: x['GB'])
            kind = 'ISO' if main['path'].lower().endswith('.iso') else 'FILE'
            movies.append(dict(name=folder.rsplit('/', 1)[-1], sub=sub, kind=kind,
                               GB=fu['totGB'] if fu else sum(x['GB'] for x in fs), path=folder, main=main['path']))
        else:
            for ck, cfs in clusters.items():
                for f in cfs:
                    kind = 'ISO' if f['path'].lower().endswith('.iso') else 'FILE'
                    movies.append(dict(name=f['path'].rsplit('/', 1)[-1].rsplit('.', 1)[0], sub=sub, kind=kind,
                                       GB=f['GB'], path=f['path'], main=f['path']))
    best = {}
    for m in movies:
        m['tier'] = _tier_s(m['name'], meas.get(m['main']))
        k = keyof_s(m['name'])
        if not k[0] or len(k[0]) < 2:
            continue
        cur = best.get(k)
        if cur is None or TIER_RANK_S[m['tier']] > TIER_RANK_S[cur['tier']] or (m['tier'] == cur['tier'] and m['GB'] > cur['GB']):
            best[k] = m
    return best


A3_CLASS = {'A': 'A-真低质(原盘UHD×REMUX低档)', 'B': 'B-同档冗余(双UHD)', 'C': 'C-同内容冗余(双1080)',
            'D1': 'D1-待定(REMUX档位未知×原盘UHD)', 'D2': 'D2-待定(原盘档位未知)', 'D3': 'D3-待定(其他组合)',
            'E': 'E-REMUX更高档(不处理)', 'A2': 'A2-低质(原盘1080×REMUX更低)'}


def remux_x_yuanpan(remux_units, best):
    """remux_units: [{title, main, path, tgb}]。返回 [(cls, u, 原盘最佳份)]，cls 用短码。"""
    out = []
    for u in remux_units:
        yp_m = best.get(keyof_s(u['title']))
        if yp_m is None:
            continue
        rt, yt = remux_tier(u), yp_m['tier']
        if yt == 'U' and rt in ('H', 'S'):
            cls = 'A'
        elif yt == 'U' and rt == 'U':
            cls = 'B'
        elif yt == 'H' and rt == 'H':
            cls = 'C'
        elif yt == 'U' and rt == '?':
            cls = 'D1'
        elif yt == '?':
            cls = 'D2'
        elif yt == 'H' and rt == 'U':
            cls = 'E'
        elif yt == 'H' and rt == 'S':
            cls = 'A2'
        else:
            cls = 'D3'
        u['tier'] = rt
        out.append((cls, u, yp_m))
    return out
