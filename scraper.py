#!/usr/bin/env python3
"""TikTok 开发者后台 IAA(应用内广告) 数据抓取脚本。

每天执行一次，拉取「昨天」所有游戏 x 所有地区的 IAA 数据，
输出一张按 游戏 / 地区 区分的表 (output/iaa_<日期>.csv)。
配置见 config.yaml，游戏列表读自 config 里指定的游戏信息表 CSV。
"""

import argparse
import csv
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://developers.us.tiktok.com/tiktok/v1/data_orchestor/minigame/analytics/iaa"

# 响应里的指标字段（顺序即输出顺序）
METRICS = [
    "ads_request",
    "ads_exposure",
    "ads_click",
    "ads_click_rate",
    "ecpm",
    "iaa_revenue",
]

# 指标 -> 中文表头
METRIC_HEADERS = {
    "ads_request": "广告请求",
    "ads_exposure": "广告曝光",
    "ads_click": "广告点击",
    "ads_click_rate": "点击率(%)",
    "ecpm": "eCPM",
    "iaa_revenue": "广告收入(USD)",
}

# 地区中文/英文名 -> 地区码（小写 ISO-3166 alpha-2）
REGION_NAME_TO_CODE = {
    "united states": "us",
    "japan": "jp",
    "indonesia": "id",
    "thailand": "th",
    "philippines": "ph",
    "vietnam": "vn",
    "malaysia": "my",
    "brazil": "br",
    "saudi arabia": "sa",
    "turkey": "tr",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("iaa")


class LoginExpiredError(RuntimeError):
    """Cookie 失效 / 未登录（需要中止整个任务）。"""


class DataUnavailableError(RuntimeError):
    """单个(游戏,地区)无数据/无权限（跳过即可，不中止）。"""


def load_config(path: Path) -> dict:
    if not path.exists():
        logger.error("找不到配置文件: %s", path)
        sys.exit(1)
    with path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if not (cfg.get("regions") or []):
        logger.error("config.yaml 未配置任何 regions。")
        sys.exit(1)

    source = (cfg.get("games_source") or "csv").strip().lower()
    if source == "csv" and not (cfg.get("games_csv") or "").strip():
        logger.error("games_source=csv 时必须配置 games_csv（游戏信息表路径）。")
        sys.exit(1)
    if source == "api" and not str(cfg.get("org_id") or "").strip():
        logger.error("games_source=api 时必须配置 org_id（组织 ID）。")
        sys.exit(1)

    return cfg


def get_cookie_string(cfg: dict) -> str:
    """获取 Cookie：cookie_source=config 用配置里的字符串；=browser 从本机浏览器读。"""
    source = (cfg.get("cookie_source") or "config").strip().lower()

    if source == "browser":
        browser = (cfg.get("browser") or "chrome").strip().lower()
        try:
            import browser_cookie3
        except ImportError:
            logger.error("cookie_source=browser 需要安装依赖：pip install browser-cookie3")
            sys.exit(1)
        loader = getattr(browser_cookie3, browser, None)
        if loader is None:
            logger.error("不支持的 browser='%s'（可选 chrome/edge/firefox/safari 等）。", browser)
            sys.exit(1)
        try:
            jar = loader(domain_name="tiktok.com")
        except Exception as exc:  # noqa: BLE001 浏览器读取失败原因多样，统一提示
            logger.error("从浏览器读取 Cookie 失败：%s", exc)
            logger.error("请确认已在该浏览器登录开发者后台，且授权了钥匙串访问。")
            sys.exit(1)
        pairs = [f"{c.name}={c.value}" for c in jar]
        cookie = "; ".join(pairs)
        if "sessionid" not in cookie:
            logger.error("浏览器里没读到登录态(sessionid)，请确认已在浏览器登录开发者后台。")
            sys.exit(1)
        logger.info("已从浏览器(%s)读取 Cookie。", browser)
        return cookie

    cookie = (cfg.get("cookie") or "").strip()
    if not cookie or "sessionid" not in cookie:
        logger.error("config.yaml 的 cookie 未填写或不完整，请从浏览器复制完整 Cookie。")
        sys.exit(1)
    return cookie


def _parse_date(raw: str) -> date:
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        logger.error("日期格式应为 YYYY-MM-DD，收到: %s", raw)
        sys.exit(1)


def resolve_dates(
    cfg: dict,
    cli_date: str | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
    days: int | None = None,
) -> list[str]:
    """确定抓取日期列表（按时间从新到旧返回）。

    优先级：
    1. --start/--end 区间（补数用）：返回区间内每一天（含两端）。
    2. --date 单天（可配合 --days 往前回溯 N 天）。
    3. config.date 单天。
    4. 默认：最近 days_back 天，最新一天为 今天 - date_offset_days。

    注意：TikTok 后台数据有延迟，昨天(T-1)当天往往还未出全，故默认连前天一起抓。
    """
    # 1) 区间
    if start or end:
        if not (start and end):
            logger.error("--start 与 --end 必须同时指定。")
            sys.exit(1)
        d0, d1 = _parse_date(start), _parse_date(end)
        if d0 > d1:
            d0, d1 = d1, d0
        span = (d1 - d0).days
        return [(d1 - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(span + 1)]

    # 2/3) 单天（可带 days 回溯）
    raw = (cli_date or str(cfg.get("date") or "")).strip()
    if raw:
        latest = _parse_date(raw)
        n = max(int(days), 1) if days else 1
        return [(latest - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]

    # 4) 默认窗口
    offset = int(cfg.get("date_offset_days", 1))
    days_back = max(int(days) if days else int(cfg.get("days_back", 2)), 1)
    latest = date.today() - timedelta(days=offset)
    return [(latest - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_back)]


def resolve_regions(cfg: dict) -> list[tuple[str, str]]:
    """把配置里的地区名解析为 (显示名, 地区码) 列表。

    include_total=true 时追加一项「全部」(code=total)：请求不带 region 参数，
    对应后台「筛选条件=全部」的汇总数据。
    """
    result = []
    if cfg.get("include_total", True):
        result.append(("全部(total)", "total"))
    for name in cfg["regions"]:
        name = str(name).strip()
        code = REGION_NAME_TO_CODE.get(name.lower())
        if not code:
            logger.warning("未知地区 '%s'，已跳过（可在 REGION_NAME_TO_CODE 中补充）。", name)
            continue
        result.append((name, code))
    if not result:
        logger.error("没有可用地区。")
        sys.exit(1)
    return result


def load_games(csv_path: Path, status_filter: list[str]) -> list[dict]:
    """读取游戏信息表，返回 [{name, app_id, client_key, status}, ...]。"""
    if not csv_path.exists():
        logger.error("找不到游戏信息表: %s", csv_path)
        sys.exit(1)

    games = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("游戏全称") or "").strip()
            client_key = (row.get("key") or "").strip()
            app_id = (row.get("app_id") or "").strip()
            status = (row.get("游戏状态") or "").strip()
            if not client_key or not name:
                continue
            if status_filter and status not in status_filter:
                continue
            games.append(
                {
                    "name": name,
                    "app_id": app_id,
                    "client_key": client_key,
                    "status": status,
                }
            )
    if not games:
        logger.error("游戏信息表中没有匹配的游戏（检查 game_status_filter / key 列）。")
        sys.exit(1)
    return games


def resolve_games(cfg: dict, session) -> list[dict]:
    """根据 games_source 选择游戏来源。

    - api：从后台接口自动获取（app_id + client_key），无需手动维护 CSV；
           失败时若存在 games_csv 则回退到 CSV。
    - csv：读取游戏信息表（默认行为，可用 game_status_filter 过滤状态）。
    """
    source = (cfg.get("games_source") or "csv").strip().lower()
    if source == "api":
        import sync_games

        org_id = str(cfg.get("org_id") or "").strip()
        cache_path = Path((cfg.get("games_cache_csv") or "games_auto.csv").strip())
        try:
            api_games = sync_games.fetch_games_from_api(
                session,
                org_id,
                concurrency=max(int(cfg.get("concurrency", 8)), 1),
                exclude=cfg.get("exclude_games"),
                approved_only=cfg.get("approved_only", True),
            )
        except Exception as exc:  # noqa: BLE001 网络/登录等多种原因
            logger.error("从后台自动获取游戏列表失败：%s", exc)
            api_games = []
        if api_games:
            logger.info("已从后台自动获取 %d 个游戏。", len(api_games))
            # 成功则更新本地快照，供下次失败时回退
            try:
                sync_games.write_games_csv(api_games, cache_path)
            except OSError as exc:
                logger.warning("写入游戏快照 %s 失败：%s", cache_path, exc)
            return [
                {
                    "name": g["name"],
                    "app_id": g["app_id"],
                    "client_key": g["client_key"],
                    "status": "",
                }
                for g in api_games
            ]
        # 回退：读取上次成功保存的快照 games_auto.csv
        if cache_path.exists():
            logger.warning("自动获取失败，回退到上次快照：%s", cache_path)
            return load_games(cache_path, [])
        logger.error(
            "自动获取游戏失败，且没有可回退的快照 %s，请检查登录态/org_id。", cache_path
        )
        sys.exit(2)

    return load_games(Path(cfg["games_csv"]), cfg.get("game_status_filter") or [])


def build_session(cookie: str, *, concurrency: int = 1, max_retries: int = 2) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=max(concurrency, 1),
        pool_maxsize=max(concurrency, 1),
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "priority": "u=1, i",
            "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36"
            ),
            "Cookie": cookie,
        }
    )
    return session


