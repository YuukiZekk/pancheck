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
    'data_source': 'scan',                      # scan=扫 CD2 挂载目录 + 读 Emby 库；csv=用现成五张 CSV
    'cd2_mount': os.environ.get('CD2_MOUNT', ''),       # CD2 挂载根（面板里的虚拟路径 "/" 对应这里）
    'cd2_config': os.environ.get('CD2_CONFIG', ''),     # CD2 配置目录（找 dir_cache.sqlite，只用于识别回显）
    'emby_data': os.environ.get('EMBY_DATA', ''),       # Emby data 目录（找 library.db）
    'emby_prefix': '/CloudNAS/CloudDrive',              # Emby 里看到的 CD2 挂载根路径
    'csv_dir': str(DATA_DIR / 'csv'),
    'min_video_mb': 100,                                # 小于此体积的视频（样片/预告）不计入
    # 分区映射（虚拟路径，如 /115/01-好康的/01-电影合集）
    'zones': {'heji': [], 'yuanpan': [], 'remux': []},
    # 保护（只能加；扫描时整枝剪掉，结果里命中则整批拒绝）
    'protect_names': [],                                # 系列合集 / 出品公司 / 已刮削 等目录名
    'listpack_names': ['豆瓣', 'IMDB', 'IMDb', '戛纳', 'Top250', 'Top 250'],
    'exclude_names': ['金庸', '动漫', 'ADWEB'],          # 第二/三刀与纵向不碰（内核已内置，这里可追加）
    'tv_keep_names': ['系列', '三部曲', '部曲'],          # 剧集分流时：路径含这些的视为系列电影，不分流
    # 第二期用
    'quarantine_dir': '',
}

# 内核写死的保护词，用户配置只能在此基础上加，不能删
BUILTIN_LISTPACK = ['豆瓣', 'IMDB', 'IMDb', '戛纳', 'Top250', 'Top 250']
BUILTIN_EXCLUDE = ['金庸', '动漫', 'ADWEB']


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
                  for k in ('heji', 'yuanpan', 'remux')}
    for k in ('protect_names', 'listpack_names', 'exclude_names', 'tv_keep_names'):
        c[k] = _merge_unique([], c.get(k))
    c['listpack_names'] = _merge_unique(BUILTIN_LISTPACK, c['listpack_names'])
    c['exclude_names'] = _merge_unique(BUILTIN_EXCLUDE, c['exclude_names'])
    c['min_video_mb'] = max(0, int(c.get('min_video_mb') or 0))
    c['data_source'] = 'csv' if c.get('data_source') == 'csv' else 'scan'
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
    keys = ('data_source', 'cd2_mount', 'emby_data', 'emby_prefix', 'csv_dir', 'min_video_mb', 'zones',
            'protect_names', 'listpack_names', 'exclude_names', 'tv_keep_names')
    blob = json.dumps({k: cfg.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode('utf-8')).hexdigest()[:12]
