"""sieve 面板（第一期：设置 + 盘点 + 跑筛 + 清单导出，只读）。

红线（写进代码）：
- 本服务没有任何删除/移动/改名接口；第一期也没有执行入口。
- CD2 缓存、Emby 库只读打开（见 panel/sources.py）。
- 配置变了旧清单自动作废（指纹不符的结果不允许导出可切类）。
- 可切里命中保护区/榜单包 → 整批拒绝。
"""
import base64
import csv
import io
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from panel import config as C
from panel import labels as L
from panel import sources

app = FastAPI(title='sieve 面板', docs_url=None, redoc_url=None)
STATIC = C.APP_DIR / 'static'
PASSWORD = os.environ.get('PANEL_PASSWORD', '')

# ---------------- 可选的访问口令（HTTP Basic，用户名任意） ----------------
@app.middleware('http')
async def basic_auth(request: Request, call_next):
    if PASSWORD and request.url.path != '/healthz':
        ok = False
        h = request.headers.get('authorization', '')
        if h.lower().startswith('basic '):
            try:
                pw = base64.b64decode(h[6:]).decode('utf-8').split(':', 1)[1]
                ok = secrets.compare_digest(pw, PASSWORD)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={'WWW-Authenticate': 'Basic realm="sieve"'})
    return await call_next(request)