def build_referer(app_id: str) -> str:
    return (
        f"https://developers.us.tiktok.com/portal/us/game/{app_id}"
        "/monetization?tab=iaa&__row_locale=zh-Hans"
    )


def fetch_iaa(
    session: requests.Session,
    *,
    client_key: str,
    app_id: str,
    day: str,
    region_code: str,
    ad_type: int,
) -> dict:
    """请求单个(游戏, 地区, 单日)的 IAA 数据。start_time=end_time=day。

    region_code 为 "total"（或空）时省略 region 参数，即后台「筛选条件=全部」。
    """
    params = {
        "client_key": client_key,
        "start_time": day,
        "end_time": day,
        "ad_type": ad_type,
    }
    if region_code and region_code != "total":
        params["region"] = region_code
    headers = {"referer": build_referer(app_id)}
    resp = session.get(API_URL, params=params, headers=headers, timeout=30)

    if resp.status_code in (401, 403):
        raise LoginExpiredError(f"HTTP {resp.status_code}，登录态可能失效")
    resp.raise_for_status()

    try:
        data = resp.json()
    except ValueError:
        snippet = resp.text[:200].replace("\n", " ")
        raise LoginExpiredError(f"响应不是 JSON，可能登录失效。内容片段: {snippet}")

    if "iaa_data" not in data:
        code = data.get("code")
        message = data.get("message") or data.get("msg")
        # 单游戏无权限/无数据：跳过，不中止全局
        raise DataUnavailableError(f"无 iaa_data (code={code}, message={message})")

    return data


