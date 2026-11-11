"""「已确认保留」名单：用户逐条看过「需人工确认」后的决定，按路径记住，以后重跑不再提醒。

和保护名单分开：保护名单是区域级红线（根本不进候选，影响判定、进配置指纹）；
这份名单只在显示层起作用——只隐藏「待定」桶里路径命中的行，不改内核、不改 rows.json、不进指纹，
所以加一条不会让当前结果作废。隐藏的行有账：接口和页面都报「另有 N 条已确认保留，已隐藏」，设置页可逐条撤销。
文件被别的方式搬走 / 改名后路径自然不再命中，无副作用。"""
import json
import os
import threading
import time

from . import config as C

BUCKET = '待定'
_LOCK = threading.Lock()


def _file():
    return C.DATA_DIR / 'keep_confirmed.json'


def load():
    f = _file()
    if not f.exists():
        return {}
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return d.get('items') or {}
    except (ValueError, OSError):
        return {}


def _save(items):
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = _file()
    tmp = f.with_suffix('.tmp')
    tmp.write_text(json.dumps({'items': items}, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, f)


def add(rows_by_path, paths):
    """只收当前结果里确实是「待定」的路径；返回 (记下的, 跳过的[{path, reason}])。"""
    ok, skipped = [], []
    with _LOCK:
        items = load()
        for p in paths:
            rs = [r for r in rows_by_path.get(p, []) if r['bucket'] == BUCKET]
            if not rs:
                skipped.append({'path': p, 'reason': '不是「需人工确认」条目'})
                continue
            r = rs[0]
            items[p] = {'at': time.strftime('%Y-%m-%d %H:%M'), 'stage': r['stage'], 'cls': r['cls'],
                        'keep': r.get('keep', ''), 'gb': r.get('gb', 0)}
            ok.append(p)
        _save(items)
    return ok, skipped


def remove(paths):
    with _LOCK:
        items = load()
        n = sum(1 for p in paths if items.pop(p, None) is not None)
        _save(items)
    return n


def split(rows, items=None):
    """→ (显示的行, 被隐藏的行)。只隐藏「待定」桶里命中的行。"""
    items = load() if items is None else items
    if not items:
        return rows, []
    shown, hidden = [], []
    for r in rows:
        (hidden if r['bucket'] == BUCKET and r['path'] in items else shown).append(r)
    return shown, hidden
