"""哈希门演练（反馈 29.2，假缓存、不碰真库）：造一份带 Sha1 的 CD2 目录缓存，跑一轮扫描，逐条核对门里怎么判。
用法：python tools/drill_hash.py <面板目录> <一个空的临时目录>"""
import json, os, shutil, sqlite3, subprocess, sys

APP, W = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
G = 1024 ** 3
Y, H = '/115/原盘/', '/115/合集/'
FILES = []                                  # (虚拟路径, GB, sha1 或 None)


def put(vp, gb, sha):
    FILES.append((vp, gb, sha))


def h(tag):
    import hashlib
    return hashlib.sha1(tag.encode()).hexdigest().upper()


# A 热浴盆型：刮削夹里的裸名份、原盘区全名 DIY 份、合集里 CHDBits 份，三份同一个文件
put(Y + '刮削整理/热浴盆时光机 (2010) {tmdb-23048}/热浴盆时光机 1080p (2010).iso', 40, h('a1'))
put(Y + '1080P原盘/热浴盆时光机(2010) 美版原盘 DIY简繁字幕 HDSky 39.5GB .iso', 40, h('a1'))
put(Y + '1080P原盘/别的片(2011) 港版原盘 TTG 30GB .iso', 30, h('a9'))
put(H + '包H/热浴盆时光机 (2010) -CHDBits.iso', 40, h('a1'))
# B Emby 指着的那份先留（哪怕名字是裸的）
put(H + '包P/某片 (2001)/某片.2001.mkv', 15, h('b1'))
put(H + '包Q/某片.2001.1080p.BluRay.x264-FGT.mkv', 15, h('b1'))
# C 夹里多一份外挂字幕：不是同一份东西，门不切
put(Y + '单片/甲片 (1999)/甲片.1999.iso', 30, h('c1'))
put(Y + '单片/甲片 (1999)/甲片.1999.chs.srt', 0.001, h('c2'))
put(H + '包A/甲片.1999.iso', 30, h('c1'))
# D 夹里只多海报 / nfo：算同一份
put(Y + '单片/乙片 (1998)/乙片.1998.iso', 31, h('d1'))
put(Y + '单片/乙片 (1998)/poster.jpg', 0.001, h('d2'))
put(Y + '单片/乙片 (1998)/乙片.1998.nfo', 0.001, h('d3'))
put(H + '包A/乙片.1998.BluRay.1080p.iso', 31, h('d1'))
# E 有一份没 Sha1：不进门（片名分组照常处理）
put(H + '包A/丙片.1997.1080p.mkv', 12, None)
put(H + '包B/丙片.1997.1080p.mkv', 12, h('e1'))
# F 多碟装：整套对上才切；只有一张碟对上的不切
put(H + '包M/丁片 (1990) 双碟版/丁片.1990.Disc1.iso', 20, h('f1'))
put(H + '包M/丁片 (1990) 双碟版/丁片.1990.Disc2.iso', 20, h('f2'))
put(H + '包N/丁片 (1990) 双碟版/丁片.1990.Disc1.iso', 20, h('f1'))
put(H + '包N/丁片 (1990) 双碟版/丁片.1990.Disc2.iso', 20, h('f2'))
# G 剧集不进门
put(H + '包E/某剧.S01E01.1080p.mkv', 3, h('g1'))
put(H + '包F/某剧.S01E01.1080p.mkv', 3, h('g1'))
# H 锁定的（排除词「金庸」）那份留，另一份切
put(H + '金庸/射雕英雄传.1983.mkv', 9, h('h1'))
put(H + '包A/射雕英雄传.1983.mkv', 9, h('h1'))
# I 留下那份后来又被片名分组判掉（同片有 4K 原盘）：依据里写真正留的是谁
put(H + '包A/戊片.2005.1080p.mkv', 14, h('i1'))
put(H + '包B/戊片.2005.1080p.mkv', 14, h('i1'))
put(Y + '4K/戊片 (2005)/戊片.2005.2160p.iso', 60, h('i2'))
put(Y + '4K/己片 (2006)/己片.2006.2160p.iso', 61, h('i3'))