# ---------------- 任务（一次只跑一个） ----------------
class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.state = {'running': False}

    def start(self, mode):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                raise HTTPException(409, '已有任务在跑')
            C.RUNS_DIR.mkdir(parents=True, exist_ok=True)
            base, n = time.strftime('%Y%m%d-%H%M%S') + '-' + mode, 1
            run_id = base
            while (C.RUNS_DIR / run_id).exists():
                n += 1
                run_id = '%s-%d' % (base, n)
            run_dir = C.RUNS_DIR / run_id
            run_dir.mkdir()
            log = open(run_dir / 'run.log', 'w', encoding='utf-8')
            env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1', SIEVE_DATA=str(C.DATA_DIR))
            self.proc = subprocess.Popen([sys.executable, '-m', 'panel.runner', mode, str(run_dir)],
                                         cwd=str(C.APP_DIR), env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            self.state = {'running': True, 'run_id': run_id, 'mode': mode, 'pct': 0, 'msg': '启动中',
                          'started': time.time(), 'tail': []}
            threading.Thread(target=self._pump, args=(self.proc, log), daemon=True).start()
            return self.state

    def _pump(self, proc, log):
        for line in proc.stdout:
            log.write(line)
            log.flush()
            line = line.rstrip('\n')
            if line.startswith('@@P '):
                try:
                    p = json.loads(line[4:])
                    self.state['msg'] = p['msg']
                    if p.get('pct') is not None:
                        self.state['pct'] = p['pct']
                except ValueError:
                    pass
            else:
                self.state['tail'] = (self.state['tail'] + [line])[-30:]
        code = proc.wait()
        log.close()
        self.state.update(running=False, exit=code, finished=time.time())
        if self.state.get('cancelled'):
            # 结果文件只在跑完时原子写入，停掉的任务不会留下半份结果
            self.state['msg'] = '已停止（这次没有产出结果，之前的结果不受影响）'
        elif code != 0 and not self.state['msg'].startswith('失败'):
            self.state['msg'] = '失败（退出码 %s），见日志' % code

    def cancel(self):
        with self.lock:
            proc = self.proc
            if not proc or proc.poll() is not None:
                raise HTTPException(409, '当前没有在跑的任务')
            self.state['cancelled'] = True
            self.state['msg'] = '正在停止…'
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return self.state


JOB = Job()


# ---------------- 结果读取 ----------------
def list_runs():
    if not C.RUNS_DIR.exists():
        return []
    out = []
    for d in C.RUNS_DIR.iterdir():
        f = d / 'result.json'
        if f.exists():
            try:
                r = json.loads(f.read_text(encoding='utf-8'))
                out.append({'run_id': d.name, 'mode': r.get('mode'), 'fingerprint': r.get('fingerprint'),
                            'finished': r.get('finished')})
            except ValueError:
                pass
    out.sort(key=lambda r: r['finished'] or 0, reverse=True)   # 最新完成的在前
    return out


def load_run(run_id=None, mode='full'):
    runs = [r for r in list_runs() if r['mode'] == mode]
    if run_id:
        runs = [r for r in runs if r['run_id'] == run_id]
    if not runs:
        return None, None
    d = C.RUNS_DIR / runs[0]['run_id']
    res = json.loads((d / 'result.json').read_text(encoding='utf-8'))
    res['run_id'] = runs[0]['run_id']
    res['stale'] = res.get('fingerprint') != C.fingerprint(C.load())
    return res, d


_rows_cache = {}


def load_rows(d):
    key = str(d)
    if key not in _rows_cache:
        _rows_cache.clear()
        _rows_cache[key] = json.loads((d / 'rows.json').read_text(encoding='utf-8'))
    return _rows_cache[key]


def filter_rows(rows, bucket='', stage='', cls='', q=''):
    q = (q or '').strip().lower()
    return [r for r in rows if (not bucket or r['bucket'] == bucket) and (not stage or r['stage'] == stage)
            and (not cls or r['cls'] == cls)
            and (not q or q in r['path'].lower() or q in (r.get('keep') or '').lower())]


# ---------------- API ----------------
@app.get('/healthz')
def healthz():
    return {'ok': True}


@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html')


@app.get('/api/config')
def get_config():
    c = C.load()
    return {'config': c, 'fingerprint': C.fingerprint(c), 'auth_enabled': bool(PASSWORD), 'builtin': {
        'listpack': C.BUILTIN_LISTPACK, 'exclude': C.BUILTIN_EXCLUDE}}


@app.get('/api/suggest')
def suggest():
    try:
        return sources.suggest(C.load())
    except OSError as e:
        raise HTTPException(400, str(e))


@app.put('/api/config')
async def put_config(request: Request):
    body = await request.json()
    old = C.load()
    # 保护词只能加不能减：内置词由 normalize 补回；用户已有的保护目录名不允许在面板里删
    removed = [x for x in old['protect_names'] if x not in (body.get('protect_names') or [])]
    if removed and not body.get('confirm_remove_protect'):
        raise HTTPException(400, '要移除保护目录名：%s。确认请勾选「我确认移除保护」' % '、'.join(removed))
    c = C.save(body)
    return {'config': c, 'fingerprint': C.fingerprint(c)}


@app.post('/api/probe')
def probe():
    c = C.load()
    return {'cd2': sources.probe_cd2(c), 'emby': sources.probe_emby(c)}


@app.get('/api/tree')
def tree(path: str = '/'):
    try:
        c = C.load()
        return {'path': path, 'dirs': sources.dir_lister(c)(c, path)}
    except OSError as e:
        raise HTTPException(400, str(e))


@app.post('/api/run/{mode}')
def run(mode: str):
    if mode not in ('inventory', 'full'):
        raise HTTPException(404)
    c = C.load()
    if c['data_source'] != 'csv' and not any(c['zones'][z] for z in ('heji', 'yuanpan')):
        raise HTTPException(400, '先在「盘点」页至少指定一个合集区或原盘区目录')
    return JOB.start(mode)


@app.get('/api/job')
def job():
    return JOB.state


@app.post('/api/job/cancel')
def job_cancel():
    return JOB.cancel()


@app.get('/api/labels')
def labels():
    return L.as_json()


@app.get('/api/runs')
def runs():
    return list_runs()


@app.get('/api/inventory')
def inventory():
    res, _ = load_run(mode='inventory')
    full, _ = load_run(mode='full')
    # 取最新的一次（盘点或全量都带盘点统计）
    cands = [r for r in (res, full) if r]
    if not cands:
        return JSONResponse(None)
    best = max(cands, key=lambda r: r.get('finished') or 0)
    return {k: best.get(k) for k in ('run_id', 'stats', 'errors', 'error_count', 'stale', 'finished')}


@app.get('/api/result')
def result(run_id: str = ''):
    res, _ = load_run(run_id or None)
    if not res:
        return JSONResponse(None)
    st = res.get('stats') or {}
    st.pop('heji_packs', None)        # 总览只要各区体积，不要大包明细
    return res


@app.get('/api/rows')
def rows(bucket: str = '', stage: str = '', cls: str = '', q: str = '', offset: int = 0, limit: int = 100,
         sort: str = 'gb', run_id: str = ''):
    res, d = load_run(run_id or None)
    if not res:
        return {'total': 0, 'gb': 0, 'rows': []}
    rs = filter_rows(load_rows(d), bucket, stage, cls, q)
    if sort == 'gb':
        rs = sorted(rs, key=lambda r: -r['gb'])
    elif sort == 'path':
        rs = sorted(rs, key=lambda r: r['path'])
    limit = max(1, min(limit, 1000))
    return {'total': len(rs), 'gb': round(sum(r['gb'] for r in rs), 1), 'rows': rs[offset:offset + limit]}


# 导出给人看：分类/来源/判定用白话名，最后一列保留内部叫法便于对账
COLS = [('分类', lambda r: L.bucket(r['bucket'])), ('能不能动', lambda r: L.BUCKETS.get(r['bucket'], ('', '', ''))[2]),
        ('来源', lambda r: L.stage(r['stage'])), ('判定', lambda r: L.cls(r['stage'], r['cls'])),
        ('候选路径', lambda r: r['path']), ('GB', lambda r: r['gb']), ('保留的那份 / 参照', lambda r: r.get('keep', '')),
        ('依据', lambda r: r.get('basis', '')), ('内部分类', lambda r: '%s/%s/%s' % (r['bucket'], r['stage'], r['cls']))]


def _csv_bytes(rs):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[0] for c in COLS])
    for r in rs:
        w.writerow([c[1](r) for c in COLS])
    return ('﻿' + buf.getvalue()).encode('utf-8')


