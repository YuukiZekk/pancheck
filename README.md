# sieve 筛选面板

115 网盘影视低质筛选面板。内核是 `sieve.py`（原样未改），面板只是适配层 + 界面。

**第一期（当前）：设置 → 盘点 → 跑筛 → 清单导出，全程只读。** 没有批准/搬运/删除入口。

## NAS 上用 Docker Compose 部署

```bash
cp .env.example .env      # 按 NAS 实际路径改 .env
docker compose up -d --build
```

浏览器打开 `http://<NAS-IP>:8760`。

`.env` 里要改的：

| 变量 | 含义 |
|---|---|
| `CD2_MOUNT_HOST` | CloudDrive2 在宿主机上的挂载根（`ls` 能看到 115 目录的那一层） |
| `EMBY_DATA_HOST` | Emby 的 data 目录（里面有 `library.db`） |
| `CD2_CONFIG_HOST` | CD2 配置目录（有 `dir_cache.sqlite`，只用于识别回显，可不填） |
| `PANEL_PASSWORD` | 访问口令，留空不设；浏览器弹窗用户名随便填 |
| `PANEL_PORT` | 端口，默认 8760 |

三个外部目录全部 **只读** 挂进容器；面板自己的配置和结果在 `./data`。

常用管理：

```bash
docker compose logs -f sieve-panel     # 看日志
docker compose up -d --build           # 更新代码后重建
docker compose down                    # 停止
```

## 使用流程

1. **设置**：路径已按 compose 预填（`/media/cd2`、`/emby-data` …）。填「Emby 里看到的 CD2 挂载根」（Emby 库里文件路径的前缀，默认 `/CloudNAS/CloudDrive`），点「识别数据源」核对电影数和「路径在前缀下」的数量。
2. **盘点**：在目录树里给目录点「合集 / 原盘 / REMUX」加入分区，点「保护」把目录名加入保护区，然后「盘点」。
3. **筛选**：「一键跑筛」。结果分 可切 / 待定 / 版本型 / 不动 / 孤本 / 提醒 / 剧集分流。
4. **清单**：按分类、来源、关键字过滤，逐条看保留份和依据；导出 CSV 或全部 zip。

## 写进代码的红线

- 没有任何删除、移动、改名调用；第一期没有执行入口。
- CD2 缓存 / Emby 库以 SQLite 只读模式打开（打不开时拷快照到 `data/snapshot` 读副本）。
- 保护区、榜单包在扫描时整枝剪掉；若「可切」里仍有命中，整批拒绝、可切类不许导出。
- 配置改动后旧清单自动作废（按配置指纹判断），可切类必须重跑才能导出。
- 内置的榜单/排除词不可删除；删除已有保护目录名需要显式勾选确认。

## 数据来源两种模式

- **扫描模式**（默认）：扫 CD2 挂载目录（只 listdir/stat）+ 读 Emby `library.db`，自动生成内核要的五张 CSV。
- **CSV 模式**：把 `yuanpan_units.csv`、`yuanpan_files.csv`、`emby_yp.csv`、`heji_films.csv`、`emby_titles.csv` 放进 `data/csv/`，直接喂内核。适合用已验证过的金标准数据复核。

## 当前已知边界

- 已接入：第一刀、第二刀、第三刀、纵向轴（内核已对金标准验证），剧集分流（新写，**未对金标准**，仅出清单）。
- 未接入：REMUX 三分分层、REMUX × 原盘交叉、原盘精确重复——方案要求逐个收编实操脚本并对金标准，脚本到位后再补。REMUX 区目前只盘点。
- 扫描模式生成的 CSV 口径是按目录结构推断的（BDMV/VIDEO_TS 夹按一张盘计、合集「大包」= 分区下第一级目录），和手工导出的 CSV 可能有出入，首跑建议用 CSV 模式对一遍数。
- Emby 新版 `MediaItems.type` 若是数字，电影按「非剧集、非文件夹」推断，识别页会提示，请核对数量。

## Windows 直接跑

```powershell
.\setup.ps1
.\start.ps1      # http://127.0.0.1:8760
```
