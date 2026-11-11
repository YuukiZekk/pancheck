"""面板配置：存 DATA_DIR/config.json。Docker 下默认值由环境变量给出。"""
import hashlib
import json
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('SIEVE_DATA', APP_DIR / 'data')).resolve()
CONFIG_FILE = DATA_DIR / 'config.json'
RUNS_DIR = DATA_DIR / 'runs'

DEFAULTS = {
    # 数据源
    'data_source': 'cache',                     # cache=读 CD2 目录缓存（默认，零网盘请求）；scan=遍历挂载目录（兜底）；csv=现成五张 CSV
    'cd2_api_name': '115open',                  # 缓存里按网盘过滤（115 = 115open）
    'cd2_api_user': '',                         # 同一网盘多个账号时填账号标识；留空=该网盘全部账号
    'cd2_mount': os.environ.get('CD2_MOUNT', ''),       # CD2 挂载根（面板里的虚拟路径 "/" 对应这里）
    'cd2_config': os.environ.get('CD2_CONFIG', ''),     # CD2 配置目录（找 dir_cache.sqlite，只用于识别回显）
    'emby_data': os.environ.get('EMBY_DATA', ''),       # Emby data 目录（找 library.db）
    'emby_prefix': '/CloudNAS/CloudDrive',              # Emby 里看到的 CD2 挂载根路径
    'csv_dir': str(DATA_DIR / 'csv'),
    'min_video_mb': 100,                                # 小于此体积的视频（样片/预告）不计入
    # 分区映射（虚拟路径，如 /115/01-好康的/01-电影合集）
    # pack = 整夹合集区（如 10-合集）：按「单元」只参加跨区比对，不进内核三刀
    'zones': {'heji': [], 'yuanpan': [], 'remux': [], 'pack': []},
    # 保护（只能加；按目录组件匹配，扫描时剔除，可切里命中则整批拒绝）
    'protect_names': [],                                # 系列合集 / 出品公司 / 已刮削 等目录名
    'listpack_names': ['豆瓣', 'IMDB', 'IMDb', '戛纳', 'Top250', 'Top 250'],
    'exclude_names': ['金庸', '动漫', 'ADWEB'],          # 命中的副本不进可清理（可当保留份）；主库对比、孤本不碰（内置，这里可追加）
    'tv_keep_names': ['系列', '三部曲', '部曲'],          # 剧集分流时：路径含这些的视为系列电影，不分流
    'keep_first_names': [],                             # 重复时优先留这里（与保护目录同属一档）；只影响 A2，不剔除
    # 特效字幕组（反馈 16 / 18，号主确认的名单 + 查证过的别名）：名字命中即算特效字幕版，同分辨率内最优先留。
    # 明确不放：cXcY@FRDS、Yobee@Sunny、LGNB@oSpecialCN、泛化的 DIY@站点 标签；
    # 也不放裸「碟影」——会命中「碟影版原盘 / 碟影传媒」这类官方国版发行盘，只认做特效字幕的 WCL碟影
    'subfx_groups': ['SGNB', 'Thor@HDSky', '雅典娜', 'Athena@HDSky', 'x-man@HDSky', 'DIY@HDSky', 'Nest@ADWeb', 'Nest@ADE',
                     'Nimbus@Sunny', 'Breeze@Sunny', 'LINMENG@CHDBits', 'nn@CHDBits', 'sh@CHDBits', 'BHYS@OurBits',
                     '至尊宝', 'WCL碟影'],
    # 第二期用
    'quarantine_dir': '',                               # 排查区（「可清理」搬到这里；同一网盘内）
    'main_lib_dir': '',                                 # 主库目录（「主库缺口」挪入这里）
    'unique_dir': '',                                   # 唯一副本目录（缺口 × 唯一副本时可选的另一个去处）
    'exec_mode': 'auto',                                # 执行方式：auto（有 CD2 令牌走直连）/ cd2 / mount
    'cd2_api_addr': os.environ.get('CD2_API_ADDR', ''),  # CD2 接口地址（gRPC），如 192.168.1.10:19798
    # 首启向导是否走完（老配置：已绑过分区的视为走完）
    'setup_done': False,
}

ZONES = [('yuanpan', '原盘区'), ('heji', '合集区'), ('remux', 'REMUX 区'), ('pack', '整夹合集区')]

# 内核写死的保护词，用户配置只能在此基础上加，不能删
BUILTIN_LISTPACK = ['豆瓣', 'IMDB', 'IMDb', '戛纳', 'Top250', 'Top 250']
BUILTIN_EXCLUDE = ['金庸', '动漫', 'ADWEB']
# A2 保留档内置词（用户 2026-11-08 拍板：01/02-系列、11-出品公司、已刮削大包同属一档）。
# 只决定重复组里留哪份，不从比对人口里剔除——剔除名单另是 protect_names，两者分开，第一刀基线不受影响
BUILTIN_KEEP_FIRST = ['系列电影合集', '出品公司', '原盘已刮削']


def _merge_unique(base, extra):
    out = list(base)
    for x in extra or []:
        x = str(x).strip()
        if x and x not in out:
            out.append(x)
    return out


def normalize(cfg):
    c = json.loads(json.dumps(DEFAULTS))
    for k, v in (cfg or {}).items():
        if k in c:
            c[k] = v
    z = c.get('zones') or {}
    c['zones'] = {k: [('/' + p.strip().strip('/')) for p in (z.get(k) or []) if str(p).strip()]
                  for k in ('heji', 'yuanpan', 'remux', 'pack')}
    for k in ('protect_names', 'listpack_names', 'exclude_names', 'tv_keep_names', 'keep_first_names', 'subfx_groups'):
        c[k] = _merge_unique([], c.get(k))
    c['listpack_names'] = _merge_unique(BUILTIN_LISTPACK, c['listpack_names'])
    c['exclude_names'] = _merge_unique(BUILTIN_EXCLUDE, c['exclude_names'])
    c['keep_first_names'] = _merge_unique(BUILTIN_KEEP_FIRST, c['keep_first_names'])
    c['min_video_mb'] = max(0, int(c.get('min_video_mb') or 0))
    c['setup_done'] = bool((cfg or {}).get('setup_done')) or any(c['zones'].values())
    c['data_source'] = c.get('data_source') if c.get('data_source') in ('cache', 'scan', 'csv') else 'cache'
    c['cd2_api_name'] = str(c.get('cd2_api_name') or '115open').strip()
    c['cd2_api_user'] = str(c.get('cd2_api_user') or '').strip()
    return c


def load():
    if CONFIG_FILE.exists():
        try:
            return normalize(json.loads(CONFIG_FILE.read_text(encoding='utf-8')))
        except Exception:
            pass
    return normalize({})


def save(cfg):
    c = normalize(cfg)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, CONFIG_FILE)
    return c


def fingerprint(cfg):
    """影响判定的配置指纹：变了旧清单即作废。"""
    keys = ('data_source', 'cd2_mount', 'cd2_config', 'cd2_api_name', 'cd2_api_user', 'emby_data', 'emby_prefix', 'csv_dir', 'min_video_mb', 'zones',
            'protect_names', 'listpack_names', 'exclude_names', 'tv_keep_names', 'keep_first_names', 'subfx_groups')
    blob = json.dumps({k: cfg.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode('utf-8')).hexdigest()[:12]
