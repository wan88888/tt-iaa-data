# TikTok IAA 数据抓取脚本

每天执行一次，拉取所有游戏 × 所有地区的「营收 - 应用内广告 (IAA)」数据，
输出一张按 **游戏 / 地区** 区分的表：`output/iaa_<日期>.csv`。

游戏列表读自游戏信息表 CSV（`游戏全称` / `app_id` / `key` 等列），
地区与日期在 `config.yaml` 配置。

## 指标

广告请求 `广告请求`、广告曝光 `广告曝光`、广告点击 `广告点击`、点击率 `点击率(%)`、`eCPM`、广告收入 `广告收入(USD)`。

## 安装

```bash
pip install -r requirements.txt
```

（本机没有现成 Python 时，可用 [uv](https://docs.astral.sh/uv/)：`uv venv --python 3.12 .venv && uv pip install -r requirements.txt`，再用 `.venv/bin/python scraper.py` 运行。）

## 配置 `config.yaml`

1. **cookie**：开发者后台页面按 `F12` → `Network` → 找到 `iaa` 请求 → 右键 `Copy` → `Copy as cURL`，把 `-b '...'` 引号内的内容粘进 `cookie`。Cookie 会过期，失效时重新复制。
2. **date / date_offset_days / days_back**：`date` 留空时自动抓最近 `days_back` 天（默认 2 = 昨天 + 前天），最新一天为「今天 - date_offset_days」。也可把 `date` 写成具体某天（如 `"2026-06-11"`，只抓那天）。
3. **games_csv**：游戏信息表路径（默认 `游戏信息表 - TT.csv`）。
4. **game_status_filter**：只抓这些状态的游戏，默认 `["已过审"]`（`开发中` 的游戏一般没数据）。
5. **regions**：地区中文/英文名列表，脚本自动转地区码。

## 运行

```bash
# 按 config 自动取日期（默认昨天）
python scraper.py

# 指定某一天
python scraper.py --date 2026-06-10
```

结果写入 `output/iaa_<起>_<止>.csv`（单天时为 `output/iaa_<日期>.csv`），一张表。
列：`日期, 游戏, key, 地区, 广告请求, 广告曝光, 广告点击, 点击率(%), eCPM, 广告收入(USD)`，按游戏、地区、日期排序；地区为简写码（如 my、us）。

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

## 重要说明：数据延迟

TikTok 后台数据有延迟：**昨天 (T-1) 的数据当天下午往往还没出全，会返回 0**；
前天 (T-2) 的数据通常已完整。若发现昨天全是 0，可在 `config.yaml` 把
`date_offset_days` 改为 `2`（拉前天），或晚点再跑。

## 其它说明

- 某些地区对某些游戏返回 0，是因为该游戏在当地没有量（属正常）。
- 个别 (游戏,地区) 因无权限/无数据会被自动跳过并记录日志，不影响整体。
- `config.yaml` 含真实登录 Cookie（等同账号凭证），已在 `.gitignore` 中排除，切勿外传。
