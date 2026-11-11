"""反馈 13 差分报告：同一轮的输入，按修复前 / 修复后两套片名键各算一遍，列出哪些条目变了。

用法（容器里）：
    docker exec sieve-panel python tools/keydiff.py            # 默认用最近一轮跑筛
    docker exec sieve-panel python tools/keydiff.py <run_id>
写出 <run_dir>/keyfix_diff.md 和 keyfix_diff.csv，并在终端打印数字。只读：不改结果、不碰批准。

覆盖：第二刀（逐组列出）、第三刀、纵向、合集×REMUX（条数 + 变动条目）。
同字节重复与 REMUX×主库也用这把键，但要连 Emby / 全区清单，留给修复版真跑后在面板里看。
"""
import csv
import os
import re
import sys
from collections import Counter, defaultdict

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (APP, os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sieve as S                     # noqa: E402
from panel import config as C        # noqa: E402
from panel import cross              # noqa: E402
import legacy_steps                  # noqa: E402  （同在 tools/）


def _title2_legacy(s):
    """修复前的取法：不挖规格短语，直接取最长中文片段（原样保留，只用于对比）。"""
    head = re.split(r'(?i)(2160p|1080p|720p|480p|uhd|remux|blu-?ray|bdrip|web-?dl|hdtv)', s)[0]
    head = S.LEAD.sub('', head)
    cjk = S.CJK.findall(head)
    if cjk:
        longest = max(cjk, key=len)
        return longest if len(longest) >= 2 else ''.join(cjk)
    return re.sub(r'[\s\.\-_]+', ' ', head).strip().lower()


def _set_mode(legacy):
    new_t, new_s = _set_mode.orig
    t, sus = (_title2_legacy, lambda *_a: False) if legacy else (new_t, new_s)
    S._title2, S.title_suspect = t, sus
    cross._title2, cross.title_suspect = t, sus


_set_mode.orig = (S._title2, S.title_suspect)


def _compute(cfg):
    s1 = S.stage1()
    cut1 = {r[1] for r in s1 if r[0] in ('A', 'B')}
    s2A, s2B, held = S.stage2(cut1)
    all2 = s2A + s2B
    emby_tmdb, emby_title = S.load_emby()
    s3A, s3B, lone, popn = S.stage3(s1, all2, emby_tmdb)
    cut_all = cut1 | {r[1] for r in s2A} | {r[1] for r in s3A}
    vert = S.vertical(cut_all, emby_tmdb, emby_title)
    res = {'stats': {}}
    a1 = legacy_steps.cross_heji_remux(cfg, cut_all, res)
    return {
        's2': {r[1]: (r[0], r[3], r[2]) for r in all2}, 's2_held': held,
        's3': {r[1]: (r[0], r[4], r[2]) for r in s3A + s3B}, 's3_lone': len(lone), 's3_pop': popn,
        'vert': {r[1]: (r[0], '', r[2]) for r in vert},
        'a1': {r['path']: (r['cls'], r.get('keep') or '', r['gb']) for r in a1},
    }


def _tally(d):
    return dict(sorted(Counter(v[0] for v in d.values()).items()))


def _reason(old_key, new_c, new_k):
    t = old_key.split('|')[0]
    if not t:
        return '旧键没有片名（同年无片名的全撞在一起）'
    if S.title_suspect(*old_key.split('|', 1)):
        return '旧键的片名是规格短语「%s」' % t
    if new_c != new_k:
        return '挖掉规格短语后两份片名不同'
    return '新键里整组不可信或换了保留份'


def main(argv):
    runs = sorted([d for d in os.listdir(C.RUNS_DIR) if (C.RUNS_DIR / d / 'heji_films.csv').exists()])
    if not runs:
        print('没有找到带输入清单的跑筛结果（%s）' % C.RUNS_DIR)
        return 1
    rid = argv[1] if len(argv) > 1 else runs[-1]
    run_dir = C.RUNS_DIR / rid
    if not (run_dir / 'heji_films.csv').exists():
        print('这一轮没有 heji_films.csv（盘点轮或 CSV 模式）：%s' % run_dir)
        return 1
    cfg = C.load()
    cwd = os.getcwd()
    os.chdir(run_dir)
    try:
        names = {r['路径']: r['片名(文件名)'] for r in csv.DictReader(open('heji_films.csv', encoding='utf-8-sig'))}
        _set_mode(True)
        old = _compute(cfg)
        k_old = {p: S.keyof2(n)[1] for p, n in names.items()}
        _set_mode(False)
        new = _compute(cfg)
        k_new = {p: S.keyof2(n)[1] for p, n in names.items()}
    finally:
        _set_mode(False)
        os.chdir(cwd)

    nm = lambda p: names.get(p) or p.rsplit('/', 1)[-1]
    lines, rows = [], []
    lines.append('# 第二刀片名键修复：差分报告（%s）\n' % rid)
    lines.append('同一轮输入，按修复前 / 修复后两套片名键各算一遍。修复后数字变化是纠错，不是回归'
                 '（第二刀的金标准当年就是这份代码生成的，这类错对从没被独立验过）。\n')
    lines.append('| 模块 | 修复前 | 修复后 |\n|---|---|---|')
    lines.append('| 第二刀 A / B | %s | %s |' % (_tally(old['s2']), _tally(new['s2'])))
    lines.append('| 第二刀 守卫挂起 | %d | %d |' % (old['s2_held'], new['s2_held']))
    lines.append('| 第三刀 A / B | %s | %s |' % (_tally(old['s3']), _tally(new['s3'])))
    lines.append('| 第三刀 人口 / 孤本 | %d / %d | %d / %d |' % (old['s3_pop'], old['s3_lone'], new['s3_pop'], new['s3_lone']))
    lines.append('| 纵向 | %s | %s |' % (_tally(old['vert']), _tally(new['vert'])))
    lines.append('| 合集×REMUX | %s | %s |' % (_tally(old['a1']), _tally(new['a1'])))
    lines.append('')

    # 第二刀：被摘掉的，按原保留份成组列出
    gone = [p for p in old['s2'] if p not in new['s2']]
    groups = defaultdict(list)
    for p in gone:
        groups[old['s2'][p][1]].append(p)
    lines.append('## 第二刀：被摘掉的组（%d 组 / %d 条）\n' % (len(groups), len(gone)))
    why_cnt = Counter()
    for keep, ps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        why = _reason(k_old.get(ps[0], ''), k_new.get(ps[0], ''), k_new.get(keep, ''))
        why_cnt[why.split('「')[0]] += len(ps)
        lines.append('- **撞的键** `%s` —— %s' % (k_old.get(ps[0], ''), why))
        lines.append('  - 原保留份：%s（新键 `%s`）' % (nm(keep), k_new.get(keep, '')))
        for p in ps:
            c, _, gb = old['s2'][p]
            lines.append('  - 候选 %s 类 %.1f GB：%s（新键 `%s`）' % (c, gb, nm(p), k_new.get(p, '')))
            rows.append(['第二刀', '摘掉', c, '', p, keep, '', k_old.get(p, ''), k_new.get(p, ''), why])
    if why_cnt:
        lines.append('\n按原因：' + '；'.join('%s %d 条' % kv for kv in why_cnt.most_common()))

    added = [p for p in new['s2'] if p not in old['s2']]
    changed = [p for p in new['s2'] if p in old['s2'] and new['s2'][p][:2] != old['s2'][p][:2]]
    lines.append('\n## 第二刀：新出现的（%d 条）\n' % len(added))
    lines.append('挖掉规格短语后，同一部片不同规格写法的几份才对上键。逐条给出，请抽查。\n')
    for p in added:
        c, keep, gb = new['s2'][p]
        lines.append('- %s 类 %.1f GB：%s → 保留 %s（键 `%s`）' % (c, gb, nm(p), nm(keep), k_new.get(p, '')))
        rows.append(['第二刀', '新增', '', c, p, '', keep, k_old.get(p, ''), k_new.get(p, ''), ''])
    lines.append('\n## 第二刀：类别或保留份变了的（%d 条）\n' % len(changed))
    for p in changed:
        (oc, ok, _), (nc, nk, _) = old['s2'][p], new['s2'][p]
        lines.append('- %s：%s 类留 %s → %s 类留 %s' % (nm(p), oc, nm(ok), nc, nm(nk)))
        rows.append(['第二刀', '变动', oc, nc, p, ok, nk, k_old.get(p, ''), k_new.get(p, ''), ''])

    for mod, key in (('第三刀', 's3'), ('纵向', 'vert'), ('合集×REMUX', 'a1')):
        o, n = old[key], new[key]
        diff = sorted(set(o) | set(n))
        diff = [p for p in diff if o.get(p, ('', ''))[:2] != n.get(p, ('', ''))[:2]]
        lines.append('\n## %s：有变化的条目（%d 条）\n' % (mod, len(diff)))
        for p in diff[:300]:
            oc, ok = o.get(p, ('—', ''))[:2]
            nc, nk = n.get(p, ('—', ''))[:2]
            lines.append('- %s：%s%s → %s%s' % (nm(p), oc, '（留 %s）' % nm(ok) if ok and ok.startswith('/') else '',
                                              nc, '（留 %s）' % nm(nk) if nk and nk.startswith('/') else ''))
        if len(diff) > 300:
            lines.append('- ……其余 %d 条见 CSV' % (len(diff) - 300))
        for p in diff:
            rows.append([mod, '变动', o.get(p, ('', ''))[0], n.get(p, ('', ''))[0], p,
                         o.get(p, ('', ''))[1], n.get(p, ('', ''))[1], '', '', ''])

    md = run_dir / 'keyfix_diff.md'
    md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    with open(run_dir / 'keyfix_diff.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['模块', '变化', '旧类', '新类', '候选路径', '旧保留份', '新保留份', '旧键', '新键', '原因'])
        w.writerows(rows)
    print('\n'.join(lines[:12]))
    print('第二刀被摘掉 %d 组 / %d 条，新增 %d 条，变动 %d 条' % (len(groups), len(gone), len(added), len(changed)))
    print('报告：%s\n明细：%s' % (md, run_dir / 'keyfix_diff.csv'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
