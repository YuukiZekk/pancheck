"""跑筛子进程：python -m panel.runner <mode> <run_dir>
mode = inventory（只盘点）| full（盘点 + 三刀 + 纵向 + 剧集分流）
进度以 "@@P <json>" 行写 stdout；结果写 run_dir/result.json 与各类 CSV。
内核 sieve.py 原样 import，读写都在 run_dir 里（内核按相对路径读五张 CSV）。
"""
import json
import os
import sys
import time
from collections import defaultdict

from . import config as C
from . import sources

sys.path.insert(0, str(C.APP_DIR))

# 分类 → 面板桶。只有「可切」将来能被批准；待定/孤本永远没有执行入口。
BUCKETS = ['可切', '待定', '版本型', '不动', '孤本', '提醒', '剧集分流']
S1 = {'A': '可切', 'B': '可切', 'C': '版本型', 'D1': '待定', 'D2': '待定', 'E': '不动'}
S1_DESC = {'A': '合集档低于原盘', 'B': '与原盘同档', 'C': 'DIY×普通 两边留', 'D1': '原盘档未知',
           'D2': '合集档未知', 'E': '合集档高于原盘'}


def emit(step, msg, pct=None):
    print('@@P ' + json.dumps({'step': step, 'msg': msg, 'pct': pct, 't': time.time()}, ensure_ascii=False),
          flush=True)


def row(stage, cls, bucket, path, gb, keep='', basis='', **extra):
    return dict(stage=stage, cls=cls, bucket=bucket, path=path, gb=round(float(gb), 2),
                keep=keep, basis=basis, **extra)


def tv_split(cfg, files):
    """剧集分流（未对金标准，仅出清单）：同一目录 ≥2 个带集号的视频文件 → 整夹列为剧集；
    路径（分区根以下部分）含系列电影词的不分流。"""
    import sieve
    zones = cfg['zones']
    by_folder = defaultdict(list)
    for zone, vp, g, _ in files:
        if zone in ('heji', 'yuanpan', 'remux'):
            by_folder[(zone, vp.rsplit('/', 1)[0])].append((vp, g))
    out = []
    for (zone, folder), fs in sorted(by_folder.items()):
        eps = [f for f in fs if sieve.EP.search(f[0].rsplit('/', 1)[-1])]
        if len(eps) < 2:
            continue
        roots = [r for r in zones.get(zone, []) if folder.startswith(r)]
        rel = folder[len(roots[0]):] if roots else folder
        keep = sources.hit_any(rel, cfg['tv_keep_names'])
        if keep:
            continue
        out.append(row('剧集分流', '剧集夹', '剧集分流', folder, sum(f[1] for f in fs),
                       basis='%d 个文件中 %d 个带集号' % (len(fs), len(eps)), zone=zone))
    return out


def main(mode, run_dir):
    os.makedirs(run_dir, exist_ok=True)
    cfg = C.load()
    fp = C.fingerprint(cfg)
    t0 = time.time()
    emit('prepare', '准备数据（%s 模式）' % ('扫描' if cfg['data_source'] == 'scan' else 'CSV'), 2)
    os.chdir(run_dir)
    if cfg['data_source'] == 'csv':
        stats, files, errors = sources.csv_inputs(cfg, run_dir, lambda m: emit('prepare', m))
    else:
        stats, files, errors = sources.scan_inputs(cfg, run_dir, lambda m: emit('prepare', m))
    result = {'mode': mode, 'fingerprint': fp, 'started': t0, 'stats': stats, 'errors': errors[:200],
              'error_count': len(errors)}
    if mode == 'inventory':
        result['finished'] = time.time()
        _dump(run_dir, result)
        emit('done', '盘点完成', 100)
        return

    import sieve
    rows = []
    emit('stage1', '第一刀：合集 × 原盘', 20)
    s1 = sieve.stage1()
    for cls, path, g, ypath, ygb, pt, yt in s1:
        rows.append(row('第一刀', cls, S1[cls], path, g, keep=ypath,
                        basis='%s：合集 %s / 原盘 %s（%sGB）' % (S1_DESC[cls], pt, yt, ygb)))
    cut1 = {r[1] for r in s1 if r[0] in ('A', 'B')}

    emit('stage2', '第二刀：合集区内互重', 40)
    s2A, s2B, held = sieve.stage2(cut1)
    for cls, path, g, keep in s2A:
        rows.append(row('第二刀', cls, '可切', path, g, keep=keep, basis='区内同片，保留更优份'))
    for cls, path, g, keep in s2B:
        rows.append(row('第二刀', cls, '版本型', path, g, keep=keep, basis='DIY/普通 或 剪辑版本不同'))
    all2 = s2A + s2B

    emit('stage3', '第三刀：小文件层', 60)
    emby_tmdb, emby_title = sieve.load_emby()
    s3A, s3B, lone, popn = sieve.stage3(s1, all2, emby_tmdb)
    for cls, path, g, basis, keep in s3A:
        rows.append(row('第三刀', cls, '可切', path, g, keep=keep, basis=basis))
    for cls, path, g, basis, keep in s3B:
        rows.append(row('第三刀', cls, '待定', path, g, keep=keep, basis=basis))
    for x in lone:
        rows.append(row('第三刀', '孤本', '孤本', x['path'], x['gb'], basis='无原盘份/区内锚点/库内份，永不可切'))

    emit('vertical', '纵向轴：合集剩余片 × Emby', 75)
    cut_all = cut1 | {r[1] for r in s2A} | {r[1] for r in s3A}
    for cls, path, g, note in sieve.vertical(cut_all, emby_tmdb, emby_title):
        rows.append(row('纵向', cls, '提醒', path, g, basis=note))

    emit('tvsplit', '剧集分流', 85)
    tv = tv_split(cfg, files)
    # 剧集不进排查：落在剧集夹里的条目从其他各类里拿掉，只在「剧集分流」里出现
    tv_dirs = tuple(t['path'] + '/' for t in tv)
    if tv_dirs:
        rows = [r for r in rows if not r['path'].startswith(tv_dirs)]
    rows += tv

    # 用户追加的排除词：第二/三刀与纵向不碰（与内核内置 EXCL 同口径）
    extra_ex = [x for x in cfg['exclude_names'] if x not in C.BUILTIN_EXCLUDE]
    if extra_ex:
        rows = [r for r in rows if not (r['stage'] in ('第二刀', '第三刀', '纵向')
                                        and sources.hit_any(r['path'], extra_ex))]

    # 红线：可切里只要有一条落在保护区/榜单包，整批拒绝（不部分放行）
    guard = sources.blocked_names(cfg)
    viol = [r['path'] for r in rows if r['bucket'] == '可切' and sources.hit_any(r['path'], guard)]
    result['protect_violations'] = viol[:200]
    result['rejected'] = bool(viol)
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
