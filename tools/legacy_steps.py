"""反馈 15 以前的旧流程步骤（合集×REMUX、REMUX×原盘、D1 改判）。

面板的扫描（panel/runner.main）从反馈 15 起不再调用这些——同一部片的所有副本由 panel/groups.py 一次归组判定。
留在这里只给对账 / 差分工具用（tools/keydiff.py）；读写的仍是当前目录下那一轮的 CSV（heji_films.csv、cross_units.csv…）。
"""
import csv
import os
import re
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP not in sys.path:
    sys.path.insert(0, APP)

from panel import config as C, cross, labels as L, sources     # noqa: E402
from panel.runner import GIB, row                              # noqa: E402

CROSS_STAGE = '合集×REMUX'
CROSS_BUCKET = {'A': '可切', 'B': '可切', 'C': '版本型', 'D': '待定', 'E': '待定'}
KIND_NAME = {'D': 'DIY/特效字幕', 'I': '原盘', 'R': 'REMUX', 'O': '普通压制'}

def _tl(t):
    return '%s·%s' % (KIND_NAME[t[0]], L.tier(t[1]))


def cross_heji_remux(cfg, cut_all, result):
    """A1 合集 × REMUX（口径 = cross_remux.py TASK 1）。
    合集侧人口 = heji_films 去榜单包/排除词（内核常量 + 用户追加），再去掉内核三刀已判可清理的
    （当轮那批已搬走；不重复列）。REMUX 单元只当参照。"""
    import sieve
    if not os.path.isfile('cross_units.csv'):
        result['cross'] = {'skipped': '没有 REMUX 区 / 整夹合集单元'}
        return []
    units = list(csv.DictReader(open('cross_units.csv', encoding='utf-8-sig')))
    mk = lambda u: {'pack': u['来源区域'], 'name': u['电影'], 'gb': float(u['单元总GB']), 'form': '',
                    'path': u['路径'], 'main': u['主视频文件']}
    rem = [mk(u) for u in units if u['分区'] == 'remux']
    pk = [mk(u) for u in units if u['分区'] == 'pack']
    if not rem:
        result['cross'] = {'skipped': '没有 REMUX 区单元'}
        return []
    extra = [x for x in cfg['exclude_names'] if x not in C.BUILTIN_EXCLUDE]
    hj, n_cut = [], 0
    for r in csv.DictReader(open('heji_films.csv', encoding='utf-8-sig')):
        p = r['路径']
        if sources.lp_path(p, cfg) or any(e in p for e in sieve.EXCL) or sources.hit_any(p, extra):
            continue
        if p in cut_all:
            n_cut += 1
            continue
        hj.append({'pack': r['大包'], 'name': r['片名(文件名)'], 'gb': float(r['GB']), 'form': r['形态'], 'path': p})
    out = []
    for cls, src, x, ref in cross.heji_x_remux(hj, pk, rem):
        xg = x['gb'] if src == '01-电影合集' else x['gb'] * 1e9 / GIB      # 单元体积是 1000 进制，显示换回 115 口径
        rg = ref['gb'] * 1e9 / GIB
        xt, rt = _tl(x['tier']), _tl(ref['tier'])
        if cls == 'D':
            out.append(row(CROSS_STAGE, cls, '待定', ref['path'], rg, keep=x['path'], side='REMUX',
                           basis='合集那份更好（%s），REMUX 区这份（%s）待议' % (xt, rt)))
            continue
        basis = {'A': '档低于 REMUX 区那份：这份 %s，REMUX 区 %s',
                 'B': '和 REMUX 区那份同档：这份 %s，REMUX 区 %s',
                 'C': '一份是 DIY/特效字幕版，两份都留：这份 %s，REMUX 区 %s',
                 'E': '分辨率推断不出，没法比档：这份 %s，REMUX 区 %s'}[cls] % (xt, rt)
        out.append(row(CROSS_STAGE, cls, CROSS_BUCKET[cls], x['path'], xg, keep=ref['path'], basis=basis,
                       side='合集' if src == '01-电影合集' else '整夹合集'))
    result['cross'] = {'heji': len(hj), 'pack_units': len(pk), 'remux_units': len(rem),
                       'skipped_cut': n_cut, 'pairs': len(out)}
    return out


A3_STAGE = 'REMUX×原盘'
A3_BUCKET = {'A': '可切', 'B': '可切', 'C': '可切', 'A2': '可切', 'D1': '待定', 'D2': '待定', 'D3': '待定',
             'D1U': '可切', 'D1H': '可切', 'D1N': '可切'}