conf = os.path.join(W, 'cd2conf'); os.makedirs(conf)
c = sqlite3.connect(os.path.join(conf, 'dir_cache.sqlite'))
c.executescript('''CREATE TABLE cached_item (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, path TEXT NOT NULL UNIQUE, insert_time INTEGER NOT NULL);
CREATE TABLE files (id TEXT NOT NULL, parent_id INTEGER NOT NULL, name TEXT NOT NULL, file_type INTEGER NOT NULL, size INTEGER NOT NULL,
 create_time INTEGER NOT NULL, access_time INTEGER NOT NULL, write_time INTEGER NOT NULL, api_name TEXT NOT NULL, api_user TEXT NOT NULL,
 thumbnail_url TEXT, preview_url TEXT, file_hash TEXT, custom_data TEXT, original_name TEXT NOT NULL, PRIMARY KEY (id, api_name, api_user));
CREATE TABLE schema_version (version INTEGER PRIMARY KEY); INSERT INTO schema_version VALUES (1);''')
dirs = {'/'}
for vp, _, _ in FILES:
    parts = vp.split('/')
    for i in range(2, len(parts)):
        dirs.add('/'.join(parts[:i]))
ids = {}
for d in sorted(dirs):
    c.execute('insert into cached_item (path, insert_time) values (?, 1794000000)', (d,))
    ids[d] = c.execute('select id from cached_item where path=?', (d,)).fetchone()[0]
n = 0
for d in sorted(dirs):
    if d == '/':
        continue
    par, name = d.rsplit('/', 1)
    n += 1
    c.execute("insert into files values (?,?,?,3,0,0,0,0,'115open','1',NULL,NULL,NULL,NULL,?)", (str(n), ids[par or '/'], name, name))
for vp, gb, sha in FILES:
    par, name = vp.rsplit('/', 1)
    n += 1
    fh = json.dumps({'sha1': sha}) if sha else None
    c.execute("insert into files values (?,?,?,4,?,0,0,0,'115open','1',NULL,NULL,?,NULL,?)", (str(n), ids[par], name, int(gb * G), fh, name))
c.commit(); c.close()
edir = os.path.join(W, 'emby', 'data'); os.makedirs(edir)
c = sqlite3.connect(os.path.join(edir, 'library.db'))
c.execute('create table MediaItems (Id integer primary key, type int, Path text, Name text, ProductionYear int, ProviderIds text, Width int, Height int, IsFolder int)')
c.execute("insert into MediaItems (type,Path,Name,ProductionYear,ProviderIds,Width,Height,IsFolder) values "
          "(5,'/CloudNAS/CloudDrive/115/合集/包P/某片 (2001)/某片.2001.strm','某片',2001,'Tmdb=77',1920,1080,0)")
c.commit(); c.close()

DATA = os.path.join(W, 'data'); os.makedirs(DATA)
json.dump({'data_source': 'cache', 'cd2_config': conf, 'emby_data': os.path.join(W, 'emby'), 'emby_prefix': '/CloudNAS/CloudDrive',
           'zones': {'heji': ['/115/合集'], 'yuanpan': ['/115/原盘'], 'remux': [], 'pack': []}, 'tree_model': True},
          open(os.path.join(DATA, 'config.json'), 'w', encoding='utf-8'), ensure_ascii=False)
RUN = os.path.join(W, 'run')
env = dict(os.environ, SIEVE_DATA=DATA, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
p = subprocess.run([sys.executable, '-m', 'panel.runner', 'scan', RUN], cwd=APP, env=env, capture_output=True, text=True, encoding='utf-8')
if p.returncode:
    print(p.stdout[-3000:], p.stderr[-3000:])
    sys.exit(1)
rows = json.load(open(os.path.join(RUN, 'rows.json'), encoding='utf-8'))
res = json.load(open(os.path.join(RUN, 'result.json'), encoding='utf-8'))
gs = json.load(open(os.path.join(RUN, 'groups.json'), encoding='utf-8'))
hr = [r for r in rows if r['stage'] == '重复副本' and '同文件哈希' in (r.get('tags') or [])]
by = {r['path']: r for r in hr}
allp = {r['path']: r for r in rows}
fails = []


def check(name, cond, info=''):
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)
        print('   ', json.dumps(info, ensure_ascii=False)[:800])