def _round(value, ndigits):
    if value is None:
        return None
    try:
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return value


def build_row(data: dict, *, day: str, game: str, key: str, region_code: str) -> dict:
    """从 iaa_data 汇总构造一行（单日）。地区显示简写(region_code)，并带 key 列。"""
    iaa = data.get("iaa_data") or {}
    row = {"日期": day, "游戏": game, "key": key, "地区": region_code}
    for metric in METRICS:
        value = (iaa.get(metric) or {}).get("value")
        if metric == "ads_click_rate":
            value = _round((value or 0) * 100, 2)  # 转百分比
        elif metric in ("ecpm",):
            value = _round(value, 3)
        elif metric == "iaa_revenue":
            value = _round(value, 2)
        else:
            value = int(value) if value is not None else 0
        row[METRIC_HEADERS[metric]] = value
    return row


def build_bq_record(data: dict, *, day: str, game: str, key: str, region_code: str) -> dict:
    """构造 BigQuery 一行，字段名对齐数仓表；ctr 用原始比例(0~1)。"""
    iaa = data.get("iaa_data") or {}

    def val(metric):
        return (iaa.get(metric) or {}).get("value")

    return {
        "stats_date": day,  # "YYYY-MM-DD"，BigQuery DATE 接受该字符串
        "app_game": game,
        "app_key": key,
        "country": region_code,
        "ad_requests": int(val("ads_request") or 0),
        "ad_impressions": int(val("ads_exposure") or 0),
        "ad_clicks": int(val("ads_click") or 0),
        "ctr": _round(val("ads_click_rate") or 0, 6),
        "ecpm": _round(val("ecpm") or 0, 4),
        "ad_revenue": _round(val("iaa_revenue") or 0, 4),
    }


