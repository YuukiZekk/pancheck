"""跑筛子进程：python -m panel.runner <mode> <run_dir>
mode = inventory（只盘点）| full（扫描：盘点 + 重复副本归组 + 主库对比 + 孤本 + 剧集分流）
进度以 "@@P <json>" 行写 stdout；结果写 run_dir/result.json 与各类 CSV。
中间表（panel.tables.Tables）在内存里传给各模块，不切当前目录；run_dir 里的 CSV 只是调试输出。
"""
import json
import os
import sys
import time
from collections import defaultdict

from . import config as C
from . import labels as L
from . import sources
from .tables import Tables

sys.path.insert(0, str(C.APP_DIR))

# 分类 → 面板桶。只有「可切」将来能被批准；待定/孤本永远没有执行入口。
BUCKETS = ['可切', '待定', '版本型', '多碟合集', '不动', '孤本', '缺口', '提醒', '剧集分流']


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


MAIN_STAGE = '主库对比'
LONE_STAGE = '孤本'
GIB = 1024 ** 3


DUPE_STAGE = '重复副本'          # 原盘区同名同大小：独立一条线，结果归到「重复副本」，带标签


def yuanpan_dupes(result, tab):
    """A2 第一层：原盘区同名同大小精确重复（口径见 panel/dupes.py）。"""
    from . import dupes
    if not tab.has('yuanpan_all.csv'):
        result['dupes'] = {'skipped': '这个数据来源没有原盘区全量清单（CSV 模式不支持）'}
        return []
    items = [{'path': r['path'], 'size': int(r['size']), 'kind': r['kind'], 'pack': r['pack'], 'top': r['top'] == '1'}
             for r in tab.rows('yuanpan_all.csv')]
    top = {x['path'] for x in items if x['top']}
    pack_of = {x['path']: x['pack'] for x in items}
    pack_size = defaultdict(int)
    for x in items:
        pack_size[x['pack']] += x['size']
    moves, all_top = dupes.plan(items, lambda p: p in top, lambda p: pack_of.get(p, ''), pack_size)
    out = []
    for x, keep, why in moves:
        where = '保护 / 保留优先目录' if why == 'top' else '更大的包「%s」' % (keep['pack'] or '分区根')
        out.append(row(DUPE_STAGE, 'L1', '可切', x['path'], x['size'] / GIB, keep=keep['path'],
                       basis='同名同大小的另一份在%s，留那份' % where, tags=['原盘同名同大小']))
    result['dupes'] = {'groups': len(dupes.groups(items)), 'all_protected': all_top, 'moves': len(out),
                       'gb': round(sum(r['gb'] for r in out), 1)}
    result['stats']['a2_l1'] = result['dupes']
    return out


B7_STAGE = '主库对比'
B7_BUCKET = {'A': '可切', 'D1': '待定', 'D2': '待定', 'W': '提醒'}
TR = {'U': 3, 'H': 2, 'S': 1}