st = res['stats'].get('hash_gate') or {}
check('门开着、按 Sha1', st.get('on'), st)
diy = Y + '1080P原盘/热浴盆时光机(2010) 美版原盘 DIY简繁字幕 HDSky 39.5GB .iso'
check('A 热浴盆：三份同一个文件 → 留名字最全的 DIY 份，另两份标同文件哈希可清理',
      by.get(Y + '刮削整理/热浴盆时光机 (2010) {tmdb-23048}') and by.get(H + '包H/热浴盆时光机 (2010) -CHDBits.iso')
      and all(by[p]['keep'] == diy and by[p]['bucket'] == '可切' and by[p]['cls'] == 'H'
              for p in (Y + '刮削整理/热浴盆时光机 (2010) {tmdb-23048}', H + '包H/热浴盆时光机 (2010) -CHDBits.iso'))
      and diy not in allp, hr)
check('A 热浴盆：三份都在同一张卡上', len({by[p]['grp'] for p in by if '热浴盆' in p}) == 1, [by[p]['grp'] for p in by if '热浴盆' in p])
check('B Emby 指着的裸名份留、全名份切', by.get(H + '包Q/某片.2001.1080p.BluRay.x264-FGT.mkv', {}).get('keep') == H + '包P/某片 (2001)/某片.2001.mkv'
      and H + '包P/某片 (2001)/某片.2001.mkv' not in by, by.get(H + '包Q/某片.2001.1080p.BluRay.x264-FGT.mkv'))
check('C 夹里多外挂字幕 → 不算同一份，门不切', not any('甲片' in p for p in by), [p for p in by if '甲片' in p])
check('D 夹里只多海报 / nfo → 算同一份，门切一份', sum('乙片' in p for p in by) == 1, [p for p in by if '乙片' in p])
check('E 有一份没 Sha1 → 不进门', not any('丙片' in p for p in by), [p for p in by if '丙片' in p])
fset = [p for p in by if '丁片' in p]
check('F 多碟装整套对上 → 整套两张碟都切、标多碟装', len(fset) == 2 and all(by[p].get('disc_set') == 2 for p in fset), fset)
check('G 剧集不进门（在归组之前就分到剧集分流了）', not any('某剧' in p for p in by), [p for p in by if '某剧' in p])
check('H 锁定（金庸）那份留、另一份切', by.get(H + '包A/射雕英雄传.1983.mkv', {}).get('keep') == H + '金庸/射雕英雄传.1983.mkv', by.get(H + '包A/射雕英雄传.1983.mkv'))
ir = [by[p] for p in by if '戊片' in p]
check('I 留下那份又被 4K 判掉 → 依据写明真正留的是 4K 原盘', len(ir) == 1 and ir[0]['keep'].endswith('戊片 (2005)')
      and '真正留的是' in ir[0]['basis'], ir)
check('I 那份 1080p 照常被片名分组判可清理（4K 原盘留）', any(r['path'].startswith(H + '包') and '戊片' in r['path'] and r['stage'] == '重复副本'
                                                       and 'H' != r['cls'] and r['bucket'] == '可切' for r in rows), [r for r in rows if '戊片' in r['path']])
check('同一份不出两行', len(rows) == len({(r['path'], r['stage']) for r in rows}), len(rows))
check('统计：组数 / 多出份数 / 可清理份数', st.get('groups') == 6 and st.get('cut') == 7 and st.get('dup') == 7, st)
check('卡片成员里有门切的份', any(m['role'] == '可切' and '热浴盆' in m['path'] for g in gs.values() for m in g['members']), '')
print('\nALL PASS' if not fails else '\nFAILED: %s' % fails)
sys.exit(1 if fails else 0)
