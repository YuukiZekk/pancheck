"""第二期全流程演练（假挂载，不碰真库）：批准 → 预演 → 执行 → 对账 → 续跑 → 回滚，全走 HTTP 接口。
用法：python tools/drill_b.py <面板目录> <一个空的临时目录>
argv: app_dir work_dir   输出演练报告到 work_dir/drill_report.json"""
import json, os, shutil, sqlite3, subprocess, sys, time
import httpx

APP, W = sys.argv[1:3]
shutil.rmtree(W, ignore_errors=True)
mount = os.path.join(W, 'mount')
G = 1024 ** 3
Y, H = '115/原盘/', '115/合集/'
CACHE_GB = {}          # 缓存里报的「体积」（判定用）；挂载上是真实小文件（执行用）


def put(rel, gb=None, text='x'):
    p = os.path.join(mount, *rel.split('/'))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w', encoding='utf-8').write(text * 10)
    if gb is not None:
        CACHE_GB['/' + rel] = gb

# 单片夹：合集 1080p vs 原盘 4K → 第一刀可清理；夹里只有这一部片（加 nfo / 字幕）→ 整夹搬
put(Y + '活着.1994.2160p/活着.1994.2160p.iso', 60)
put(H + '包A/活着 (1994)/活着.1994.1080p.mkv', 10)
put(H + '包A/活着 (1994)/活着.1994.1080p.nfo', 0.001)
put(H + '包A/活着 (1994)/活着.1994.1080p.chs.srt', 0.001)
# 混装夹：只有英雄被判可清理 → 只搬这一个文件
put(Y + '英雄.2002.2160p/英雄.2002.2160p.iso', 61)
put(H + '包B/混装/英雄.2002.1080p.mkv', 11)
put(H + '包B/混装/霸王别姬.1993.1080p.mkv', 12)
# 主库缺口：Emby 里没有 → 挪入主库
put(H + '包C/红高粱 (1987)/红高粱.1987.1080p.mkv', 20)
# 原盘同名同大小 12 组：小包那份可清理（凑出 >10 条测试试跑门槛）
for i in range(1, 13):
    put(Y + '大包/Film%02d (20%02d)/Film%02d.20%02d.iso' % (i, i, i, i), 30 + i * 0.37)
    put(Y + '小包/Film%02d (20%02d)/Film%02d.20%02d.iso' % (i, i, i, i), 30 + i * 0.37)
put(Y + '大包/填充 (2000)/填充.2000.iso', 500)

conf = os.path.join(W, 'cd2conf'); os.makedirs(conf)
c = sqlite3.connect(os.path.join(conf, 'dir_cache.sqlite'))
c.executescript('''CREATE TABLE cached_item (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, path TEXT NOT NULL UNIQUE, insert_time INTEGER NOT NULL);
CREATE TABLE files (id TEXT NOT NULL, parent_id INTEGER NOT NULL, name TEXT NOT NULL, file_type INTEGER NOT NULL, size INTEGER NOT NULL,
 create_time INTEGER NOT NULL, access_time INTEGER NOT NULL, write_time INTEGER NOT NULL, api_name TEXT NOT NULL, api_user TEXT NOT NULL,
 thumbnail_url TEXT, preview_url TEXT, file_hash TEXT, custom_data TEXT, original_name TEXT NOT NULL, PRIMARY KEY (id, api_name, api_user));
CREATE TABLE schema_version (version INTEGER PRIMARY KEY); INSERT INTO schema_version VALUES (1);''')
n = 0
for dp, dns, fns in os.walk(mount):
    rel = os.path.relpath(dp, mount).replace(os.sep, '/')
    vp = '/' if rel == '.' else '/' + rel
    c.execute('insert into cached_item (path, insert_time) values (?, 1794000000)', (vp,))
    pid = c.execute('select id from cached_item where path=?', (vp,)).fetchone()[0]
    for name, ft in [(d, 3) for d in dns] + [(f, 4) for f in fns]:
        n += 1
        size = int(CACHE_GB.get(vp.rstrip('/') + '/' + name, 0) * G) if ft == 4 else 0
        c.execute("insert into files values (?,?,?,?,?,0,0,0,'115open','1',NULL,NULL,NULL,NULL,?)", (str(n), pid, name, ft, size, name))
