# TikTok IAA 数据抓取脚本

拉取所有游戏 × 所有地区的「营收 - 应用内广告 (IAA)」数据，输出一张按 **游戏 / 地区 / 日期** 区分的表，并可自动写入 BigQuery 数仓。

游戏列表默认从后台 API 自动获取（`app_id` + `key`），地区与日期在 `config.yaml` 配置。

## 给运营同学：最简用法（双击即可）

1. **第一次**：双击 `setup.command`，自动装好运行环境（联网，约 1-2 分钟）。
2. **以后每天**：双击 `run.command`，跑完自动打开结果文件夹。
3. 想让它**每天自动跑**：双击 `install_schedule.command`（默认每天 10:00 和 18:00 各一次），不想要了双击 `uninstall_schedule.command`。

运行结束会显示一个**摘要**（总收入、收入 Top 5、结果文件等）。若提示「登录态失效」，按提示在浏览器重新登录后台再跑一次即可。

## 指标

广告请求、广告曝光、广告点击、点击率(%)、eCPM、广告收入(USD)。

## 手动安装（开发者）

```bash
pip install -r requirements.txt
```

（本机没有现成 Python 时，可用 [uv](https://docs.astral.sh/uv/)：`uv venv --python 3.12 .venv && uv pip install -r requirements.txt`，再用 `.venv/bin/python scraper.py` 运行。）

## 配置

**首次使用**（或新机器克隆仓库后）：

```bash
cp config.example.yaml config.yaml
```

然后编辑 `config.yaml`，至少填入 `org_id`；若用 `cookie_source: config` 还需粘贴 `cookie`；若开启 BigQuery 还需配置 `bigquery` 段。

> `config.yaml` 含 Cookie 等敏感信息，已在 `.gitignore` 中排除，**不要提交**。配置结构变更请改仓库里的 `config.example.yaml`。

## 配置 `config.yaml`

1. **cookie_source**：默认 `browser`（从本机已登录浏览器自动读 Cookie）；也可设为 `config` 手动粘贴到 `cookie` 字段。失效时脚本会图文提示，并自动打开后台登录页。
2. **browser**（`cookie_source: browser` 时）：指定从哪个浏览器读 Cookie，如 `chrome`、`firefox`、`edge`、`safari`。**换浏览器只需改这一项**，并确保已在该浏览器登录 [开发者后台](https://developers.tiktok.com/)。
3. **games_source**：默认 `api`（从后台自动获取游戏列表 `app_id`+`key`，无需手动维护 CSV，新游戏自动纳入）；需配 `org_id`（后台 `organization/<数字>` 链接里的数字）。设为 `csv` 则读 `games_csv`。
   - `approved_only`：默认 `true`，只抓已过审游戏（接口 `app_status==1`）。
   - `exclude_games`：按游戏名或 app_id 排除不想统计的游戏。
   - 每次成功获取后写入快照 `games_cache_csv`（默认 `games_auto.csv`）；**下次 api 获取失败时自动回退读取该快照**。
4. **include_total**：默认 `true`，额外抓「全部地区」汇总（对应后台筛选条件=全部），地区列显示为 `total`。
5. **date / date_offset_days / days_back**：`date` 留空时自动抓最近 `days_back` 天（默认 2 = 昨天 + 前天），最新一天为「今天 - date_offset_days」。也可把 `date` 写成具体某天（如 `"2026-06-11"`，只抓那天）。
6. **game_status_filter**：仅 `games_source=csv` 生效，只抓这些状态的游戏，默认 `["已过审"]`。
7. **regions**：地区中文/英文名列表，脚本自动转地区码。
8. **限流相关**（多账号时尤其重要）：`concurrency`（默认 4）、`account_pause_seconds`（账号间暂停）、`failed_retry_rounds` / `failed_retry_pause_seconds` / `failed_retry_concurrency`（429 限流后自动补抓）。若日志仍出现大量 `429 Too Many Requests`，可把 `concurrency` 降到 2 或加大 `account_pause_seconds`。

### 自动同步游戏列表

`games_source: api` 时，每次运行会自动从后台拉取最新游戏。也可单独同步并导出到 CSV 查看：

```bash
python sync_games.py            # 写入 games_auto.csv
```

## 运行（命令行）

```bash
# 按 config 自动取日期（默认昨天 + 前天）
python scraper.py

# 指定单天
python scraper.py --date 2026-06-11

# 临时覆盖 Cookie 来源
python scraper.py --cookie-source config
```

## 补数（指定日期 / 区间）

写入 BigQuery 时按本次抓取的日期范围**先 delete 再 insert**，可重复跑，不会重复入库。

```bash
# 指定日期区间（推荐，补缺失的连续多天）
python scraper.py --start 2026-06-11 --end 2026-06-12

# 单天
python scraper.py --date 2026-06-11

# 从某天往前回溯 N 天（含当天）
python scraper.py --date 2026-06-12 --days 3
# → 补 2026-06-12、2026-06-11、2026-06-10
```

不带 `--start/--end/--date` 时，仍按 `config.yaml` 的 `date_offset_days` + `days_back` 抓默认窗口（定时任务走这条逻辑）。

结果写入 `output/iaa_<起>_<止>.csv`（单天时为 `output/iaa_<日期>.csv`），一张表。
列：`日期, 游戏, key, 地区, 广告请求, 广告曝光, 广告点击, 点击率(%), eCPM, 广告收入(USD)`，按游戏、地区、日期排序；地区为简写码（如 my、us），`total` 表示全部地区汇总。

## 写入 BigQuery 数仓

在 `config.yaml` 的 `bigquery` 配置：

```yaml
bigquery:
  enabled: true                         # true 开启；false 只生成本地 CSV
  credentials_json: "gzdw2024-d6b174f471ff.json"
  table_id: "gzdw2024.tt_game.ods_tt_game_revenue_crawler_di"
```

开启后，每次跑完会按本次抓取的日期范围**先 delete 再 insert**（可重复跑不会重复入库）。
字段映射：`stats_date / app_game / app_key / country / ad_requests / ad_impressions /
ad_clicks / ctr / ecpm / ad_revenue`，其中 `country` 为地区码、`ctr` 为原始比例(0~1)。

依赖：`pip install google-cloud-bigquery`。凭证文件含私钥，已在 `.gitignore` 中排除，切勿外传。

## 定时自动跑（macOS launchd）

双击 `install_schedule.command` 安装（默认每天 10:00 和 18:00 各一次；改时间编辑该文件顶部的 `TIMES`）。
日志写入 `logs/`，只保留最近 30 次。卸载双击 `uninstall_schedule.command`。

注意：定时运行无终端界面。若用 `cookie_source: browser`，需保持已在浏览器登录后台且授权过钥匙串访问；否则改用 `config` 手动 Cookie（但会过期）。

## 重要说明：数据延迟

TikTok 后台数据有延迟：**昨天 (T-1) 的数据当天下午往往还没出全，会返回 0**；
前天 (T-2) 的数据通常已完整。默认连前天一起抓（`days_back: 2`）即为此设计。

## 其它说明

- 某些地区对某些游戏返回 0，是因为该游戏在当地没有量（属正常）。
- 个别 (游戏,地区) 因无权限/无数据会被自动跳过，计入摘要的「跳过」数，不影响整体。
- `config.yaml`（含 Cookie）与服务账号密钥文件已在 `.gitignore` 中排除，切勿外传；配置模板见 `config.example.yaml`。
