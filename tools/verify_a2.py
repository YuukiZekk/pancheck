"""A2 对差（两层），全部用面板自己的模块和内置词跑，不在这里另写口径。
用法：python tools/verify_a2.py <面板目录> <A2-数据包目录> [<A1-数据包目录>]
  第一层：yuanpan_files / yuanpan_units → 可移与 moves5.txt 逐条一致；313 条文件级确认重复全部成组；Sample 不成组。
  第二层：隐藏重复-同字节数.csv（3,381 组，大小口径）→ 按保留档排除后 = 保护区外 1,176 组逐组一致；
          保留份（build16b 计分）对审计表。已搬集合取 A1 包的 moves*；A2 包里若放了 moves15.txt 一并扣除。
          缺 moves15 时，差异只允许出现在「成员在审计表里完全没出现（第 15 批已搬）」的组。"""
import csv, glob, os, sys
from collections import Counter
APP, PKG = sys.argv[1:3]
A1 = sys.argv[3] if len(sys.argv) > 3 else ''
sys.path.insert(0, APP)
os.environ.setdefault('SIEVE_DATA', os.path.join(PKG, '_tmp_data'))
sys.path.insert(0, APP)
import sieve
from panel import config as C, cross, dupes, sources as S
B115 = '/115/01-好康的/'
cfg = C.normalize({'zones': {'heji': [B115 + '01-电影合集'], 'yuanpan': [B115 + '01-电影原盘'],
                                   'remux': [B115 + '01-电影REMUX'], 'pack': [B115 + '10-合集']}})
J = lambda n: os.path.join(PKG, n)
fails = []

# ---------------- 第一层 ----------------
units = list(csv.DictReader(open(J('yuanpan_units.csv'), encoding='utf-8')))
pack_size = Counter()
for u in units:
    pack_size[u['sub']] += float(u['totGB'])
items = [{'path': r['path'], 'size': r['GB'], 'kind': 'file'} for r in csv.DictReader(open(J('yuanpan_files.csv'), encoding='utf-8'))
         if '/BDMV/' not in r['path'].upper() and '/VIDEO_TS/' not in r['path'].upper()]
items += [{'path': u['path'], 'size': u['totGB'], 'kind': 'disc'} for u in units if u['kind'] == 'BDMV']
ud = S.film_unit_dirs([x['path'] for x in items])
keep_tier = list(cfg['protect_names']) + list(cfg['keep_first_names'])
is_top = lambda p: bool(S.protect_hit(p, keep_tier, ud) or S.listpack_hit(p, cfg['listpack_names'], cfg))
moves, all_top = dupes.plan(items, is_top, lambda p: p.split('/')[4], pack_size)
m5 = {l.strip() for l in open(J('moves5.txt'), encoding='utf-8') if l.strip()}
mine = {x['path'] for x, _, _ in moves}
grouped = {x['path'] for g in dupes.groups(items) for x in g}
review = list(csv.DictReader(open(J('原盘精确重复复核.csv'), encoding='utf-8-sig')))
conf = [r['路径'] for r in review if r['复核结论'] == '确认重复']
print('【第一层】重复组 %d | 全在保留档不动 %d | 可移 %d' % (len(dupes.groups(items)), all_top, len(mine)))
print('  moves5 对差：面板独有 %d | moves5 独有 %d' % (len(mine - m5), len(m5 - mine)))
print('  确认重复（文件级）成组：%d / %d；Sample 成组：%s' % (sum(p in grouped for p in conf), len(conf),
      any('sample' in p.rsplit('/', 1)[-1].lower() for p in grouped)))
if mine != m5 or not all(p in grouped for p in conf):
    fails.append('第一层')

# ---------------- 第二层 ----------------
G = list(csv.DictReader(open(J('隐藏重复-同字节数.csv'), encoding='utf-8-sig')))
B = {r['精确字节数'] for r in csv.DictReader(open(J('隐藏重复-保护区外1176.csv'), encoding='utf-8-sig'))}
tier = list(cfg['protect_names']) + list(cfg['keep_first_names']) + list(sieve.LISTPACK)
allp = [p for r in G for p in r['路径组'].split(' || ')]
ud2 = S.film_unit_dirs(allp)
zone = lambda p: 'yuanpan' if '/01-电影原盘/' in p else 'remux' if '/01-电影REMUX/' in p else 'heji'
groups = []
for r in G:
    groups.append([{'path': p, 'zone': zone(p), 'root_depth': 3, 'key': r['精确字节数'],
                    'tier': bool(S.protect_hit(p, tier, ud2)), 'guard': bool(S.guard_hit(cfg, p, ud2)),
                    '_g': r['精确字节数']} for p in r['路径组'].split(' || ')])
free = {ms[0]['_g'] for ms in groups if not any(x['tier'] for x in ms)}
print('【第二层】3,381 组 → 不沾保留档 %d 组 | 金标准 1,176 | 面板独有 %d | 金标准独有 %d' % (len(free), len(free - B), len(B - free)))
if free != B:
    fails.append('第二层分组')
moved = set()
srcs = ([os.path.join(A1, 'moves.tsv')] + sorted(glob.glob(os.path.join(A1, 'moves*.txt')))) if A1 else []
srcs += [J('moves15.txt')] if os.path.isfile(J('moves15.txt')) else []
for fn in srcs:
    for ln in open(fn, encoding='utf-8', errors='ignore'):
        c = [p.strip() for p in ln.rstrip('\n').split('\t') if p.strip().startswith('/115/')]
        if c:
            moved.add(max(c, key=len))
def gone(p):
    while p:
        if p in moved:
            return True
        p = p.rsplit('/', 1)[0] if '/' in p else ''
    return False
EXCL = list(sieve.EXCL)
def held(x):
    p = x['path']
    if '/BDMV/' in p: return '碟内文件'
    if any(w in p for w in EXCL): return '另议包'
    if sieve.EP.search(p.rsplit('/', 1)[1]): return '剧集标记'
    return ''
mv, st = dupes.plan_hidden([ms for ms in groups if ms[0]['_g'] in B], held, gone)
mine2 = {(k['path'], x['path']) for x, k in mv}
gold = {(r['保留份路径'], r['搬运份路径']) for r in csv.DictReader(open(J('同字节重复-保留与搬运审计.csv'), encoding='utf-8-sig'))}
inaudit = {p for pair in gold for p in pair}
diff_groups = {x['_g'] for x, k in mv if (k['path'], x['path']) not in gold} | \
              {ms[0]['_g'] for ms in groups for x in ms if any(x['path'] == q for _, q in gold - mine2)}
unexplained = [g for g in diff_groups if not any(not gone(x['path']) and not held(x) and x['path'] not in inaudit
                                                  for ms in groups if ms[0]['_g'] == g for x in ms)]
print('  已搬集合 %d 条（%s）| 判定 %d 组、搁置 %d 组 | 搬运 面板 %d / 审计 %d | 面板独有 %d | 审计独有 %d'
      % (len(moved), 'A1 包 moves*' + (' + moves15' if os.path.isfile(J('moves15.txt')) else '，缺 moves15'),
         st['decided'], st['shelved'], len(mine2), len(gold), len(mine2 - gold), len(gold - mine2)))
print('  有差异的组 %d 个，其中不能用「成员在审计表里完全没出现（第 15 批已搬）」解释的：%d 个' % (len(diff_groups), len(unexplained)))
if unexplained or (os.path.isfile(J('moves15.txt')) and mine2 != gold):
    fails.append('第二层保留份')
print('ALL PASS' if not fails else 'FAILED: %s' % fails)
sys.exit(1 if fails else 0)
