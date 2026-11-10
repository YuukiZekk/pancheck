# sieve 筛选面板

115 网盘影视低质筛选面板。内核是 `sieve.py`（原样未改），面板只是适配层 + 界面。

**当前版本：设置 → 盘点 → 筛选 → 清单导出，全程只读。** 只出清单，不会移动、改名或删除任何文件。
默认直接读 CloudDrive2 自己的目录缓存（`dir_cache.sqlite`），盘点不向网盘发请求。

## NAS 上用 Docker Compose 部署

```bash
mkdir sieve-panel && cd sieve-panel
curl -fsSLO https://raw.githubusercontent.com/YuukiZekk/pancheck/main/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/YuukiZekk/pancheck/main/.env.example -o .env
# 按 NAS 实际路径改 .env，然后：
docker compose up -d
```

镜像是预构建的（`ghcr.io/yuukizekk/pancheck`，amd64 / arm64），不用在 NAS 上编译。浏览器打开 `http://<NAS-IP>:8760`。

`.env` 里要改的：

| 变量 | 含义 |
|---|---|
| `CD2_CONFIG_HOST` | **必填**。CloudDrive2 的配置目录（里面有 `dir_cache.sqlite`，默认数据来源） |
| `EMBY_DATA_HOST` | **必填**。Emby 的 data 目录（里面有 `library.db`） |
| `PANEL_PASSWORD` | 访问口令，**强烈建议设置**；留空则局域网里谁都能打开。浏览器弹窗用户名随便填 |
| `CD2_MOUNT_HOST` | 可选。CloudDrive2 在宿主机上的挂载根，只有「遍历挂载目录」兜底模式才用 |
| `PANEL_PORT` | 端口，默认 8760 |

外部目录全部 **只读** 挂进容器；面板自己的配置和结果在 `./data`。

常用管理：

```bash
docker compose logs -f sieve-panel           # 看日志
docker compose pull && docker compose up -d  # 更新到最新版
docker compose down                          # 停止
```

## 使用流程

1. **设置**：路径已按 compose 预填。填「Emby 里看到的 CD2 挂载根」（Emby 库里文件路径的前缀，默认 `/CloudNAS/CloudDrive`），点「识别数据源」：核对缓存时间、115 的文件数、Emby 电影数和「路径在前缀下」的数量。
2. **盘点**：点「生成建议」按目录名自动给出分区和常见保护目录，勾选采用；也可以在目录树里手动点「合集 / 原盘 / REMUX / 保护」。然后「盘点」。
3. **筛选**：点「开始筛选」，跑错了可以随时点「停止」。结果分成下面几类：

   | 分类 | 是什么 | 能不能动 |
   |---|---|---|
   | 可清理 | 别处已有同一部片、画质更好或相同的副本，这份删了不会丢片 | 可移走（后续版本） |
   | 需人工确认 | 规则拿不准（画质没标注、体积对不上），请逐条判断 | 先别动 |
   | 不同版本 | DIY/特效字幕版与普通版，或剪辑版本不同 | 不要动 |
   | 这份更好 | 合集里这份比原盘区那份画质更高 | 不要动 |
   | 唯一副本 | 全库只有这一份 | 不要动 |
   | Emby 片库对比 | 库里没有的建议入库，库里版本更差的建议洗版 | 仅提醒 |
   | 混入的剧集 | 电影区里混进来的电视剧 | 仅提醒 |

   导出的 CSV 最后一列「内部分类」保留了内核叫法（可切/第一刀/A 等），方便和金标准对账。
4. **清单**：按分类、来源、关键字过滤，逐条看保留份和依据；导出 CSV 或全部 zip。

## 写进代码的红线

- 没有任何删除、移动、改名调用；第一期没有执行入口。
- CD2 缓存 / Emby 库以 SQLite 只读模式打开（打不开时拷快照到 `data/snapshot` 读副本）。
- 保护区、榜单包按目录组件匹配：扫描时剔除其下全部条目，可切里仍有命中则整批拒绝、可切类不许导出。文件名和「单片夹」夹名里的简介字样（如「豆瓣9.1分」）不算命中——单片夹指夹内只直接放着同一部片、且夹名含该片名的目录。
- 设置改动后旧结果自动过期（按配置指纹判断），「可清理」必须重新筛选才能导出。
- 内置的榜单/排除词不可删除；删除已有保护目录名需要显式勾选确认。

## 数据来源三种模式

- **读 CD2 目录缓存**（默认，推荐）：直接读 `dir_cache.sqlite`（只读），按网盘标识过滤（115 是 `115open`，同一网盘多账号时可再填账号标识），生成内核要的五张 CSV。几十万个目录也是秒级，**不向网盘发任何请求**。
  - 结果以**缓存时刻**为准：CD2 没打开过的目录不在缓存里，缓存之后新增/删除的文件也看不到。结果页会显示本次用到的缓存时间范围。想更新就先在 CD2 里把相关目录打开刷新一下，再重新筛选。
  - 和遍历挂载目录的结果逐条一致（同一份数据下生成的 CSV 逐字节相同）。
- **遍历 CD2 挂载目录**（兜底）：缓存不可用时才用。大库首跑很慢，而且每个目录都会经 CD2 向网盘发请求，有风控风险。不会自动切换到这个模式，需要你在设置里手动选。
- **CSV 模式**：把 `yuanpan_units.csv`、`yuanpan_files.csv`、`emby_yp.csv`、`heji_films.csv`、`emby_titles.csv` 放进 `data/csv/`，直接喂内核。适合用已验证过的金标准数据复核。

## 当前已知边界

- 已接入：第一刀、第二刀、第三刀、纵向轴（内核已对金标准验证），剧集分流（新写，**未对金标准**，仅出清单）。
- 未接入：REMUX 三分分层、REMUX × 原盘交叉、原盘精确重复——方案要求逐个收编实操脚本并对金标准，脚本到位后再补。REMUX 区目前只盘点。
- 缓存/遍历模式生成的 CSV 口径是按目录结构推断的（BDMV/VIDEO_TS 夹按一张盘计、合集「大包」= 分区下第一级目录），和手工导出的 CSV 可能有出入，首跑建议用 CSV 模式对一遍数。
- Emby 新版 `MediaItems.type` 若是数字，电影按「非剧集、非文件夹」推断，识别页会提示，请核对数量。

## 自己构建镜像

```bash
git clone https://github.com/YuukiZekk/pancheck.git && cd pancheck
docker build -t ghcr.io/yuukizekk/pancheck:latest .
docker compose up -d
```

## Windows 直接跑

```powershell
.\setup.ps1
.\start.ps1      # http://127.0.0.1:8760
```