def remux_vs_mainlib(cfg, rows, result, tab):
    """B7 纵向扩展到 REMUX 区（规则 2：主库已有、且不差于这份 → 多余）。用当下的 Emby 与缓存判。
    「主库里的原盘版」= Emby 电影条目，路径去掉主库挂载前缀后落在原盘区（strm 镜像保留目录结构）。
    配对：TMDB 编号相同，或片名 + 年份都相同 → 确认是同一部；只有片名相同 → 疑似。"""
    from . import cross
    if not tab.has('cross_units.csv'):
        result['b7'] = {'skipped': '没有 REMUX 单元清单'}
        return []
    try:
        items, _ = sources.emby_items(cfg)
    except Exception as e:
        result['b7'] = {'skipped': 'Emby 读不了：%s' % e}
        return []
    pre = (cfg.get('emby_prefix') or '').rstrip('/')
    yroots = [r.rstrip('/') for r in cfg['zones']['yuanpan']]
    by_tm, by_key, by_title = {}, {}, {}
    n_lib = 0
    for it in items:
        if not it['movie'] or not pre or not it['path'].startswith(pre + '/'):
            continue
        folder = it['path'][len(pre):].rsplit('/', 1)[0]
        if not any(folder == r or folder.startswith(r + '/') for r in yroots):
            continue
        vh = sources.nominal_vh(it['width'], it['height'])
        e = {'folder': folder, 'tier': 'U' if vh >= 1600 else 'H' if vh >= 900 else 'S' if vh > 0 else '?',
             'vh': vh, 'name': it['name'], 'year': it['year']}
        n_lib += 1
        _, k = cross.keyof('%s %s' % (it['name'], it['year']))
        title, year = k.split('|')
        for d, key in ((by_tm, it['tmdb']), (by_key, k if title and year else ''), (by_title, title)):
            if key:
                cur = d.get(key)
                if cur is None or TR.get(e['tier'], 0) > TR.get(cur['tier'], 0):
                    d[key] = e
    if not n_lib:
        result['b7'] = {'skipped': 'Emby 里没有落在原盘区的电影（检查「Emby 里看到的 CD2 挂载根」）', 'prefix': pre}
        return []
    cut = {r['path'] for r in rows if r['bucket'] == '可切'}
    touched = set(cut)
    for c in cut:
        while '/' in c.strip('/'):
            c = c.rsplit('/', 1)[0]
            touched.add(c)
    out, cnt, skipped = [], {}, 0
    for u in tab.rows('cross_units.csv'):
        p = u['路径']
        if p in touched or sources.guard_hit(cfg, p, set()):
            skipped += 1
            continue
        tm, k = cross.keyof(u['电影'] + ' ' + u['主视频文件'])
        title = k.split('|')[0]
        lib, how = None, ''
        if tm and tm[1:] in by_tm:
            lib, how = by_tm[tm[1:]], 'TMDB 编号相同'
        elif k in by_key and k.split('|')[1]:
            lib, how = by_key[k], '片名、年份都相同'
        elif title and title in by_title:
            lib, how = by_title[title], '只有片名相同（年份不同或缺）'
        if lib is None:
            continue
        rt = cross.remux_tier({'main': u['主视频文件'], 'title': u['电影']})
        if how.startswith('只有'):
            cls = 'D2'
        elif rt == '?' or lib['tier'] == '?':
            cls = 'D1'
        elif TR[lib['tier']] >= TR.get(rt, 0):
            cls = 'A'
        else:
            cls = 'W'
        cnt[cls] = cnt.get(cls, 0) + 1
        desc = {'A': '主库里已有原盘版、画质不比这份差', 'W': '这份 REMUX 比主库里的原盘版档位高，可拿去给主库洗版',
                'D1': '主库里有这部片的原盘版，但有一边画质看不出', 'D2': '主库里疑似有这部片的原盘版'}[cls]
        out.append(row(B7_STAGE, cls, B7_BUCKET[cls], p, float(u['单元总GB']) * 1e9 / GIB, keep=lib['folder'],
                       basis='%s（%s）：这份 %s，主库 %s%s' % (desc, how, L.tier(rt), L.tier(lib['tier']),
                                                         ' %dp' % lib['vh'] if lib['vh'] else '')))
    result['b7'] = {'mainlib_yuanpan_movies': n_lib, 'skipped_cut_or_protected': skipped,
                    'pairs': sum(cnt.values()), 'classes': cnt}
    result['stats']['b7'] = result['b7']
    return out


