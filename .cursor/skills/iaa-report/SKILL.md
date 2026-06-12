---
name: iaa-report
description: 拉取 TikTok 开发者后台「营收-应用内广告(IAA)」数据，按游戏/地区/日期生成 CSV 表。当用户要求抓取/拉取/导出 IAA、应用内广告、广告营收、TikTok 小游戏收入数据，或提到「拉昨天/前天的数据」时使用。
---

# 拉取 TikTok IAA 营收数据

运行本项目的 `scraper.py`，抓取所有游戏 × 配置地区的应用内广告数据，输出一张 CSV 表。游戏列表默认从后台接口自动获取（`games_source: api`），无需手动维护。

## 运行步骤

1. 确定日期：默认抓最近两天（昨天 + 前天，由 config 的 `date_offset_days`/`days_back` 控制）。用户要某一天用 `--date YYYY-MM-DD` 指定。
2. 在项目根目录执行（优先用项目自带虚拟环境）：

```bash
.venv/bin/python scraper.py
# 指定某天：
.venv/bin/python scraper.py --date YYYY-MM-DD
```

3. 全量约 14 游戏 × 11 地区（含「全部」total）× 2 天，并发跑通常 30-60 秒。完成后读取输出文件 `output/iaa_<起>_<止>.csv`（单天时为 `output/iaa_<日期>.csv`）。
4. 向用户汇报：输出文件路径 + 有数据（非 0 收入）的游戏/地区简要汇总（脚本结束也会打印摘要）。

## 常见情况处理

- **数据全是 0**：多半是后台数据延迟（昨天的数据当天还没出全）。提示用户改拉前天：`--date` 指定前天，或把 `config.yaml` 的 `date_offset_days` 改成 `2`。
- **报"登录态失效"**：Cookie 过期。让用户重新从浏览器复制 Cookie 到 `config.yaml`，或把 `cookie_source` 设为 `browser` 自动读取。
- **`.venv` 不存在**：用 `uv venv --python 3.12 .venv && uv pip install -r requirements.txt` 创建，或 `pip install -r requirements.txt` 后用 `python scraper.py`。
- **想单独刷新游戏列表**：运行 `python sync_games.py` 导出 `games_auto.csv` 查看（api 模式下抓数据时也会自动获取）。

## 输出表结构

列：`日期, 游戏, key, 地区, 广告请求, 广告曝光, 广告点击, 点击率(%), eCPM, 广告收入(USD)`，按游戏、地区、日期排序。地区为简写码（如 my、us），`total` 表示全部地区汇总（统计总收入时用 total 行，避免与各地区行重复相加）。
