# dir_cache.sqlite 表结构与读取口径

来源：CloudDrive2 实际在用的缓存库（schema_version = 1），结构从真实库只读导出。
样例行已脱敏（路径中的片名打码），字段、类型、数值形态都是真的。

## 一、表结构（原文）

```sql
CREATE TABLE cached_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    insert_time INTEGER NOT NULL
);
-- 实测 158,646 行：被 CD2 列过的每个文件夹一行，path 是完整虚拟路径（如 /115/01-好康的/01-电影合集）

CREATE TABLE files (
    id TEXT NOT NULL,               -- 网盘侧文件 ID（115 的是纯数字字符串）
    parent_id INTEGER NOT NULL,     -- → cached_item.id，指向父文件夹
    name TEXT NOT NULL,             -- 文件名/文件夹名（不含路径）
    file_type INTEGER NOT NULL,     -- 3 = 文件夹，4 = 文件
    size INTEGER NOT NULL,          -- 字节；文件夹恒为 0
    create_time INTEGER NOT NULL,
    access_time INTEGER NOT NULL,
    write_time INTEGER NOT NULL,
    api_name TEXT NOT NULL,         -- 网盘标识：115 的是 '115open'（另有 LocalFsAPI 等）
    api_user TEXT NOT NULL,         -- 账号标识（数字字符串）
    thumbnail_url TEXT,
    preview_url TEXT,
    file_hash TEXT,                 -- JSON 字符串：{"Sha1":"35789F4..."}，实测全量有值
    custom_data TEXT,
    original_name TEXT NOT NULL,
    PRIMARY KEY (id, api_name, api_user)
);
-- 实测 2,295,873 行，其中 file_type=3 文件夹 156,154 行、file_type=4 文件 2,139,719 行

CREATE TABLE entry_properties (file_id TEXT, api_name TEXT, api_user TEXT, ...);  -- 实测 0 行，可忽略
CREATE TABLE metadata (key TEXT PRIMARY KEY, value INTEGER NOT NULL);              -- 实测 0 行，可忽略
CREATE TABLE schema_version (version INTEGER PRIMARY KEY);                         -- 1 行，值 1
```

## 二、样例行（脱敏）

```
cached_item:
  (10167481, '/115', 1794176739)
  (10168357, '/115/00-未整理/00-×××', 1794019896)

files（文件）:
  ('345495253437', 10168357, '[Search]×××.iso', 4, 45557448704, ..., '115open', '8000××××', '{"Sha1":"35789F4..."}')
  ('326842780031', 10369400, '×××.2025.2160p.WEB.SDR.HEVC.DDP5.1-××.mkv', 4, 15312795813, ...)

files（文件夹，size 恒 0）:
  ('312361897109', 10422401, '××× (2011) {tmdb-9364}', 3, 0, ...)
```

## 三、读取口径（照这个写，和手工流程一致）

1. **全路径靠 join 还原**：`files` 自己不存路径。文件全路径 = 父夹 `cached_item.path` + '/' + `files.name`：
   ```sql
   SELECT ci.path, f.name, f.file_type, f.size
   FROM files f JOIN cached_item ci ON ci.id = f.parent_id
   WHERE f.api_name = '115open'
   ```
   根目录的 `cached_item.path` 是 '/'，拼接时注意别出双斜杠。
2. **只认目标网盘**：一个缓存库可能混多个网盘/账号，必须按 `api_name`（115 是 `115open`）过滤，必要时再按 `api_user` 区分账号。
3. **文件夹没有大小**：`file_type=3` 的行 size 恒 0，体积只能汇总其下 `file_type=4` 的行。文件夹同时出现在两张表里：`files` 里有一行（记它的父级），`cached_item` 里有一行（记它自己的路径和缓存时间）。
4. **分区过滤按路径前缀**：zones 配置的是虚拟路径前缀（如 `/115/01-好康的/01-电影合集`），对 join 出的全路径做前缀匹配即可，不用遍历挂载目录。
5. **五张 CSV 的派生**：
   - `heji_films.csv`：合集区前缀下的 file_type=4 视频文件行；「大包」= 分区根下第一级目录名；形态按扩展名，父链含 BDMV 目录的按盘处理。
   - `yuanpan_units.csv` / `yuanpan_files.csv`：原盘区同理，files 给逐文件行，units 按文件夹聚合（内核会自己再展开到片级）。
   - `emby_*.csv`：与缓存无关，仍读 Emby library.db（现有实现即可）。
6. **时效性**：缓存是「CD2 列到哪算哪」的采样 — 没被列过的目录不在库里；`insert_time` 是该文件夹的缓存时刻（epoch 秒），各目录新旧不一。面板应在结果里回显本次用到的缓存时间范围（min/max insert_time），并提示「结果以缓存时刻为准」。手工流程里多份快照是按文件夹取最新一份合并的；读活库时只有一份，不需要合并。
7. **只读打开**：库带 WAL — 用 `mode=ro` 打开时把 `-wal` 文件留在原地一起读，或把 `.sqlite` + `-wal` 一起拷走再读；不要只拷主文件，会丢未落盘页。
8. **附带红利（可选，不属本轮）**：`file_hash` 里有真实 Sha1 — 以后做「同字节重复」的精确版时，可以用它替代大小指纹。本轮缓存优先只做盘点数据源替换，不动判定。