def write_csv(path: Path, fieldnames: list, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _do_one(session, game, region, day, ad_type, abort_event):
    """单个(游戏, 地区)的抓取任务。返回 (status, payload)。"""
    region_name, region_code = region
    if abort_event.is_set():
        return ("aborted", None)
    try:
        data = fetch_iaa(
            session,
            client_key=game["client_key"],
            app_id=game["app_id"],
            day=day,
            region_code=region_code,
            ad_type=ad_type,
        )
    except LoginExpiredError as exc:
        abort_event.set()
        return ("login", exc)
    except DataUnavailableError as exc:
        return ("nodata", exc)
    except requests.RequestException as exc:
        return ("failed", exc)
    row = build_row(
        data, day=day, game=game["name"], key=game["client_key"], region_code=region_code
    )
    bq = build_bq_record(
        data, day=day, game=game["name"], key=game["client_key"], region_code=region_code
    )
    return ("ok", (row, bq))


BQ_SCHEMA_FIELDS = [
    ("stats_date", "DATE", "REQUIRED"),
    ("app_game", "STRING", "NULLABLE"),
    ("app_key", "STRING", "NULLABLE"),
    ("country", "STRING", "NULLABLE"),
    ("ad_requests", "INTEGER", "NULLABLE"),
    ("ad_impressions", "INTEGER", "NULLABLE"),
    ("ad_clicks", "INTEGER", "NULLABLE"),
    ("ctr", "FLOAT", "NULLABLE"),
    ("ecpm", "FLOAT", "NULLABLE"),
    ("ad_revenue", "FLOAT", "NULLABLE"),
]


def upload_to_bigquery(records: list, days: list, bq_cfg: dict):
    """delete-then-insert：先删指定日期范围，再追加写入本次抓取数据。"""
    try:
        from google.cloud import bigquery
    except ImportError:
        logger.error("写入 BigQuery 需要安装依赖：pip install google-cloud-bigquery")
        sys.exit(4)

    creds = (bq_cfg.get("credentials_json") or "").strip()
    table_id = (bq_cfg.get("table_id") or "").strip()
    if not creds or not table_id:
        logger.error("bigquery 配置缺少 credentials_json 或 table_id。")
        sys.exit(4)
    if not Path(creds).exists():
        logger.error("找不到 BigQuery 凭证文件：%s", creds)
        sys.exit(4)

    client = bigquery.Client.from_service_account_json(creds)

    start_date, end_date = min(days), max(days)
    logger.info("BigQuery: 先删除 %s ~ %s 的旧数据 …", start_date, end_date)
    delete_sql = (
        f"DELETE FROM `{table_id}` "
        "WHERE stats_date >= @start_date AND stats_date <= @end_date"
    )
    delete_cfg = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )
    client.query(delete_sql, job_config=delete_cfg).result()

    logger.info("BigQuery: 写入 %d 行 …", len(records))
    schema = [bigquery.SchemaField(n, t, mode=m) for n, t, m in BQ_SCHEMA_FIELDS]
    load_cfg = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_APPEND")
    job = client.load_table_from_json(records, table_id, job_config=load_cfg)
    job.result()
    logger.info("BigQuery: 完成，已写入 %s。", table_id)


class ProgressBar:
    """简单的终端进度条；非 TTY 环境（如定时任务）自动降级为不输出。"""

    def __init__(self, total: int, width: int = 32):
        self.total = total
        self.width = width
        self.done = 0
        self.enabled = sys.stderr.isatty()

    def update(self, n: int = 1):
        self.done += n
        if not self.enabled:
            return
        frac = self.done / self.total if self.total else 1.0
        filled = int(self.width * frac)
        bar = "#" * filled + "-" * (self.width - filled)
        sys.stderr.write(f"\r  进度 [{bar}] {self.done}/{self.total} ({frac*100:4.0f}%)")
        sys.stderr.flush()

    def close(self):
        if self.enabled:
            sys.stderr.write("\n")
            sys.stderr.flush()


