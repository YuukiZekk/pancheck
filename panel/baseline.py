"""从一轮扫描结果直接打印基线表（Markdown），重跑后贴进 docs/基线.md 就行，不用手数。

用法：
    docker exec sieve-panel python -m panel.baseline              # 最近一轮完整扫描
    docker exec sieve-panel python -m panel.baseline <轮次号>
    python -m panel.baseline <轮次目录>                            # 本地：直接给目录
只读：只看 result.json / rows.json，不改结果。
"""
import json
import os
import sys
import time
from collections import Counter, defaultdict

from . import config as C

GROUP_TAGS = ['与原盘重复', '合集内重复', '原盘区内重复', '涉及 REMUX / 整夹合集', '小文件低质', '特效字幕版', '多碟装']
MAIN_CLS = [('入库提醒', '缺口'), ('洗版提醒', '洗版'), ('库内已有同档+', '主库已有同档'), ('疑似同片(仅标注)', '疑似')]
B7_CLS = ['A', 'D1', 'D2', 'W']           # REMUX×主库（结果里同属「主库对比」，按分类区分）


def find_run(arg=None):
    """→ 轮次目录。arg 可以是目录、轮次号，或不给（最近一轮完整扫描）。"""
    if arg and os.path.isdir(arg):
        return arg
    runs = []
    if C.RUNS_DIR.exists():
        for d in C.RUNS_DIR.iterdir():
            f = d / 'result.json'
            if not f.exists():
                continue
            try:
                r = json.loads(f.read_text(encoding='utf-8'))
            except ValueError:
                continue
            if r.get('mode') == 'full' and (not arg or d.name == arg):
                runs.append((r.get('finished') or 0, str(d)))
    if not runs:
        raise SystemExit('没找到%s的完整扫描结果（数据目录 %s）' % ('轮次 ' + arg if arg else '任何一轮', C.RUNS_DIR))
    return max(runs)[1]


def _n(x):
    return '{:,}'.format(x)


def _gb(x):
    return '{:,.0f} GB'.format(x) if x >= 10 else '{:,.1f} GB'.format(x)


def table(run_dir):
    res = json.load(open(os.path.join(run_dir, 'result.json'), encoding='utf-8'))
    rows = json.load(open(os.path.join(run_dir, 'rows.json'), encoding='utf-8'))
    st = res.get('stats') or {}
    g = st.get('groups') or res.get('groups') or {}
    cnt, gbs = Counter(), defaultdict(float)

    def add(key, r):
        cnt[key] += 1
        gbs[key] += r.get('gb') or 0

    for r in rows:
        stage, cls, b = r.get('stage'), r.get('cls'), r.get('bucket')
        if stage == '重复副本':
            if cls == 'L1':
                add('L1', r)
            elif cls == 'SHA':
                add('SHA', r)
            else:
                add('dup:' + b, r)
                if b == '可切':
                    for t in r.get('tags') or ():
                        add('tag:' + t, r)
        elif stage == '主库对比':
            add(('b7:' if cls in B7_CLS else 'main:') + cls, r)
        else:
            add('stage:' + stage, r)

    def cell(*keys):
        return ' / '.join('%s（%s）' % (_n(cnt[k]), _gb(gbs[k])) if cnt[k] else '0' for k in keys)

    fin = res.get('finished')
    src = res.get('source') or {}
    cur = C.load()
    head = ['轮次 %s · 完成于 %s · 配置指纹 %s%s' % (
        os.path.basename(os.path.normpath(run_dir)), time.strftime('%Y-%m-%d %H:%M', time.localtime(fin)) if fin else '—',
        res.get('fingerprint') or '—', '（和当前设置不同：结果已过期）' if res.get('fingerprint') != C.fingerprint(cur) else '')]
    if src.get('kind') == 'cache' and src.get('time_max'):
        head.append('CD2 缓存快照截至 %s' % time.strftime('%Y-%m-%d %H:%M', time.localtime(src['time_max'])))
    if res.get('rejected') or res.get('protect_violations'):
        head.append('**注意：这轮被保护守卫整批拒绝（%d 条可清理落在没勾的目录 / 保护区里）**' % len(res.get('protect_violations') or ()))

    pop = ' / '.join('%s %s' % (lbl, _n((st.get(z) or {}).get('count', 0)))
                     for z, lbl in (('heji', '合集'), ('yuanpan', '原盘'), ('remux', 'REMUX'), ('pack', '整夹')))
    skipped = sum((st.get('protected_skipped') or {}).values())
    unl = sum((v or {}).get('count', 0) for v in ((src.get('unlisted') or {}).values()))
    lines = ['| 项 | 数 |', '|---|---|',
             '| 扫描人口（条） %s | %s |' % ('合集 / 原盘 / REMUX / 整夹', pop),
             '| 没勾 / 保护剔除 · 查重区跳过 · CD2 没打开过的目录 | %s · %s · %s |' % (
                 _n(skipped), _n(st.get('quarantine_skipped') or 0), _n(unl)),
             '| 副本总数 / 归成重复组的组数 / 挂起组 | %s / %s / %s |' % (
                 _n(g.get('copies', 0)), _n(g.get('groups', 0)), _n(g.get('held_groups', 0))),
             '| 重复副本 可清理 / 版本对 / 需人工确认 / 不碰 | %s |' % cell('dup:可切', 'dup:版本型', 'dup:待定', 'dup:不动'),
             '| 其中 %s | %s |' % (' / '.join(t.replace(' / ', '或') for t in GROUP_TAGS), cell(*['tag:' + t for t in GROUP_TAGS])),
             '| 原盘同名同大小 / 同字节 | %s |' % cell('L1', 'SHA'),
             '| 主库对比 %s | %s |' % (' / '.join(t for _, t in MAIN_CLS), cell(*['main:' + c for c, _ in MAIN_CLS])),
             '| REMUX×主库 A / D1 / D2 / 提醒 | %s |' % cell(*['b7:' + c for c in B7_CLS]),
             '| 孤本 | %s |' % cell('stage:孤本'),
             '| 剧集分流 | %s |' % cell('stage:剧集分流')]
    other = sorted(k for k in cnt if k.startswith('stage:') and k not in ('stage:孤本', 'stage:剧集分流'))
    other += sorted(k for k in cnt if (k.startswith('main:') and k[5:] not in dict(MAIN_CLS))
                    or (k.startswith('dup:') and k[4:] not in ('可切', '版本型', '待定', '不动')))
    for k in other:
        lines.append('| %s | %s |' % (k.split(':', 1)[1], cell(k)))
    total = Counter(r.get('bucket') for r in rows)
    lines.append('| 合计 各分类 | %s |' % ' · '.join('%s %s' % (b, _n(v)) for b, v in total.most_common()))
    return '\n'.join(head) + '\n\n' + '\n'.join(lines)


def main(argv):
    print(table(find_run(argv[1] if len(argv) > 1 else None)))


if __name__ == '__main__':
    main(sys.argv)