A3_DESC = {'A': '原盘区那份是 4K，这份 REMUX 档更低', 'B': '两边都是 4K，留原盘', 'C': '两边都是 1080p，留原盘',
           'A2': '原盘区那份 1080p，这份 REMUX 更低', 'D1': '这份 REMUX 画质看不出、原盘区是 4K，请确认',
           'D2': '原盘区那份画质看不出，请确认', 'D3': '画质组合不好判断，请确认',
           'D1U': '原盘 4K 已确认，这份 REMUX 文件名写的也是 4K（同档），留原盘',
           'D1H': '原盘 4K 已确认，这份 REMUX 文件名写的是 1080p（低一档），留原盘',
           'D1N': '原盘 4K 已确认，这份 REMUX 文件名没标分辨率，留原盘'}


def d1_subclass(u, y):
    """D1 改判（用户 2026-11-11）：原盘那边是已确认的 4K（实测或文件名写明，不含体积推断）→ 可清理，
    按 REMUX 主文件名写的分辨率分子类；REMUX 不做体积推断。原盘 4K 只是推断的，仍留 D1 人工确认。"""
    if y['tier'] != 'U':
        return 'D1'
    name = (u.get('main') or '').rsplit('/', 1)[-1]
    if cross.U_NAME.search(name):
        return 'D1U'
    if re.search(r'(?i)1080[pi]', name):
        return 'D1H'
    return 'D1N'


def remux_x_yuanpan(cfg, rows, result):
    """A3 REMUX × 原盘（口径 = cross_screen.py）。REMUX 侧 = REMUX 区 + 整夹合集区单元；原盘那份只当参照。
    单元里已有文件被前面模块判可清理的，整单元跳过（当轮靠「已搬走」排除）。"""
    if not (os.path.isfile('cross_units.csv') and os.path.isfile('yuanpan_units.csv')):
        result['remux_x_yp'] = {'skipped': '没有 REMUX / 原盘单元清单'}
        return []
    cut = {r['path'] for r in rows if r['bucket'] == '可切'}
    touched = set(cut)
    for c in cut:                                   # 被判可清理条目的所有上层目录
        while '/' in c.strip('/'):
            c = c.rsplit('/', 1)[0]
            touched.add(c)
    rem, skipped = [], 0
    for u in csv.DictReader(open('cross_units.csv', encoding='utf-8-sig')):
        p = u['路径']
        if p in touched:
            skipped += 1
            continue
        rem.append({'title': u['电影'], 'main': u['主视频文件'], 'path': p, 'tgb': float(u['单元总GB'])})
    units = [dict(r, totGB=float(r['totGB'])) for r in csv.DictReader(open('yuanpan_units.csv', encoding='utf-8'))]
    files = [dict(r, GB=float(r['GB'])) for r in csv.DictReader(open('yuanpan_files.csv', encoding='utf-8'))]
    meas = {}
    if os.path.isfile('emby_yp.csv'):
        for r in csv.DictReader(open('emby_yp.csv', encoding='utf-8')):
            try:
                meas[r['source_path'].replace('/CloudNAS/CloudDrive', '')] = min(int(r['width']), int(r['height']))
            except (ValueError, KeyError):
                pass
    roots = sorted(cfg['zones']['yuanpan'], key=len, reverse=True)

    def sub_of(p):
        for r in roots:
            if p.startswith(r.rstrip('/') + '/'):
                return p[len(r.rstrip('/')) + 1:].split('/')[0]
        return ''
    best = cross.yuanpan_films(units, files, meas, sub_of, mode='v2')
    out, cnt = [], {}
    for cls, u, y in cross.remux_x_yuanpan(rem, best):
        if cls == 'D1':
            cls = d1_subclass(u, y)
        cnt[cls] = cnt.get(cls, 0) + 1
        if cls == 'E':
            continue
        out.append(row(A3_STAGE, cls, A3_BUCKET[cls], u['path'], u['tgb'] * 1e9 / GIB, keep=y['path'],
                       basis='%s：这份 %s，原盘区 %s' % (A3_DESC[cls], L.tier(u['tier']), L.tier(y['tier']))))
    result['remux_x_yp'] = {'remux_units': len(rem), 'skipped_cut': skipped, 'yuanpan_films': len(best),
                            'pairs': sum(cnt.values()), 'classes': cnt}
    result['stats']['a3_cross'] = result['remux_x_yp']
    return out