c.commit(); c.close()
edir = os.path.join(W, 'emby', 'data'); os.makedirs(edir)
c = sqlite3.connect(os.path.join(edir, 'library.db'))
c.execute('create table MediaItems (Id integer primary key, type int, Path text, Name text, ProductionYear int, ProviderIds text, Width int, Height int, IsFolder int)')
c.execute("insert into MediaItems (type,Path,Name,ProviderIds,Width,Height,IsFolder) values (5,'/x/y.strm','别的片','Tmdb=1',1920,1080,0)")
c.commit(); c.close()

DATA = os.path.join(W, 'data'); os.makedirs(DATA)
json.dump({'data_source': 'cache', 'cd2_config': conf, 'cd2_mount': mount, 'emby_data': os.path.join(W, 'emby'),
           'zones': {'heji': ['/115/合集'], 'yuanpan': ['/115/原盘'], 'remux': [], 'pack': []},
           'quarantine_dir': '/115/99-排查区', 'main_lib_dir': '/115/00-主库', 'unique_dir': '/115/98-唯一副本'},
          open(os.path.join(DATA, 'config.json'), 'w', encoding='utf-8'), ensure_ascii=False)

PY = sys.executable
SRV = None
# 后端：默认挂载改名；DRILL_BACKEND=cd2 时起一个假 CD2 gRPC 服务，走直连搬移
CD2 = os.environ.get('DRILL_BACKEND') == 'cd2'
FAKE, FAKE_LOG, TOKEN = None, os.path.join(W, 'fake_cd2.log'), 'drill-token-0123456789abcdef'