def _export_guard(res, buckets):
    if '可切' in buckets and res.get('stale'):
        raise HTTPException(409, '筛选完之后改过设置，这份结果已过期，请重新筛选后再导出「可清理」')
    if '可切' in buckets and res.get('rejected'):
        raise HTTPException(409, '「可清理」里有条目落在保护区/榜单包里，整批不能导出，请先修正设置再重新筛选')


def _export_resp(res, rs, label, fmt):
    _export_guard(res, {r['bucket'] for r in rs})
    if fmt == 'json':
        body = json.dumps([dict(r, 分类=L.bucket(r['bucket']), 来源=L.stage(r['stage']), 判定=L.cls(r['stage'], r['cls']))
                           for r in rs], ensure_ascii=False, indent=1).encode('utf-8')
        name, mt = 'sieve_%s_%s.json' % (res['run_id'], label), 'application/json; charset=utf-8'
    else:
        body, name, mt = _csv_bytes(rs), 'sieve_%s_%s.csv' % (res['run_id'], label), 'text/csv; charset=utf-8'
    return Response(body, media_type=mt, headers={'Content-Disposition': "attachment; filename*=UTF-8''" + _q(name)})


@app.get('/api/export')
def export(bucket: str = '', stage: str = '', cls: str = '', q: str = '', run_id: str = '', fmt: str = 'csv'):
    res, d = load_run(run_id or None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    rs = sorted(filter_rows(load_rows(d), bucket, stage, cls, q), key=lambda r: -r['gb'])
    return _export_resp(res, rs, L.bucket(bucket) if bucket else '全部', fmt)


@app.post('/api/export/selected')
async def export_selected(request: Request, fmt: str = 'csv'):
    """清单里勾选的条目单独导出（第一期只导出，不批准、不执行）。"""
    body = await request.json()
    res, d = load_run(body.get('run_id') or None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    want = set(body.get('paths') or [])
    rs = sorted([r for r in load_rows(d) if r['path'] in want and r['bucket'] == '可切'], key=lambda r: -r['gb'])
    if not rs:
        raise HTTPException(400, '没有勾选任何「可清理」条目')
    return _export_resp(res, rs, '已勾选', fmt)


@app.get('/api/export.zip')
def export_zip(run_id: str = ''):
    res, d = load_run(run_id or None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    allrows = sorted(load_rows(d), key=lambda r: -r['gb'])
    buckets = sorted({r['bucket'] for r in allrows})
    skip_reason = zip_withheld_reason(res)
    skip_cut = bool(skip_reason)
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        for b in buckets:
            if b == '可切' and skip_cut:
                continue
            z.writestr('%s.csv' % L.bucket(b), _csv_bytes([r for r in allrows if r['bucket'] == b]))
        if skip_cut:
            # 不静默扣下：包里放一份说明，和页面上弹出的原因一致
            z.writestr('_未包含「可清理」的原因.txt', ('\ufeff' + skip_reason + '\r\n').encode('utf-8'))
        z.writestr('summary.json', json.dumps({k: res.get(k) for k in (
            'run_id', 'fingerprint', 'stale', 'rejected', 'summary', 'detail', 'held_stage2',
            'stage3_population', 'protect_violations')}, ensure_ascii=False, indent=2))
    mem.seek(0)
    return StreamingResponse(mem, media_type='application/zip', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + _q('sieve_%s.zip' % res['run_id'])})


def zip_withheld_reason(res):
    try:
        _export_guard(res, {'可切'})
        return ''
    except HTTPException as e:
        return '这个压缩包里没有「可清理」清单：' + e.detail


@app.get('/api/export.check')
def export_check(run_id: str = ''):
    """导出全部之前先问一句：会不会扣下「可清理」、为什么。"""
    res, _ = load_run(run_id or None)
    if not res:
        raise HTTPException(404, '还没有筛选结果')
    return {'withheld': zip_withheld_reason(res)}


@app.get('/api/log')
def log(run_id: str = ''):
    rid = run_id or JOB.state.get('run_id')
    if not rid or '/' in rid or '\\' in rid or '..' in rid:
        raise HTTPException(404)
    f = C.RUNS_DIR / rid / 'run.log'
    if not f.exists():
        raise HTTPException(404)
    return Response(f.read_text(encoding='utf-8', errors='replace')[-200000:], media_type='text/plain; charset=utf-8')


def _q(s):
    from urllib.parse import quote
    return quote(s)
