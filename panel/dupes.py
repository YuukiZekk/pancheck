"""A2 原盘区完全重复（第一层：同片同规格精确重复）。面板层模块，不改 sieve.py。

口径（由 2026-11-08 复核表 404 条 + moves5 的 84 条反推、逐条验证）：
  - 判定对象：原盘区里**同名同大小**、分属不同父文件夹的文件（ISO 等单文件）；
    盘片夹（BDMV/VIDEO_TS）整夹算一份，按「夹名 + 总大小」比。
  - 通用名（Sample/样片/预告）不判重复：各片自带的样片同名同大小只是巧合。
  - 保留规则（用户 2026-11-08 拍板）：
      ① 组里有在「保护档」的份（保护目录、榜单包 + 保留优先目录，如已刮削大包）→ 保护档的都留，档外的都算多余；
      ② 全在普通区 → 留最大的包（原盘区第一级目录按总体积）里那份，其余算多余。
    组里全在保护档 → 一份都不动（只计数，不出清单）。
"""
import os
import re
from collections import defaultdict

GENERIC = re.compile(r'(?i)^(sample|样片|预告|trailer)\b')


def groups(items):
    """items: [{path, size, kind: 'file'|'disc'}]。返回 [[item, ...]]：同名同大小、≥2 个不同父文件夹。"""
    g = defaultdict(list)
    for it in items:
        name = it['path'].rsplit('/', 1)[-1]
        if GENERIC.match(os.path.splitext(name)[0]):
            continue
        g[(it['kind'], name, it['size'])].append(it)
    return [v for v in g.values() if len({x['path'].rsplit('/', 1)[0] for x in v}) >= 2]


def plan(items, is_top, pack_of, pack_size):
    """返回 (moves, kept_groups)：moves = [(多余份 item, 保留份 item, 理由)]；kept_groups = 全在保护档、不动的组数。"""
    moves, all_top = [], 0
    for grp in groups(items):
        tops = [x for x in grp if is_top(x['path'])]
        if tops and len(tops) == len(grp):
            all_top += 1
            continue
        if tops:
            keep = tops[0]
            why = 'top'
        else:
            keep = max(grp, key=lambda x: (pack_size.get(pack_of(x['path']), 0), x['path']))
            why = 'pack'
        for x in grp:
            if x is keep or (why == 'top' and x in tops):
                continue
            moves.append((x, keep, why))
    return moves, all_top


# ================= 第二层：同字节重复（隐藏重复登记册） =================
# 口径 = cross_remux.py TASK 2 分组 + build16b.py 保留份计分（用户 2026-11-10 拍板），面板版按 Sha1 分组（无 Sha1 时退回字节数）。
#   - 同一指纹、≥2 份、不全在同一个夹、且不全是同一身份（keyof v3 相同的是「已知重复」，归别的模块）
#   - 组里只要有一份沾保留档（保护目录、内置保留档词、内核榜单包）→ 整组不动
#   - 暂缓成员（碟内文件、另议包、剧集标记）不搬也不当保留份；剩不到 2 份的组整组搁置
#   - 落在保护/榜单名下的成员（守卫会拦）可以当保留份，但不搬
#   - 保留份 = 计分最低：裸名 +100、文件名规格词每个 −1、路径带「刮削」−50、带 {tmdb} −40、区域 ×10（原盘 0 / REMUX 1 / 其他 2）、
#     直接散放在分区或包根 +5；同分按父路径
SPEC = re.compile(r'(?i)(2160p|1080p|1080i|720p|480p|\buhd\b|4k|blu-?ray|remux|bdrip|web-?dl|webrip|hdtv|x264|x265|h\.?264|h\.?265|hevc|avc|dts|truehd|atmos|ddp|aac|flac|lpcm|hdr|dolby|\bdv\b|diy|字幕|国配|国语|粤语|特效|双语|简繁|中字|花絮|加长|@)')
AREA = {'yuanpan': 0, 'remux': 1}


def keeper_rank(it):
    p = it['path']
    parent, name = p.rsplit('/', 1)
    t = len(set(m.group(0).lower() for m in SPEC.finditer(name)))
    s = (100 if t == 0 else 0) - t
    if '刮削' in p:
        s -= 50
    low = p.lower()
    if '{tmdb' in low or 'tmdbid' in low:
        s -= 40
    s += AREA.get(it['zone'], 2) * 10
    if parent.count('/') <= it['root_depth'] + 1:
        s += 5
    return (s, parent)


def hidden_groups(items, keyof):
    """items: [{path, key(指纹), ...}]。返回 TASK 2 口径的隐藏重复组。"""
    g = defaultdict(list)
    for it in items:
        if it['key']:
            g[it['key']].append(it)
    out = []
    for ms in g.values():
        if len(ms) < 2:
            continue
        if len({keyof(x['path'].rsplit('/', 1)[1]) for x in ms}) == 1:
            continue                                   # 同身份：已知重复，归别的模块
        if len({x['path'].rsplit('/', 1)[0] for x in ms}) == 1:
            continue                                   # 同一个夹里的：不算跨夹重复证据
        out.append(ms)
    return out


def plan_hidden(groups, held_reason, gone=lambda p: False):
    """返回 (moves[(多余份, 保留份)], stats)。"""
    moves, st = [], {'groups': len(groups), 'tier': 0, 'shelved': 0, 'decided': 0, 'held': {}}
    for ms in groups:
        if any(x['tier'] for x in ms):
            st['tier'] += 1
            continue
        members = [x for x in ms if not gone(x['path'])]
        normal = []
        for x in members:
            r = held_reason(x)
            if r:
                st['held'][r] = st['held'].get(r, 0) + 1
            else:
                normal.append(x)
        if len(normal) < 2:
            st['shelved'] += 1
            continue
        st['decided'] += 1
        keep = min(normal, key=keeper_rank)
        for x in normal:
            if x is keep:
                continue
            if x.get('guard'):                         # 落在保护/榜单名下的：可以当保留份，但不搬（守卫会整批拒绝）
                st['held']['保护/榜单目录'] = st['held'].get('保护/榜单目录', 0) + 1
                continue
            moves.append((x, keep))
    return moves, st
