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
# F 多碟装（反馈 31）：并成套的不进门，字节相同的两套也都进「多碟合集」，一套一条
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

# J 码头风云型（反馈 31）：3 碟套原盘进多碟合集；剩下的单碟里 4K DIY 当留，1080p 单碟可清理
for i in (1, 2, 3):
    put(Y + '单/庚片(1954) 4K 美版原盘 三碟 DISC %d.iso' % i, 85, h('j%d' % i))      # 和真库一样：散放在多片夹里的几张碟并成一套
put(Y + '单/庚片(1954) 4K 美版原盘 DIY 简繁字幕 HDSky 84.1GB .iso', 84, h('j7'))
put(Y + '单/庚片(1954) 1080p Blu-ray AVC.iso', 40, h('j8'))
put(Y + '单/占位(2000) 1080p.iso', 30, h('j9'))
# K 一组里全是套：整组进多碟合集，不出别的判断
for tag, dirn in (('k', '甲套'), ('m', '乙套')):
    for i in (1, 2):
        put(H + '%s/辛片 (1977)/辛片.1977.1080p.Disc%d.iso' % (dirn, i), 25 + (tag == 'm'), h(tag + str(i)))
# L 名字带碟号、没并成套的单张碟：不算套，照老规矩（需人工确认）
put(Y + '单/壬片(1953) 4K DIY DISC.1.iso', 45, h('l1'))
put(H + '包A/壬片.1953.2160p.mkv', 20, h('l2'))

# 反馈 32：剧集分集不并套（天龙八部的「部」、ISO 光有编号），也不当同一部片的几份去切
for i in (1, 2, 3):
    put(Y + '单/天龙八部(1997) %02d.iso' % i, 20 + i, h('tl%d' % i))
    put(Y + '单/倚天屠龙记(1994)-%02d.iso' % i, 15 + i, h('yt%d' % i))
# 反馈 32：Disc1 / Disc2 认片时去掉碟号 → 并成一套
put(Y + '单/The.Fight.for.Moscow.1985.JPN.Disc1.iso', 40, h('mo1'))
put(Y + '单/The.Fight.for.Moscow.1985.JPN.Disc2.iso', 41, h('mo2'))
put(H + '包A/The.Fight.for.Moscow.1985.1080p.mkv', 12, h('mo3'))
# 反馈 32：正片碟 + 花絮碟是一套；Disc1 + Disc2 + 花絮碟三张一套；花絮 1 + 花絮 2 一套
put(Y + '单/卡萨布兰卡(1942) 原盘 正片碟.iso', 45.9, h('ka1'))
put(Y + '单/卡萨布兰卡(1942) 原盘 花絮碟.iso', 23.0, h('ka2'))
put(H + '包A/卡萨布兰卡.1942.1080p.mkv', 10, h('ka3'))
put(Y + '单/浩劫(1985) 原盘 Disc1.iso', 45.5, h('hj1'))
put(Y + '单/浩劫(1985) 原盘 Disc2.iso', 45.5, h('hj2'))
put(Y + '单/浩劫(1985) 原盘 花絮碟.iso', 44.3, h('hj3'))
put(H + '包A/浩劫.1985.1080p.mkv', 11, h('hj4'))
put(Y + '单/公民凯恩(1941) 原盘 花絮1.iso', 20, h('gm1'))
put(Y + '单/公民凯恩(1941) 原盘 花絮2.iso', 21, h('gm2'))
put(H + '包A/公民凯恩.1941.1080p.mkv', 10, h('gm3'))

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
sets = [r for r in rows if r['bucket'] == '多碟合集' and '丁片' in r['path']]
check('F 字节相同的两套不进门、都进多碟合集（一套一条、写碟数）', not fset and len(sets) == 2 and all(r['disc_set'] == 2 and len(r['parts']) == 2 for r in sets), sets)
check('F 套里的碟不在别的栏出现', not any('丁片' in r['path'] and r['bucket'] != '多碟合集' for r in rows), [r for r in rows if '丁片' in r['path']])
check('G 剧集不进门（在归组之前就分到剧集分流了）', not any('某剧' in p for p in by), [p for p in by if '某剧' in p])
check('H 锁定（金庸）那份留、另一份切', by.get(H + '包A/射雕英雄传.1983.mkv', {}).get('keep') == H + '金庸/射雕英雄传.1983.mkv', by.get(H + '包A/射雕英雄传.1983.mkv'))
ir = [by[p] for p in by if '戊片' in p]
check('I 留下那份又被 4K 判掉 → 依据写明真正留的是 4K 原盘', len(ir) == 1 and ir[0]['keep'].endswith('戊片 (2005)')
      and '真正留的是' in ir[0]['basis'], ir)
