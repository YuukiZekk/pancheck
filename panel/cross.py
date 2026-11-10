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
