"""A2 第一层对差：用数据包原始输入（yuanpan_files.csv / yuanpan_units.csv）跑面板模块 panel.dupes，
对 moves5.txt（84 条可移）和复核表 315 条「确认重复」。
用法：python tools/verify_a2.py <面板目录> <A2-数据包目录>
期望：可移 84 条与 moves5 逐条一致；313 条文件级确认重复全部落在模块的重复组里；Sample 不成组。"""
import csv, os, sys
from collections import Counter
APP, PKG = sys.argv[1:3]
sys.path.insert(0, APP)
from panel import dupes
os.chdir(PKG)
# 当轮保护档：01/02-系列、11-出品公司（保护目录）+ 已刮削大包（保留优先，与出品公司同属一档）
TOP = ('01-系列电影合集', '02-系列电影合集', '11-出品公司', '蓝光原盘已刮削完成')
pack_of = lambda p: p.split('/')[4]
is_top = lambda p: any(pack_of(p).startswith(t) for t in TOP)
units = list(csv.DictReader(open('yuanpan_units.csv', encoding='utf-8')))
pack_size = Counter()
for u in units:
    pack_size[u['sub']] += float(u['totGB'])
items = []
for r in csv.DictReader(open('yuanpan_files.csv', encoding='utf-8')):
    up = r['path'].upper()
    if '/BDMV/' in up or '/VIDEO_TS/' in up:          # 碟内流文件：面板按整张盘算，不单列
        continue
    items.append({'path': r['path'], 'size': r['GB'], 'kind': 'file'})
items += [{'path': u['path'], 'size': u['totGB'], 'kind': 'disc'} for u in units if u['kind'] == 'BDMV']
moves, all_top = dupes.plan(items, is_top, pack_of, pack_size)
m5 = {l.strip() for l in open('moves5.txt', encoding='utf-8') if l.strip()}
mine = {x['path'] for x, _, _ in moves}
grouped = {x['path'] for g in dupes.groups(items) for x in g}
review = list(csv.DictReader(open('原盘精确重复复核.csv', encoding='utf-8-sig')))
conf = [r['路径'] for r in review if r['复核结论'] == '确认重复']
sample_rows = [r for r in review if r['复核结论'] == '待核-通用名']
print('重复组', len(dupes.groups(items)), '| 全在保护档不动', all_top, '| 可移', len(mine))
print('moves5 对差：面板独有', len(mine - m5), '| moves5 独有', len(m5 - mine))
print('确认重复（文件级）落在重复组里：%d / %d' % (sum(p in grouped for p in conf), len(conf)))
print('Sample 成组：', any('sample' in p.rsplit('/', 1)[-1].lower() for p in grouped), '（复核表 hold %d 条）' % len(sample_rows))
ok = mine == m5 and all(p in grouped for p in conf)
print('ALL PASS' if ok else 'FAILED')
sys.exit(0 if ok else 1)
