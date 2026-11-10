"""跑筛子进程：python -m panel.runner <mode> <run_dir>
mode = inventory（只盘点）| full（盘点 + 三刀 + 纵向 + 剧集分流）
进度以 "@@P <json>" 行写 stdout；结果写 run_dir/result.json 与各类 CSV。
内核 sieve.py 原样 import，读写都在 run_dir 里（内核按相对路径读五张 CSV）。
"""
import csv
import json
import os
import sys
import time
from collections import defaultdict

from . import config as C
from . import labels as L
from . import sources

sys.path.insert(0, str(C.APP_DIR))

# 分类 → 面板桶。只有「可切」将来能被批准；待定/孤本永远没有执行入口。
BUCKETS = ['可切', '待定', '版本型', '不动', '孤本', '缺口', '提醒', '剧集分流']
S1 = {'A': '可切', 'B': '可切', 'C': '版本型', 'D1': '待定', 'D2': '待定', 'E': '不动'}
S1_DESC = {'A': '画质低于原盘区那份', 'B': '和原盘区那份画质相同', 'C': '一份是 DIY/特效字幕版，两份都留',
           'D1': '原盘区那份画质未知', 'D2': '这份画质未知', 'E': '这份比原盘区那份画质更高'}


def emit(step, msg, pct=None):
    print('@@P ' + json.dumps({'step': step, 'msg': msg, 'pct': pct, 't': time.time()}, ensure_ascii=False),
          flush=True)


def row(stage, cls, bucket, path, gb, keep='', basis='', **extra):
    return dict(stage=stage, cls=cls, bucket=bucket, path=path, gb=round(float(gb), 2),
                keep=keep, basis=basis, **extra)


def tv_split(cfg, files):
    """混入的剧集（未对金标准，仅出清单），按文件夹展示：
    - 缓存/遍历模式：带集号的文件已在提取层分出（zone='tv'），不在电影人口里；所在夹一律列出；
    - CSV 模式：人口由 CSV 决定，沿用夹级口径——同一目录 ≥2 个带集号文件、且不含系列电影词的才列。"""
    import sieve
    zones = cfg['zones']
    by_folder = defaultdict(list)
    for zone, vp, g, _ in files:
        if zone == 'tv':
            by_folder[('heji', vp.rsplit('/', 1)[0])].append((vp, g, True))
        elif zone in ('heji', 'yuanpan', 'remux'):
            by_folder[(zone, vp.rsplit('/', 1)[0])].append((vp, g, False))
    out = []
    for (zone, folder), fs in sorted(by_folder.items()):
        split = [f for f in fs if f[2]]
        eps = [f for f in fs if f[2] or sieve.EP.search(f[0].rsplit('/', 1)[-1])]
        if not split and len(eps) < 2:
            continue
        roots = [r for r in zones.get(zone, []) if folder.startswith(r)]
        rel = folder[len(roots[0]):] if roots else folder
        keep = sources.hit_any(rel, cfg['tv_keep_names'])
        if keep and not split:
            continue
        if split:
            basis = '%d 个带集号的文件已从电影里分出，不参与比对' % len(split)
            if keep:
                basis += '；路径含「%s」，请确认是不是系列电影' % keep
        else:
            basis = '%d 个文件里 %d 个带集号；夹里的文件若也出现在其他分类，优先按剧集处理' % (len(fs), len(eps))
        out.append(row('剧集分流', '剧集夹', '剧集分流', folder, sum(f[1] for f in fs), basis=basis,
                       zone=zone, episodes=len(eps)))
    return out


CROSS_STAGE = '合集×REMUX'
CROSS_BUCKET = {'A': '可切', 'B': '可切', 'C': '版本型', 'D': '待定', 'E': '待定'}
KIND_NAME = {'D': 'DIY/特效字幕', 'I': '原盘', 'R': 'REMUX', 'O': '普通压制'}
GIB = 1024 ** 3


def _tl(t):
    return '%s·%s' % (KIND_NAME[t[0]], L.tier(t[1]))