check('I 那份 1080p 照常被片名分组判可清理（4K 原盘留）', any(r['path'].startswith(H + '包') and '戊片' in r['path'] and r['stage'] == '重复副本'
                                                       and 'H' != r['cls'] and r['bucket'] == '可切' for r in rows), [r for r in rows if '戊片' in r['path']])
check('同一份不出两行', len(rows) == len({(r['path'], r['stage']) for r in rows}), len(rows))
check('统计：组数 / 多出份数 / 可清理份数', st.get('groups') == 5 and st.get('cut') == 6 and st.get('dup') == 6, st)
check('卡片成员里有门切的份', any(m['role'] == '可切' and '热浴盆' in m['path'] for g in gs.values() for m in g['members']), '')
jr = [r for r in rows if '庚片' in r['path'] or '庚片' in (r.get('film') or '')]
jset = [r for r in jr if r['bucket'] == '多碟合集']
check('J 三碟套进多碟合集一条（3 张、总大小）', len(jset) == 1 and jset[0]['disc_set'] == 3 and abs(jset[0]['gb'] - 255) < 0.1, jr)
check('J 剩下单碟里 4K DIY 当留、1080p 单碟可清理', any(r['bucket'] == '可切' and '1080p' in r['path'] and 'HDSky' in r['keep'] for r in jr)
      and not any('HDSky' in r['path'] for r in jr), jr)
kr = [r for r in rows if '辛片' in r['path']]
check('K 全是套的组：整组进多碟合集，没有别的判断', len(kr) == 2 and all(r['bucket'] == '多碟合集' for r in kr), kr)
lr = [r for r in rows if '壬片' in r['path'] and r['stage'] == '重复副本']
check('L 没并成套的 DISC.1 照老规矩（需人工确认）', any(r['bucket'] == '待定' for r in lr) and not any(r['bucket'] == '多碟合集' for r in lr), lr)
sr = {r['film']: r for r in rows if r['bucket'] == '多碟合集' and r.get('film')}
def setof(word):
    return [r for r in rows if r['bucket'] == '多碟合集' and any(word in pp for pp in r.get('parts') or [])]
check('32 天龙八部 / 倚天屠龙记分集不并套、也不被当同一部片切', not setof('天龙八部') and not setof('倚天屠龙记')
      and not any(('天龙八部' in r['path'] or '倚天屠龙记' in r['path']) and r['bucket'] == '可切' for r in rows),
      [r for r in rows if '天龙八部' in r['path'] or '倚天屠龙记' in r['path']])
check('32 莫斯科保卫战 Disc1 + Disc2 并成一套进多碟合集', len(setof('Moscow')) == 1 and setof('Moscow')[0]['disc_set'] == 2
      and not any('Moscow' in r['path'] and r['bucket'] == '待定' for r in rows), [r for r in rows if 'Moscow' in r['path']])
check('32 卡萨布兰卡 正片碟 + 花絮碟一套', len(setof('卡萨布兰卡')) == 1 and setof('卡萨布兰卡')[0]['disc_set'] == 2, setof('卡萨布兰卡'))
check('32 浩劫 Disc1 + Disc2 + 花絮碟三张一套', len(setof('浩劫')) == 1 and setof('浩劫')[0]['disc_set'] == 3
      and abs(setof('浩劫')[0]['gb'] - 135.3) < 0.1 and not any('花絮碟' in r['path'] and r['bucket'] != '多碟合集' for r in rows), [r for r in rows if '浩劫' in r['path']])
check('32 公民凯恩 花絮 1 + 花絮 2 一套', len(setof('公民凯恩')) == 1 and setof('公民凯恩')[0]['disc_set'] == 2, setof('公民凯恩'))
print('\nALL PASS' if not fails else '\nFAILED: %s' % fails)
sys.exit(1 if fails else 0)
