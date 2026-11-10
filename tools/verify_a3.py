"""A3 对差：REMUX × 原盘交叉（cross_screen.py 口径），用数据包原始输入跑面板模块 panel.cross。
用法：python tools/verify_a3.py <面板目录> <A3-数据包目录>
期望：1,395 对，A 11 · B 40 · C 63 · D1 244 · D2 970 · D3 62 · E 5，逐对（分类 + REMUX 路径 + 原盘路径）一致。"""
import csv, os, sys
from collections import Counter
APP, PKG = sys.argv[1:3]
sys.path.insert(0, APP)
from panel import cross
J = lambda n: os.path.join(PKG, n)
remux = []
for fn in ('remux_units.csv', 'remux_units2.csv'):
    for r in csv.DictReader(open(J(fn), encoding='utf-8-sig')):
        remux.append({'title': r['电影'], 'main': r['主视频文件'], 'path': r['路径'], 'tgb': float(r['单元总GB'])})
gone = set()
for line in open(J('moves.tsv'), encoding='utf-8'):
    parts = line.rstrip('\n').split('\t')
    if len(parts) >= 3 and parts[2].startswith('/115/'):
        gone.add(parts[2])
for fn in ('moves2.txt', 'moves3.txt', 'moves4all.txt'):
    for line in open(J(fn), encoding='utf-8'):
        if line.strip():
            gone.add(line.strip().split('\t')[0])
gone.add('/115/01-好康的/01-电影REMUX/『电影』外语/怪兽王哥斯拉 (1956) {tmdb-18983}')   # 当轮脚本里写死的单搬
rem = [u for u in remux if u['path'] not in gone]
units = [dict(r, totGB=float(r['totGB'])) for r in csv.DictReader(open(J('yuanpan_units.csv'), encoding='utf-8'))]
files = [dict(r, GB=float(r['GB'])) for r in csv.DictReader(open(J('yuanpan_files.csv'), encoding='utf-8'))]
meas = {}
for r in csv.DictReader(open(J('emby_yp.csv'), encoding='utf-8')):
    try:
        meas[r['source_path'].replace('/CloudNAS/CloudDrive', '')] = min(int(r['width']), int(r['height']))
    except Exception:
        meas[r['source_path'].replace('/CloudNAS/CloudDrive', '')] = None
PRE = '/115/01-好康的/01-电影原盘'
sub_of = lambda p: p[len(PRE) + 1:].split('/')[0]
best = cross.yuanpan_films(units, files, meas, sub_of)
out = cross.remux_x_yuanpan(rem, best)
mine = Counter((cross.A3_CLASS[c], u['path'], y['path']) for c, u, y in out)
gold = Counter((r['分类'], r['REMUX路径'], r['原盘路径']) for r in csv.DictReader(open(J('A3-金标准交叉逐对.csv'), encoding='utf-8-sig')))
print('REMUX 剩余 %d 单元（全量 %d，已搬 %d）| 原盘片 %d' % (len(rem), len(remux), len(gone), len(best)))
print('面板：', dict(sorted(Counter(c for c, _, _ in out).items())), '共', len(out))
print('金标准：', dict(sorted(Counter(k[0].split('-')[0] for k in gold.elements()).items())), '共', sum(gold.values()))
print('逐对：面板独有 %d | 金标准独有 %d' % (sum((mine - gold).values()), sum((gold - mine).values())))
ok = mine == gold
print('ALL PASS' if ok else 'FAILED')
sys.exit(0 if ok else 1)