def cross_heji_remux(cfg, cut_all, result):
    """A1 合集 × REMUX（口径 = cross_remux.py TASK 1）。
    合集侧人口 = heji_films 去榜单包/排除词（内核常量 + 用户追加），再去掉内核三刀已判可清理的
    （当轮那批已搬走；不重复列）。REMUX 单元只当参照。"""
    import sieve
    from . import cross
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
    extra = [x for x in cfg['exclude_names'] if x not in C.BUILTIN_EXCLUDE] + \
            [x for x in cfg['listpack_names'] if x not in C.BUILTIN_LISTPACK]
    hj, n_cut = [], 0
    for r in csv.DictReader(open('heji_films.csv', encoding='utf-8-sig')):
        p = r['路径']
        if any(b in p for b in sieve.BANGDAN) or any(e in p for e in sieve.EXCL) or sources.hit_any(p, extra):
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


DUPE_STAGE = '原盘重复'


def yuanpan_dupes(result):
    """A2 第一层：原盘区同名同大小精确重复（口径见 panel/dupes.py）。"""
    from . import dupes
    if not os.path.isfile('yuanpan_all.csv'):
        result['dupes'] = {'skipped': '这个数据来源没有原盘区全量清单（CSV 模式不支持）'}
        return []
    items = [{'path': r['path'], 'size': int(r['size']), 'kind': r['kind'], 'pack': r['pack'], 'top': r['top'] == '1'}
             for r in csv.DictReader(open('yuanpan_all.csv', encoding='utf-8-sig'))]
    top = {x['path'] for x in items if x['top']}
    pack_of = {x['path']: x['pack'] for x in items}
    pack_size = defaultdict(int)
    for x in items:
        pack_size[x['pack']] += x['size']
    moves, all_top = dupes.plan(items, lambda p: p in top, lambda p: pack_of.get(p, ''), pack_size)
    out = []
    for x, keep, why in moves:
        where = '保护 / 保留优先目录' if why == 'top' else '更大的包「%s」' % (keep['pack'] or '分区根')
        out.append(row(DUPE_STAGE, 'A', '可切', x['path'], x['size'] / GIB, keep=keep['path'],
                       basis='同名同大小的另一份在%s，留那份' % where))
    result['dupes'] = {'groups': len(dupes.groups(items)), 'all_protected': all_top, 'moves': len(out),
                       'gb': round(sum(r['gb'] for r in out), 1)}
    result['stats']['a2_l1'] = result['dupes']
    return out


HIDDEN_STAGE = '同字节重复'


def hidden_dupes(cfg, rows, result):
    """A2 第二层：内容完全相同、名字不同的隐藏重复（缓存模式按 Sha1，否则按字节数）。
    已被前面各模块判可清理的份视同已搬走（当轮 build16b 也是先扣掉已搬集合）。"""
    import sieve
    from . import cross, dupes
    if not os.path.isfile('hidden_all.csv'):
        result['hidden'] = {'skipped': '这个数据来源没有全区文件清单（CSV 模式不支持）'}
        return []
    use_sha1 = result['stats'].get('hash_mode') == 'sha1'
    items = []
    for r in csv.DictReader(open('hidden_all.csv', encoding='utf-8-sig')):
        items.append({'path': r['path'], 'size': int(r['size']), 'zone': r['zone'], 'root_depth': int(r['root_depth']),
                      'tier': r['tier'] == '1', 'guard': r['guard'] == '1',
                      'key': (r['sha1'] if use_sha1 else r['size'])})
    parked = list(sieve.EXCL) + [x for x in cfg['exclude_names'] if x not in sieve.EXCL]

    def held(x):
        p = x['path']
        if '/BDMV/' in p.upper() or '/VIDEO_TS/' in p.upper():
            return '碟内文件'
        if any(w in p for w in parked):
            return '另议包'
        if sieve.EP.search(p.rsplit('/', 1)[1]):
            return '剧集标记'
        return ''
    cut = {r['path'] for r in rows if r['bucket'] == '可切'}
    groups = dupes.hidden_groups(items, cross.keyof)
    moves, st = dupes.plan_hidden(groups, held, gone=lambda p: p in cut)
    how = 'Sha1 完全一致' if use_sha1 else '字节数完全一致'
    out = [row(HIDDEN_STAGE, 'A', '可切', x['path'], x['size'] / GIB, keep=k['path'],
               basis='和保留的那份%s、只是名字不同；留规格标注更全 / 已刮削的那份' % how) for x, k in moves]
    result['hidden'] = dict(st, key='sha1' if use_sha1 else 'size', moves=len(out),
                            move_groups=len({id(k) for _, k in moves}), gb=round(sum(r['gb'] for r in out), 1))
    result['stats']['a2_l2'] = result['hidden']
    return out