def main(mode, run_dir):
    os.makedirs(run_dir, exist_ok=True)
    cfg = C.load()
    fp = C.fingerprint(cfg)
    t0 = time.time()
    emit('prepare', '准备数据（%s）' % {'cache': '读 CD2 目录缓存', 'scan': '遍历挂载目录', 'csv': '读现成 CSV'}[cfg['data_source']], 2)
    # 中间表在内存里传给各模块；run_dir 里的 CSV 只是调试输出（反馈：去掉对当前目录的依赖）
    tab = Tables(dump_dir=run_dir)
    if cfg['data_source'] == 'csv':
        stats, files, errors = sources.csv_inputs(cfg, tab, lambda m: emit('prepare', m))
    else:
        stats, files, errors = sources.scan_inputs(cfg, tab, lambda m: emit('prepare', m))
    result = {'mode': mode, 'fingerprint': fp, 'started': t0, 'stats': stats, 'errors': errors[:200],
              'source': stats.get('source') or {'kind': cfg['data_source']},
              'error_count': len(errors)}
    if mode == 'inventory':
        result['finished'] = time.time()
        _dump(run_dir, result)
        emit('done', '盘点完成', 100)
        return

    import sieve
    from . import groups as G
    sieve.LP_OFF = tuple(cfg.get('listpack_off') or ())          # 用户点过「不算榜单包」的目录
    sieve.LP_ON = not cfg.get('tree_model')                      # 勾选模型：没勾 = 不筛，不再另认榜单包
    rows = []
    emit('dupes', '查找原盘区完全重复', 20)
    # 反馈 31：并成套的多碟装不参加任何自动判断——原盘同名同大小这条线也不碰套里的碟（两边哪边是套都不判）
    sets0 = {pp for c in G.copies(cfg, frozenset(), tab) for pp, _ in (c.get('parts') or [])}
    rows += [r for r in yuanpan_dupes(result, tab) if r['path'] not in sets0 and r.get('keep') not in sets0]
    l1 = {r['path'] for r in rows}

    emit('groups', '把同一部片的副本归组', 35)
    grows, gout, gst, gs = G.scan(cfg, gone=l1, tab=tab)
    rows += grows
    result['groups'] = gst
    result['stats']['groups'] = gst
    with open(os.path.join(run_dir, 'groups.json'), 'w', encoding='utf-8') as f:
        json.dump(gout, f, ensure_ascii=False)

    emit('vertical', '对比 Emby 片库', 60)
    emby_tmdb, emby_title = sieve.load_emby(tab.rows('emby_titles.csv'))
    cut_all = {r['path'] for r in rows if r['bucket'] == '可切'}
    vert_cut = set()
    for cls, path, g, note in sieve.vertical(cut_all, emby_tmdb, emby_title, tab.rows('heji_films.csv')):
        # 主库（Emby）已有、且不差于这份（TMDB 精确命中、同档或更好）→ 多余；库里没有 → 主库缺口
        if cls == '库内已有同档+':
            vert_cut.add(path)
            rows.append(row(MAIN_STAGE, cls, '可切', path, g, keep='Emby 主库', basis=L.plain_basis(note) + '，这份不比库里的好'))
        else:
            rows.append(row(MAIN_STAGE, cls, '缺口' if cls == '入库提醒' else '提醒', path, g, basis=L.plain_basis(note)))

    # 孤本（口径同原小文件层）：合集区小文件、全库只有这一份、主库里也没有同档以上的
    lone = [x for x in G.lone_small(gs) if x['path'] not in vert_cut]
    for x in lone:
        rows.append(row(LONE_STAGE, '孤本', '孤本', x['path'], x['gb'], basis='原盘区、合集、REMUX 区、Emby 片库里都没有别的副本'))

    # 反馈 29.2：原来的同字节层（hidden_dupes）由分组前的哈希门取代——它跳过「片名相同」的同字节对子，正是漏掉的那一块
    result['hidden'] = gst.get('hash') or {}
    result['stats']['hash_gate'] = result['hidden']

    emit('b7', '比对 REMUX 与主库', 82)
    rows += remux_vs_mainlib(cfg, rows, result, tab)

    emit('tvsplit', '识别混入的剧集', 85)
    rows += tv_split(cfg, files)

    # 用户追加的排除词：主库对比与孤本不碰（重复副本在归组时已处理：命中的副本可当保留份，自己不进可清理）
    extra_ex = [x for x in cfg['exclude_names'] if x not in C.BUILTIN_EXCLUDE]
    if extra_ex:
        rows = [r for r in rows if not (r['stage'] in (MAIN_STAGE, LONE_STAGE)
                                        and sources.hit_any(r['path'], extra_ex))]

    # 与扫描剪枝同一口径：只看目录组件，单片夹夹名与文件名里的简介字样不算
    unit_dirs = sources.film_unit_dirs([f[1] for f in files])

    # 用户追加的榜单包名（内核不认识）：榜单包留在人口里，但任何一刀的结论都不出
    extra_lp = list(cfg['listpack_names'])
    if extra_lp:
        rows = [r for r in rows if r['stage'] == '剧集分流' or not sources.listpack_hit(r['path'], extra_lp, cfg, rule=False)]

    # 反馈 31：并成套的多碟装只在「多碟合集」里出现（一套一条），别的线（主库对比、孤本、REMUX 对主库、剧集分流…）不再出它的行
    set_paths = tab.obj('set_paths') or set()
    if set_paths:
        rows = [r for r in rows if r['bucket'] == G.SET_BUCKET or (r['path'] not in set_paths and r.get('keep') not in set_paths)]

    # 红线：可切里只要有一条落在保护区/榜单包，整批拒绝（不部分放行）

    viol = [r['path'] for r in rows if r['bucket'] == '可切' and sources.guard_hit(cfg, r['path'], unit_dirs)]
    result['protect_violations'] = viol[:200]

    # BDMV 肉酱盘单独标注（用户 2026-11-11）：盘片夹，且路径带「肉酱」或盘片夹名带 REMUX；主体或保留份任一边是就标
    import re as _re
    discs = {f[1] for f in files if f[3] in ('BDMV', 'ISO') and not f[1].lower().endswith('.iso')}

    def roujiang(p):
        return bool(p) and p in discs and ('肉酱' in p or bool(_re.search(r'(?i)remux', p.rsplit('/', 1)[-1])))
    n_rj = 0
    for r in rows:
        if roujiang(r['path']) or roujiang(r.get('keep')):
            r['flag'] = 'BDMV肉酱盘'
            n_rj += 1
    result['stats']['bdmv_roujiang_rows'] = n_rj
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
    result['engine'] = 2

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