PORTAL_URL = "https://developers.us.tiktok.com/"


def handle_login_failure(cfg: dict):
    """登录失效时给出图文化指引，并按配置自动打开后台登录页。"""
    source = (cfg.get("cookie_source") or "config").strip().lower()
    logger.error("=" * 56)
    logger.error("  登录态已失效（Cookie 过期或未登录），无法获取数据。")
    logger.error("=" * 56)
    if source == "browser":
        browser = cfg.get("browser") or "chrome"
        logger.error("  解决方法（当前为浏览器自动读取模式）：")
        logger.error("   1) 在 %s 浏览器里打开并登录 TikTok 开发者后台", browser)
        logger.error("   2) 确认能正常看到营收页面后，重新运行本工具即可")
    else:
        logger.error("  解决方法（当前为手动 Cookie 模式）：")
        logger.error("   1) 浏览器登录开发者后台 -> F12 -> Network -> 找到 iaa 请求")
        logger.error("   2) 右键 Copy -> Copy as cURL，复制其中 -b '...' 的内容")
        logger.error("   3) 粘贴到 config.yaml 的 cookie 字段后，重新运行")
        logger.error("   （也可把 cookie_source 改为 browser，自动从已登录浏览器读取）")
    if cfg.get("open_login_on_expire", True) and sys.stderr.isatty():
        import subprocess

        try:
            subprocess.run(["open", PORTAL_URL], check=False)
            logger.error("  已为你打开后台登录页：%s", PORTAL_URL)
        except Exception:  # noqa: BLE001
            logger.error("  请手动打开后台登录：%s", PORTAL_URL)
    else:
        logger.error("  后台地址：%s", PORTAL_URL)
    logger.error("=" * 56)


