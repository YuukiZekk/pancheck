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