def main(mode, run_dir):
    os.makedirs(run_dir, exist_ok=True)
    cfg = C.load()
    fp = C.fingerprint(cfg)
    t0 = time.time()
    emit('prepare', '准备数据（%s）' % {'cache': '读 CD2 目录缓存', 'scan': '遍历挂载目录', 'csv': '读现成 CSV'}[cfg['data_source']], 2)
    os.chdir(run_dir)
    if cfg['data_source'] == 'csv':
        stats, files, errors = sources.csv_inputs(cfg, run_dir, lambda m: emit('prepare', m))
    else:
        stats, files, errors = sources.scan_inputs(cfg, run_dir, lambda m: emit('prepare', m))
    result = {'mode': mode, 'fingerprint': fp, 'started': t0, 'stats': stats, 'errors': errors[:200],
              'source': stats.get('source') or {'kind': cfg['data_source']},
              'error_count': len(errors)}
    if mode == 'inventory':
        result['finished'] = time.time()
        _dump(run_dir, result)
        emit('done', '盘点完成', 100)
        return

    import sieve
    rows = []
    emit('stage1', '比对合集与原盘', 20)
    s1 = sieve.stage1()
    for cls, path, g, ypath, ygb, pt, yt in s1:
        rows.append(row('第一刀', cls, S1[cls], path, g, keep=ypath,
                        basis='%s：这份 %s，原盘区 %s（%sGB）' % (S1_DESC[cls], L.tier(pt), L.tier(yt), ygb)))
    cut1 = {r[1] for r in s1 if r[0] in ('A', 'B')}

    emit('stage2', '查找合集内重复', 40)
    s2A, s2B, held = sieve.stage2(cut1)
    for cls, path, g, keep in s2A:
        rows.append(row('第二刀', cls, '可切', path, g, keep=keep, basis='合集里同一部片有更好的一份，保留那份'))
    for cls, path, g, keep in s2B:
        rows.append(row('第二刀', cls, '版本型', path, g, keep=keep, basis='DIY/特效字幕版与普通版，或剪辑版本不同'))
    all2 = s2A + s2B

    emit('stage3', '检查小体积低画质文件', 60)
    emby_tmdb, emby_title = sieve.load_emby()
    s3A, s3B, lone, popn = sieve.stage3(s1, all2, emby_tmdb)
    for cls, path, g, basis, keep in s3A:
        rows.append(row('第三刀', cls, '可切', path, g, keep=keep, basis=L.plain_basis(basis)))
    for cls, path, g, basis, keep in s3B:
        rows.append(row('第三刀', cls, '待定', path, g, keep=keep, basis=L.plain_basis(basis)))
    for x in lone:
        rows.append(row('第三刀', '孤本', '孤本', x['path'], x['gb'], basis='原盘区、合集、Emby 片库里都没有别的副本'))

    emit('vertical', '对比 Emby 片库', 75)
    cut_all = cut1 | {r[1] for r in s2A} | {r[1] for r in s3A}
    for cls, path, g, note in sieve.vertical(cut_all, emby_tmdb, emby_title):
        # 「库内无此片」单列为正藏缺口（只改面板分类，内核判定与条数不变）
        rows.append(row('纵向', cls, '缺口' if cls == '入库提醒' else '提醒', path, g, basis=L.plain_basis(note)))

    emit('cross', '比对合集与 REMUX', 80)
    rows += cross_heji_remux(cfg, cut_all, result)

    emit('dupes', '查找原盘区完全重复', 83)
    rows += yuanpan_dupes(result)

    emit('hidden', '查找改了名的完全重复', 84)
    rows += hidden_dupes(cfg, rows, result)

    emit('tvsplit', '识别混入的剧集', 85)
    # 第一期分流只出清单、不摘刀口行：刀口各桶保持内核原样（已对金标准），两边互斥留到第二期执行时处理
    rows += tv_split(cfg, files)

    # 用户追加的排除词：第二/三刀与纵向不碰（与内核内置 EXCL 同口径）
    extra_ex = [x for x in cfg['exclude_names'] if x not in C.BUILTIN_EXCLUDE]
    if extra_ex:
        rows = [r for r in rows if not (r['stage'] in ('第二刀', '第三刀', '纵向')
                                        and sources.hit_any(r['path'], extra_ex))]

    # 与扫描剪枝同一口径：只看目录组件，单片夹夹名与文件名里的简介字样不算
    unit_dirs = sources.film_unit_dirs([f[1] for f in files])

    # 用户追加的榜单包名（内核不认识）：榜单包留在人口里，但任何一刀的结论都不出
    extra_lp = [x for x in cfg['listpack_names'] if x not in C.BUILTIN_LISTPACK]
    if extra_lp:
        rows = [r for r in rows if r['stage'] == '剧集分流' or not sources.listpack_hit(r['path'], extra_lp, cfg)]

    # 红线：可切里只要有一条落在保护区/榜单包，整批拒绝（不部分放行）

    viol = [r['path'] for r in rows if r['bucket'] == '可切' and sources.guard_hit(cfg, r['path'], unit_dirs)]
    result['protect_violations'] = viol[:200]
    result['rejected'] = bool(viol)

    # 清单展示用：可清理条目的搬运方式（单片夹/盘片夹 → 整夹；多片混装夹 → 只动这个文件），保留份体积
    gb_of, gb_dir = {}, defaultdict(float)
    for f in files:
        gb_of[f[1]] = f[2]
        gb_dir[f[1].rsplit('/', 1)[0]] += f[2]
    for r in rows:
        if r['bucket'] == '可切':
            p = r['path']
            r['move'] = '整夹' if (not sources.is_video_path(p) or p.rsplit('/', 1)[0] in unit_dirs) else '单文件'
        k = r.get('keep')
        if k and k.startswith('/'):
            kg = gb_of.get(k) or gb_dir.get(k)
            if kg:
                r['keep_gb'] = round(kg, 2)
    result['held_stage2'] = held
    result['stage3_population'] = popn

    emit('export', '写出清单', 92)
    summary = defaultdict(lambda: {'count': 0, 'gb': 0.0})
    detail = defaultdict(lambda: {'count': 0, 'gb': 0.0})
    for r in rows:
        for d, k in ((summary, r['bucket']), (detail, '%s|%s|%s' % (r['bucket'], r['stage'], r['cls']))):
            d[k]['count'] += 1
            d[k]['gb'] += r['gb']
    result['summary'] = {b: {'count': summary[b]['count'], 'gb': round(summary[b]['gb'], 1)} for b in BUCKETS}
    result['detail'] = [dict(zip(('bucket', 'stage', 'cls'), k.split('|')), count=v['count'], gb=round(v['gb'], 1))
                        for k, v in sorted(detail.items(), key=lambda kv: (BUCKETS.index(kv[0].split('|')[0]), kv[0]))]
    result['total_gb'] = round(sum(f[2] for f in files), 1)
    with open(os.path.join(run_dir, 'rows.json'), 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False)
    result['finished'] = time.time()
    _dump(run_dir, result)
    emit('done', '完成：%d 条，用时 %.0f 秒' % (len(rows), time.time() - t0), 100)


def _dump(run_dir, result):
    tmp = os.path.join(run_dir, 'result.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(run_dir, 'result.json'))


if __name__ == '__main__':
    try:
        main(sys.argv[1], sys.argv[2])
    except Exception as e:
        import traceback
        traceback.print_exc()
        emit('error', '失败：%s' % e, None)
        sys.exit(1)
