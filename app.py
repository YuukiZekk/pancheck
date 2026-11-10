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
        if code != 0 and not self.state['msg'].startswith('失败'):
            self.state['msg'] = '失败（退出码 %s），见日志' % code


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
    return {'config': c, 'fingerprint': C.fingerprint(c), 'builtin': {
        'listpack': C.BUILTIN_LISTPACK, 'exclude': C.BUILTIN_EXCLUDE}}


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
        return {'path': path, 'dirs': sources.list_dirs(C.load(), path)}
    except OSError as e:
        raise HTTPException(400, str(e))


@app.post('/api/run/{mode}')
def run(mode: str):
    if mode not in ('inventory', 'full'):
        raise HTTPException(404)
    c = C.load()
    if c['data_source'] == 'scan' and not any(c['zones'][z] for z in ('heji', 'yuanpan')):
        raise HTTPException(400, '先在「盘点」页至少指定一个合集区或原盘区目录')
    return JOB.start(mode)


@app.get('/api/job')
def job():
    return JOB.state


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
    res.pop('stats', None)
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


COLS = [('bucket', '分类'), ('stage', '来源'), ('cls', '判定'), ('path', '候选路径'), ('gb', 'GB'),
        ('keep', '保留份/参照'), ('basis', '依据')]


def _csv_bytes(rs):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c[1] for c in COLS])
    for r in rs:
        w.writerow([r.get(c[0], '') for c in COLS])
    return ('﻿' + buf.getvalue()).encode('utf-8')


def _export_guard(res, buckets):
    if '可切' in buckets and res.get('stale'):
        raise HTTPException(409, '配置已改动，这份清单已作废，请重跑后再导出可切类')
    if '可切' in buckets and res.get('rejected'):
        raise HTTPException(409, '可切里有条目落在保护区/榜单包，整批拒绝，先修正配置再重跑')


@app.get('/api/export')
def export(bucket: str = '', stage: str = '', cls: str = '', q: str = '', run_id: str = ''):
    res, d = load_run(run_id or None)
    if not res:
        raise HTTPException(404, '还没有跑筛结果')
    rs = filter_rows(load_rows(d), bucket, stage, cls, q)
    _export_guard(res, {r['bucket'] for r in rs})
    name = 'sieve_%s_%s.csv' % (res['run_id'], bucket or 'all')
    return Response(_csv_bytes(rs), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': "attachment; filename*=UTF-8''" + _q(name)})


@app.get('/api/export.zip')
def export_zip(run_id: str = ''):
    res, d = load_run(run_id or None)
    if not res:
        raise HTTPException(404, '还没有跑筛结果')
    allrows = load_rows(d)
    buckets = sorted({r['bucket'] for r in allrows})
    skip_cut = False
    try:
        _export_guard(res, {'可切'})
    except HTTPException:
        skip_cut = True
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', zipfile.ZIP_DEFLATED) as z:
        for b in buckets:
            if b == '可切' and skip_cut:
                continue
            z.writestr('%s.csv' % b, _csv_bytes([r for r in allrows if r['bucket'] == b]))
        z.writestr('summary.json', json.dumps({k: res.get(k) for k in (
            'run_id', 'fingerprint', 'stale', 'rejected', 'summary', 'detail', 'held_stage2',
            'stage3_population', 'protect_violations')}, ensure_ascii=False, indent=2))
    mem.seek(0)
    return StreamingResponse(mem, media_type='application/zip', headers={
        'Content-Disposition': "attachment; filename*=UTF-8''" + _q('sieve_%s.zip' % res['run_id'])})


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
