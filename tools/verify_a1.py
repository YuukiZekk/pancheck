"""A1 对差：用数据包原始输入（heji_films.csv、union_units.csv、moves*）跑面板模块 panel.cross，逐对对 A1-金标准逐对明细.csv。
用法：python tools/verify_a1.py <面板目录> <A1-数据包目录>
期望：422 对，A 29 · B 112 · C 29 · D 202 · E 50，面板独有 0、金标准独有 0。"""
import csv, glob, os, sys
from collections import Counter
APP, PKG = sys.argv[1:3]
sys.path.insert(0, APP)
from panel import cross
os.chdir(PKG)
moved = set()
for fn in ['moves.tsv'] + sorted(glob.glob('moves*.txt')):
    for ln in open(fn, encoding='utf-8', errors='ignore'):
        c = [p.strip() for p in ln.rstrip('\n').split('\t') if p.strip().startswith('/115/')]
        if c: moved.add(max(c, key=len))
def is_moved(p):
    if p in moved: return True
    while '/' in p:
        p = p.rsplit('/', 1)[0]
        if p in moved: return True
    return False
BANGDAN = ('豆瓣', 'IMDb', 'IMDB', '戛纳', 'Top 250', 'Top250', 'TOP250'); EXCL = ('金庸', '动漫', 'ADWEB')
hj = [{'pack': r['大包'], 'name': r['片名(文件名)'], 'gb': float(r['GB']), 'form': r['形态'], 'path': r['路径']}
      for r in csv.DictReader(open('heji_films.csv', encoding='utf-8-sig'))
      if not is_moved(r['路径']) and not any(b in r['路径'] for b in BANGDAN) and not any(e in r['路径'] for e in EXCL)]
rx, seen = [], set()
for r in csv.DictReader(open('union_units.csv', encoding='utf-8-sig')):
    p = r['路径']
    if p in seen or is_moved(p): continue
    seen.add(p)
    rx.append({'side': r['来源区域'], 'pack': r['来源区域'], 'name': r['电影'], 'gb': float(r['单元总GB']), 'form': '', 'path': p, 'main': r['主视频文件']})
out = cross.heji_x_remux(hj, [x for x in rx if x['side'] != 'REMUX'], [x for x in rx if x['side'] == 'REMUX'])
mine = Counter((cross.GOLD_LABEL[c], s, x['path'], ref['path']) for c, s, x, ref in out)
gold = Counter((r['分类'], r['来源'], r['合集侧路径'], r['REMUX区路径']) for r in csv.DictReader(open('A1-金标准逐对明细.csv', encoding='utf-8-sig')))
print('population: 合集', len(hj), '| REMUX', sum(x['side'] == 'REMUX' for x in rx), '| 10合集', sum(x['side'] != 'REMUX' for x in rx))
print('panel module :', dict(sorted(Counter(cross.GOLD_LABEL[c][0] for c, *_ in out).items())), 'total', len(out))
print('gold         :', dict(sorted(Counter(k[0][0] for k in gold.elements()).items())), 'total', sum(gold.values()))
print('pair-level: only panel', sum((mine - gold).values()), '| only gold', sum((gold - mine).values()))
sys.exit(0 if mine == gold else 1)