def fake_cd2(perms='list,mkdir,move', die_after=0):
    global FAKE
    if FAKE:
        FAKE.terminate(); FAKE.wait()
    FAKE = subprocess.Popen([PY, os.path.join(APP, 'tools', 'fake_cd2.py'), mount, '8790', TOKEN, FAKE_LOG, perms, str(die_after)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    FAKE.stdout.readline()


if CD2:
    # CD2 真实格式：{ 令牌本体: {元数据} }；前面放一个 CD2 已不认的令牌，要能跳过它试下一个
    json.dump({'stale-token-0000000000': {'friendly_name': 'old', 'root_dir': '/', 'permissions': {'allow_list': True}},
               TOKEN: {'friendly_name': 'drill', 'root_dir': '/', 'permissions': {'allow_list': True, 'allow_create_folder': True, 'allow_move': True}}},
              open(os.path.join(conf, 'api_tokens.json'), 'w', encoding='utf-8'))
    c = json.load(open(os.path.join(DATA, 'config.json'), encoding='utf-8'))
    c.update(exec_mode='cd2', cd2_api_addr='127.0.0.1:8790')
    json.dump(c, open(os.path.join(DATA, 'config.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    fake_cd2()
B = 'http://127.0.0.1:8770'


def server(**env):
    global SRV
    if SRV:
        SRV.terminate(); SRV.wait()
    e = dict(os.environ, SIEVE_DATA=DATA, **env)
    e.pop('PANEL_PASSWORD', None)
    SRV = subprocess.Popen([PY, '-m', 'uvicorn', 'app:app', '--port', '8770'], cwd=APP, env=e,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            httpx.get(B + '/healthz'); return
        except httpx.HTTPError:
            time.sleep(0.1)


cl = httpx.Client(base_url=B, timeout=60)
fails, report = [], {'steps': []}


def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name, '' if cond else info)
    report['steps'].append({'check': name, 'ok': bool(cond)})
    if not cond:
        fails.append(name)


def wait_job():
    for _ in range(600):
        j = cl.get('/api/job').json()
        if not j.get('running'):
            return j
        time.sleep(0.2)


def exists(v):
    return os.path.exists(os.path.join(mount, *v.strip('/').split('/')))


def approve(add=(), remove=()):
    return cl.put('/api/approvals', json={'add': [{'path': p, 'dest': d} for p, d in add], 'remove': list(remove)}).json()

# ---------- 0. 开关没开：能跑筛、能批准、能预演，不能执行 ----------
server()
cl.post('/api/run/full'); wait_job()
rows = cl.get('/api/rows', params={'limit': 1000}).json()['rows']
cut = sorted({r['path'] for r in rows if r['bucket'] == '可切'})
gap = sorted({r['path'] for r in rows if r['bucket'] == '缺口' and '红高粱' in r['path']})
A2 = [p for p in cut if '/小包/' in p]
huozhe = [p for p in cut if '活着' in p and '/合集/' in p]
yingxiong = [p for p in cut if '英雄' in p and '/合集/' in p]
check('fixture: 14 条可清理（活着、英雄、12 组原盘重复）+ 红高粱缺口',
      len(A2) == 12 and len(huozhe) == 1 and len(yingxiong) == 1 and len(gap) == 1, (cut, gap))
r = approve([(p, None) for p in cut])
check('批准 14 条可清理', r['count'] == 14 and not r['errors'], r)
r = approve([('/115/原盘/活着.1994.2160p/活着.1994.2160p.iso', None)])
check('不在可清理 / 缺口里的批准被拒', r['errors'] and '只有' in r['errors'][0]['reason'], r)
check('开关没开：执行入口 403', cl.post('/api/exec/run').status_code == 403)
pl = cl.post('/api/exec/plan').json()
check('开关没开也能预演', len(pl['ops']) == 14, pl)

# ---------- 1. 开关打开；第一次 >10 条被拦 ----------
server(PANEL_ALLOW_MOVE='1')
st = cl.get('/api/exec/status').json()
check('状态：开关开、挂载可写、未试跑', st['allowed'] and st['mount_writable'] and not st['trial_ok'], st)
r = cl.post('/api/exec/run')
check('第一次批准 14 条（>10）被拦', r.status_code == 409 and '≤10' in r.json()['detail'], r.text)

# ---------- 2. 试跑批次：6 条（活着整夹、英雄单文件、红高粱挪入主库、3 组原盘重复） ----------
approve([], remove=A2[3:])
approve([(gap[0], 'mainlib')])
pl = cl.post('/api/exec/plan').json()
kinds = {o['src']: (o['kind'], o['dst']) for o in pl['ops']}
hz_dir = huozhe[0].rsplit('/', 1)[0]
check('预演：活着单片夹 → 整夹（含 nfo/字幕）', kinds.get(hz_dir, ('',))[0] == 'folder', kinds)
check('预演：混装夹里的英雄 → 只搬这个文件', kinds.get(yingxiong[0], ('',))[0] == 'file', kinds)
gap_dir = gap[0].rsplit('/', 1)[0]
check('预演：红高粱 → 挪入主库（整夹）', kinds.get(gap_dir, ('', ''))[1] == '/115/00-主库/红高粱 (1987)', kinds)
check('预演：排查区按批次保留原路径', kinds[hz_dir][1].startswith('/115/99-排查区/B') and kinds[hz_dir][1].endswith(hz_dir), kinds[hz_dir])
report['trial_plan'] = pl
# 防重复：同时点三次执行，只许建一个批次
import threading
codes = []
ths = [threading.Thread(target=lambda: codes.append(httpx.post(B + '/api/exec/run', timeout=120).status_code)) for _ in range(3)]
[t.start() for t in ths]; [t.join() for t in ths]
check('防重复：同时点三次执行 → 只建一个批次（1 个 200、2 个 409）', sorted(codes) == [200, 409, 409]
      and len(os.listdir(os.path.join(DATA, 'batches'))) == 1, codes)
r = cl.get('/api/job')
check('试跑批次开跑', r.status_code == 200, r.text)
j = wait_job()
b1 = j['run_id']
rec = cl.get('/api/exec/batch/' + b1).json()['reconcile']
report['trial_reconcile'] = rec
check('试跑对账：6 = 搬成 6 + 跳过 0 + 失败 0，平', rec['ok'] and rec['rows'] == 6 and rec['moved_rows'] == 6, rec)
check('实地：活着整夹在排查区（含 nfo/字幕），原位置没了', not exists(hz_dir)
      and exists('/115/99-排查区/' + b1 + hz_dir + '/活着.1994.1080p.chs.srt'))
check('实地：霸王别姬还在混装夹里、英雄搬走了', exists('/115/合集/包B/混装/霸王别姬.1993.1080p.mkv') and not exists(yingxiong[0]))
check('实地：红高粱进了主库', exists('/115/00-主库/红高粱 (1987)/红高粱.1987.1080p.mkv') and not exists(gap_dir))
check('试跑通过 → 放开批量', cl.get('/api/exec/status').json()['trial_ok'])
check('批准随批次带走（清单上清空）', cl.get('/api/exec/status').json()['approvals'] == 0)

# ---------- 3. 批量 9 条，中途崩溃 → 续跑 ----------
approve([(p, None) for p in A2[3:]])
server(PANEL_ALLOW_MOVE='1', PANEL_EXEC_CRASH_AFTER='2')
cl.post('/api/exec/run'); j = wait_job(); b2 = j['run_id']
jr = [json.loads(l) for l in open(os.path.join(DATA, 'batches', b2, 'journal.jsonl'), encoding='utf-8')]
check('模拟崩溃：搬了 2 处，第 2 处只写了「打算」没写结果', j['exit'] == 3 and sum(e['state'] == 'intent' for e in jr) == 2
      and sum(e['state'] == 'done' for e in jr) == 1, (j, jr))
server(PANEL_ALLOW_MOVE='1')
r = cl.post('/api/exec/resume/' + b2); j = wait_job()
rec2 = cl.get('/api/exec/batch/' + b2).json()['reconcile']
report['resume_reconcile'] = rec2
jr = [json.loads(l) for l in open(os.path.join(DATA, 'batches', b2, 'journal.jsonl'), encoding='utf-8')]
check('续跑：断点那处按实地判成「已搬成」，不重搬', any(e.get('note') == '续跑：上次已搬成' for e in jr), jr[-12:])
check('续跑后对账：9 = 搬成 9，平', rec2['ok'] and rec2['moved_rows'] == 9, rec2)
check('实地：小包 9 份都在排查区', all(not exists(p) and exists('/115/99-排查区/' + b2 + p) for p in A2[3:]))

# ---------- 4. 缓存滞后：清单里还列着已经搬走的 → 预演实地核对，判「源已不在」，不会误动 ----------
cl.post('/api/run/full'); wait_job()
rows = cl.get('/api/rows', params={'limit': 1000}).json()['rows']
stale = [r['path'] for r in rows if r['bucket'] == '可切']
approve([(p, None) for p in stale])
pl = cl.post('/api/exec/plan').json()
check('缓存滞后：已搬走的 14 条全判「源已不在」、0 处搬运', not pl['ops'] and len(pl['refused']) == 14
      and all(r.get('skip') for r in pl['refused']), pl['refused'][:2])
check('没有可执行的搬运 → 执行被拦（不建空批次）', cl.post('/api/exec/run').status_code == 400)
approve([], remove=stale)

# ---------- 5. 回滚试跑批次；排查区里那份被动过 → 不覆盖 ----------
open(os.path.join(mount, '115', '99-排查区', b1, *hz_dir.strip('/').split('/'), '多出来的.txt'), 'w').write('tamper')
r = cl.post('/api/exec/rollback/' + b1); j = wait_job()
rb = cl.get('/api/exec/batch/' + b1).json()['rollback']
report['rollback'] = rb
check('回滚：5 处搬回，活着那处体积对不上 → 不覆盖、报出来', rb['rolled_back'] == 5 and len(rb['problems']) == 1
      and '身份不符' in rb['problems'][0]['reason'], rb)
check('实地：英雄、红高粱、3 份原盘回到原位', exists(yingxiong[0]) and exists(gap[0]) and all(exists(p) for p in A2[:3]))
check('实地：活着仍在排查区（没被覆盖）', exists('/115/99-排查区/' + b1 + hz_dir) and not exists(hz_dir))

# ---------- 6. 配置一改，批准作废 ----------
cl.post('/api/run/full'); wait_job()
rows = cl.get('/api/rows', params={'limit': 1000}).json()['rows']
back = [r['path'] for r in rows if r['bucket'] == '可切']
approve([(p, None) for p in back])
# 重跑：判定没变的批准自动带到新结果，并报数（带过来的照样要过预演复核）
cl.post('/api/run/full'); j = wait_job()
a = cl.get('/api/approvals').json()
check('重跑：判定没变的批准带到新结果并报数', len(a['items']) == len(back) and (a.get('carry') or {}).get('carried') == len(back)
      and not a['carry']['dropped'] and ('带过来 %d 条' % len(back)) in j['msg'], (a.get('carry'), j['msg']))
check('重跑：带过来的批准照样过预演复核', cl.post('/api/exec/plan').status_code == 200)
cfg = cl.get('/api/config').json()['config']
cfg['min_video_mb'] = 50
cl.put('/api/config', json=cfg)
check('配置改了：批准自动作废、执行被拦', cl.get('/api/exec/status').json()['approvals'] == 0
      and cl.post('/api/exec/run').status_code == 409)

# ---------- 6b. 直连专项 ----------
if CD2:
    calls = [json.loads(l) for l in open(FAKE_LOG, encoding='utf-8')]
    mv = [c for c in calls if c['m'] == 'MoveFile']
    done_ops = 0
    for b in (b1, b2):
        done_ops += sum(1 for l in open(os.path.join(DATA, 'batches', b, 'journal.jsonl'), encoding='utf-8')
                        if json.loads(l)['state'] in ('done',))
    check('直连：搬移全走 CD2 MoveFile（含回滚搬回），固定不覆盖、不跨云',
          len(mv) >= done_ops and all(c['policy'] == 2 and c['across'] == 0 for c in mv), (len(mv), done_ops))
    from collections import Counter as _C
    cc = _C(c['m'] for c in calls)
    report['cd2_calls'] = dict(cc)
    check('直连：认出真实格式的令牌（跳过 CD2 不认的那个）', any(c['m'] == 'GetApiTokenInfo' for c in calls) and cc.get('MoveFile', 0) > 0, dict(cc))
    check('直连：批次计划记的后端是 cd2', json.load(open(os.path.join(DATA, 'batches', b1, 'plan.json'), encoding='utf-8'))['backend'] == 'cd2')
    check('直连：令牌没写进计划和日志', all(TOKEN not in open(os.path.join(DATA, 'batches', b, f), encoding='utf-8').read()
                                    for b in (b1, b2) for f in ('plan.json', 'journal.jsonl')))
    # 令牌缺「移动」权限 → 预演就拒，说清楚
    cfg = cl.get('/api/config').json()['config']; cfg['min_video_mb'] = 100; cl.put('/api/config', json=cfg)
    cl.post('/api/run/full'); wait_job()
    # 设置改回去后上一轮的批准又生效、会被带过来；这里只要一条，先清空
    approve([], remove=list(cl.get('/api/approvals').json()['items']))
    rows = cl.get('/api/rows', params={'limit': 1000}).json()['rows']
    todo = [r['path'] for r in rows if r['bucket'] == '可切' and exists(r['path'])][:1]
    approve([(p, None) for p in todo])
    fake_cd2('list,mkdir')
    r = cl.post('/api/exec/plan')
    check('直连：令牌缺「移动」权限 → 预演被拒并说明', r.status_code == 400 and '权限' in r.json()['detail'], r.text)
    # 中途 CD2 断了 → 停批，不退回挂载；用户选「挂载改名」续跑才继续
    fake_cd2()
    os.environ['PANEL_EXEC_CRASH_AFTER'] = ''
    r = cl.post('/api/exec/run'); check('直连：小批次开跑', r.status_code == 200, r.text)
    j = wait_job(); b3 = j['run_id']
    check('直连：小批次全部搬成', cl.get('/api/exec/batch/' + b3).json()['reconcile']['ok'])
    cl.post('/api/run/full'); wait_job()
    rows = cl.get('/api/rows', params={'limit': 1000}).json()['rows']
    todo = [r['path'] for r in rows if r['bucket'] == '可切' and exists(r['path'])][:2]
    approve([(p, None) for p in todo])
    # 中途断：搬完第 1 处 CD2 就退出 → 第 2 处失败、停批；用户明确选「挂载改名」续跑才继续
    cl.post('/api/run/full'); wait_job()
    rows = cl.get('/api/rows', params={'limit': 1000}).json()['rows']
    todo = [r['path'] for r in rows if r['bucket'] == '可切' and exists(r['path'])][:2]
    check('直连：中途断测试有 2 条可用', len(todo) == 2, todo)
    approve([(p, None) for p in todo])
    fake_cd2(die_after=1)
    r = cl.post('/api/exec/run'); j = wait_job(); b4 = j['run_id']
    rec4 = cl.get('/api/exec/batch/' + b4).json()['reconcile']
    jr = [json.loads(l) for l in open(os.path.join(DATA, 'batches', b4, 'journal.jsonl'), encoding='utf-8')]
    check('直连：中途断（CD2 搬了、没来得及确认）→ 记「结果未知」、停批、第 2 处没动、对账不平',
          any(e['state'] == 'unknown' for e in jr) and not rec4['ok']
          and not exists(jr[0]['src']) and all(exists(p) for p in todo if not p.startswith(jr[0]['src'])), (rec4, jr[-3:]))
    r = cl.post('/api/exec/resume/' + b4, params={'backend': 'mount'}); j = wait_job()
    rec4 = cl.get('/api/exec/batch/' + b4).json()['reconcile']
    jr = [json.loads(l) for l in open(os.path.join(DATA, 'batches', b4, 'journal.jsonl'), encoding='utf-8')]
    check('直连：用户选「挂载改名」续跑 → 结果未知那处按实地判成已搬成、剩下的搬成，对账平（日志记了改用挂载）',
          any(e['state'] == 'backend' and e['to'] == 'mount' for e in jr) and any(e.get('note') == '续跑：上次已搬成' for e in jr)
          and rec4['moved_rows'] == 2 and rec4['ok'], rec4)
    cl.post('/api/run/full'); wait_job()
    rows = cl.get('/api/rows', params={'limit': 1000}).json()['rows']
    todo = [r['path'] for r in rows if r['bucket'] == '可切' and exists(r['path'])][:1]
    check('直连：还剩可用的演练条目', len(todo) == 1, todo)
    approve([(p, None) for p in todo])
    FAKE.terminate(); FAKE.wait()
    r = cl.post('/api/exec/run')
    check('直连：CD2 不通 → 不建批次、说清楚（不退回挂载）', r.status_code == 400 and '直连不可用' in r.json()['detail'], r.text)
    check('直连：CD2 不通时文件一个没动', all(exists(p) for p in todo))

SRV.terminate()
if FAKE:
    FAKE.terminate()

# ---------- 7. 拒绝规则单测（不经接口） ----------
os.environ['SIEVE_DATA'] = DATA
sys.path.insert(0, APP)
from panel import config as C, execute as X
cfg = C.normalize(json.load(open(os.path.join(DATA, 'config.json'), encoding='utf-8')))
put(H + '包D/成龙合集/警察故事.1985.1080p.mkv'); put(H + '包D/成龙合集/红番区.1995.1080p.mkv')
rows = [{'path': '/115/合集/包D/成龙合集', 'bucket': '可切'}, {'path': '/115/合集/包B/混装/霸王别姬.1993.1080p.mkv', 'bucket': '可切'}]
p = X.plan(cfg, rows, {'/115/合集/包D/成龙合集': {}}, 'Btest', X.MountFS(cfg))
check('多片夹（成龙夹）整夹批准 → 拒绝', not p['ops'] and '多片夹' in p['refused'][0]['reason'], p)
p = X.plan(dict(cfg, quarantine_dir='/116/排查区'), rows, {'/115/合集/包B/混装/霸王别姬.1993.1080p.mkv': {}}, 'Btest', X.MountFS(cfg))
check('排查区不在同一网盘 → 拒绝（不复制）', not p['ops'] and '跨盘' in p['refused'][0]['reason'], p)
put('115/99-排查区/Btest/115/合集/包B/混装/霸王别姬.1993.1080p.mkv')
p = X.plan(cfg, rows, {'/115/合集/包B/混装/霸王别姬.1993.1080p.mkv': {}}, 'Btest', X.MountFS(cfg))
check('目标位置已有同名 → 拒绝（不覆盖）', not p['ops'] and '不覆盖' in p['refused'][0]['reason'], p)
from pathlib import Path
bd = Path(DATA) / 'batches' / 'Bident'
bd.mkdir(parents=True)
victim = '/115/合集/包B/混装/霸王别姬.1993.1080p.mkv'
real_size = os.path.getsize(os.path.join(mount, *victim.strip('/').split('/')))
json.dump({'batch_id': 'Bident', 'rows': 1, 'gb': 0, 'refused': [],
           'ops': [{'id': 0, 'kind': 'file', 'src': victim, 'dst': '/115/99-排查区/Bident' + victim, 'covers': [victim],
                    'action': 'quarantine', 'size': real_size + 1, 'videos': 1}]},
          open(bd / 'plan.json', 'w', encoding='utf-8'), ensure_ascii=False)
X.run_batch(bd)
rec = json.load(open(bd / 'reconcile.json', encoding='utf-8'))
check('执行时身份不符（体积和预演时不同）→ 不搬、记失败、对账不平', exists(victim) and rec['failed_rows'] == 1 and not rec['ok']
      and '身份不符' in rec['failures'][0]['reason'], rec)
rb = {'/x': [{'bucket': '缺口'}, {'bucket': '孤本'}]}
check('缺口 × 唯一副本：不选去处不让批准', X.approvable(rb, '/x', None)[1] and X.approvable(rb, '/x', 'unique')[0] == 'unique')
src = open(os.path.join(APP, 'panel', 'execute.py'), encoding='utf-8').read()
check('执行模块里没有删除调用', not any(w in src for w in ('os.remove', 'unlink', 'rmtree', 'rmdir', 'shutil.copy')))

report['fails'] = fails
json.dump(report, open(os.path.join(W, 'drill_report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('\nALL PASS' if not fails else '\nFAILED: %s' % fails)
sys.exit(1 if fails else 0)