def print_summary(*, days, rows, skipped, failed, failures, out_path, bq_enabled):
    """结束时打印关键数字摘要。"""
    total_rows = [r for r in rows if r["地区"] == "total"]
    region_rows = [r for r in rows if r["地区"] != "total"]
    # 真实总收入：有 total 行时用 total 行（避免与各地区行重复计），否则用各地区行
    rev_basis = total_rows if total_rows else region_rows
    total_rev = sum((r.get("广告收入(USD)") or 0) for r in rev_basis)
    nonzero = [r for r in rows if (r.get("广告收入(USD)") or 0) > 0]

    # 收入 Top 5（具体游戏@地区，排除 total 行避免重复）
    top = sorted(region_rows, key=lambda r: (r.get("广告收入(USD)") or 0), reverse=True)[:5]

    lines = []
    lines.append("")
    lines.append("=" * 56)
    lines.append("  抓取完成 ✓  摘要")
    lines.append("-" * 56)
    lines.append(f"  日期范围   : {', '.join(days)}")
    lines.append(f"  数据行数   : {len(rows)}（其中有收入 {len(nonzero)} 行）")
    lines.append(f"  总广告收入 : ${total_rev:,.2f}")
    if skipped:
        lines.append(f"  跳过(无数据): {skipped}")
    if failed:
        lines.append(f"  请求失败   : {failed}")
    lines.append(f"  结果文件   : {out_path}")
    lines.append(f"  写入数仓   : {'是' if bq_enabled else '否'}")
    if top and (top[0].get("广告收入(USD)") or 0) > 0:
        lines.append("-" * 56)
        lines.append("  收入 Top 5（游戏 @ 地区 @ 日期）：")
        for r in top:
            rev = r.get("广告收入(USD)") or 0
            if rev <= 0:
                break
            lines.append(
                f"    ${rev:>10,.2f}  {r['游戏']} @ {r['地区']} @ {r['日期']}"
            )
    if failures:
        lines.append("-" * 56)
        lines.append("  失败明细（最多显示 10 条）：")
        for g, rn, d, msg in failures[:10]:
            lines.append(f"    {g} @ {rn} @ {d}: {msg}")
    lines.append("=" * 56)
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="抓取 TikTok 开发者后台 IAA 数据")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--output-dir", default="output", help="CSV 输出目录")
    parser.add_argument("--date", default=None, help="抓取单天 YYYY-MM-DD（默认昨天+前天）")
    parser.add_argument("--start", default=None, help="补数起始日 YYYY-MM-DD（需配合 --end）")
    parser.add_argument("--end", default=None, help="补数结束日 YYYY-MM-DD（需配合 --start）")
    parser.add_argument(
        "--days", type=int, default=None, help="往前回溯的天数（配合 --date 或默认窗口）"
    )
    parser.add_argument(
        "--cookie-source",
        default=None,
        choices=["config", "browser"],
        help="覆盖 config 的 cookie_source（config=手动粘贴 / browser=从浏览器读）",
    )
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    if args.cookie_source:
        cfg["cookie_source"] = args.cookie_source

    cookie = get_cookie_string(cfg)
    days = resolve_dates(cfg, args.date, start=args.start, end=args.end, days=args.days)
    ad_type = int(cfg.get("ad_type", 1))
    concurrency = max(int(cfg.get("concurrency", 8)), 1)
    max_retries = int(cfg.get("max_retries", 2))
    regions = resolve_regions(cfg)

    session = build_session(cookie, concurrency=concurrency, max_retries=max_retries)
    games = resolve_games(cfg, session)

    total = len(games) * len(regions) * len(days)
    logger.info(
        "抓取日期=%s | 游戏 %d 个 | 地区 %d 个（含全部） | 共 %d 个请求 | 并发 %d",
        ",".join(days),
        len(games),
        len(regions),
        total,
        concurrency,
    )

    tasks = [(game, region, day) for day in days for game in games for region in regions]
    abort_event = threading.Event()
    rows: list = []
    bq_records: list = []
    failures: list = []  # (game, region_name, day, msg)
    skipped = 0
    failed = 0
    login_failed = False

    bar = ProgressBar(total)
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_do_one, session, game, region, day, ad_type, abort_event): (
                game,
                region,
                day,
            )
            for game, region, day in tasks
        }
        for future in as_completed(futures):
            game, region, day = futures[future]
            region_name = region[0]
            status, payload = future.result()
            if status == "ok":
                row, bq = payload
                rows.append(row)
                bq_records.append(bq)
            elif status == "nodata":
                skipped += 1
            elif status == "failed":
                failed += 1
                failures.append((game["name"], region_name, day, str(payload)))
            elif status == "login":
                login_failed = True
            # aborted: 静默跳过（登录失效后剩余任务）
            bar.update()
    bar.close()

    if login_failed:
        handle_login_failure(cfg)
        if not rows:
            sys.exit(2)

    if not rows:
        logger.error("没有抓取到任何数据。")
        sys.exit(3)

    # 排序：游戏 -> 地区 -> 日期，便于对比两天
    rows.sort(key=lambda r: (r["游戏"], r["地区"], r["日期"]))

    fieldnames = ["日期", "游戏", "key", "地区", *[METRIC_HEADERS[m] for m in METRICS]]
    sorted_days = sorted(days)
    suffix = sorted_days[0] if len(sorted_days) == 1 else f"{sorted_days[0]}_{sorted_days[-1]}"
    out_path = Path(args.output_dir) / f"iaa_{suffix}.csv"
    write_csv(out_path, fieldnames, rows)

    bq_cfg = cfg.get("bigquery") or {}
    bq_enabled = bool(bq_cfg.get("enabled"))
    if bq_enabled:
        if failed:
            logger.warning(
                "有 %d 个请求失败，本次数据不完整；仍按配置写入 BigQuery（如需完整数据请重跑）。",
                failed,
            )
        upload_to_bigquery(bq_records, sorted_days, bq_cfg)

    print_summary(
        days=days,
        rows=rows,
        skipped=skipped,
        failed=failed,
        failures=failures,
        out_path=out_path,
        bq_enabled=bq_enabled,
    )


if __name__ == "__main__":
    main()
