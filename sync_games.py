#!/usr/bin/env python3
"""从 TikTok 开发者后台自动获取游戏列表（app_id + client_key）。

两步：
1) 组织应用列表接口 -> 拿到所有游戏的 app_id + name
2) 逐个 mini_game basic_info 接口 -> 拿到每个游戏的 client_key

可作为模块被 scraper 调用，也可单独运行把结果写入 CSV。
"""

import argparse
import csv
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

APP_LIST_URL = "https://developers.tiktok.com/tiktok/v2/devportal/organization/app/list"
BASIC_INFO_URL = "https://developers.tiktok.com/tiktok/v4/devportal/mini_game/basic_info"
METADATA_URL = "https://developers.tiktok.com/tiktok/v4/devportal/mini_game/metadata"

# app_status 含义：1 = 已过审
APPROVED_STATUS = 1

logger = logging.getLogger("iaa")


def _live(field):
    """basic_info 的字段可能是 {"live_value": x} 或直接的值。"""
    if isinstance(field, dict):
        return field.get("live_value")
    return field


def fetch_app_list(session: requests.Session, org_id: str) -> list:
    referer = f"https://developers.tiktok.com/portal/organization/{org_id}?tab=overview"
    resp = session.get(
        APP_LIST_URL,
        params={"org_id": org_id},
        headers={"referer": referer},
        timeout=30,
    )
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError("应用列表返回非 JSON，可能登录失效。")
    return data.get("apps", []) or []


def fetch_basic_info(session: requests.Session, app_id: str) -> tuple:
    """返回 (client_key, region)。"""
    referer = f"https://developers.tiktok.com/portal/game/{app_id}/overall"
    resp = session.get(
        BASIC_INFO_URL,
        params={"mini_game_id": app_id},
        headers={"referer": referer},
        timeout=30,
    )
    resp.raise_for_status()
    d = resp.json()
    return _live(d.get("client_key")), _live(d.get("region"))


def fetch_app_status(session: requests.Session, app_id: str):
    """返回 app_status（1=已过审），取不到返回 None。"""
    referer = f"https://developers.tiktok.com/portal/game/{app_id}/overall"
    resp = session.get(
        METADATA_URL,
        params={"mini_game_id": app_id},
        headers={"referer": referer},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("app_status")


def fetch_games_from_api(
    session: requests.Session,
    org_id: str,
    *,
    concurrency: int = 8,
    category: str = "Games",
    exclude: list | None = None,
    approved_only: bool = True,
) -> list:
    """返回 [{name, app_id, client_key, region, app_status}, ...]，按游戏名排序。

    category 不为空时只保留该分类（默认 Games）。
    exclude 可按 游戏名 或 app_id 排除。
    approved_only=True 时只保留 app_status==1（已过审）的游戏；
    先查 metadata 拿状态，只对已过审的再查 basic_info 取 client_key（省请求）。
    """
    exclude_set = {str(x).strip() for x in (exclude or [])}
    apps = fetch_app_list(session, org_id)
    apps = [a for a in apps if not category or a.get("category") == category]

    def work(app):
        app_id = str(app.get("app_id") or "")
        name = (app.get("name") or "").strip()
        if not app_id or app_id in exclude_set or name in exclude_set:
            return None
        try:
            status = fetch_app_status(session, app_id)
        except requests.RequestException as exc:
            logger.warning("取 app_status 失败 %s(%s): %s", name, app_id, exc)
            return None
        if approved_only and status != APPROVED_STATUS:
            return None
        try:
            client_key, region = fetch_basic_info(session, app_id)
        except requests.RequestException as exc:
            logger.warning("取 client_key 失败 %s(%s): %s", name, app_id, exc)
            return None
        if not client_key:
            logger.warning("游戏 %s(%s) 无 client_key，跳过。", name, app_id)
            return None
        return {
            "name": name,
            "app_id": app_id,
            "client_key": client_key,
            "region": region or "",
            "app_status": status,
        }

    games = []
    with ThreadPoolExecutor(max_workers=max(concurrency, 1)) as executor:
        for result in executor.map(work, apps):
            if result:
                games.append(result)
    games.sort(key=lambda g: g["name"])
    return games


def write_games_csv(games: list, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["游戏全称", "app_id", "key", "region"])
        for g in games:
            writer.writerow([g["name"], g["app_id"], g["client_key"], g["region"]])


def main():
    import yaml

    import scraper  # 复用 build_session / get_cookie_string

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="从后台同步游戏列表到 CSV")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--out", default="games_auto.csv", help="输出 CSV 路径")
    parser.add_argument(
        "--cookie-source",
        default=None,
        choices=["config", "browser"],
        help="覆盖 config 的 cookie_source",
    )
    args = parser.parse_args()

    cfg = scraper.load_config(Path(args.config))
    if args.cookie_source:
        cfg["cookie_source"] = args.cookie_source
    org_id = str(cfg.get("org_id") or "").strip()
    if not org_id:
        logger.error("config.yaml 缺少 org_id（组织 ID，来自后台 organization/<id> 链接）。")
        sys.exit(1)

    cookie = scraper.get_cookie_string(cfg)
    session = scraper.build_session(cookie, concurrency=8)
    games = fetch_games_from_api(
        session,
        org_id,
        concurrency=8,
        exclude=cfg.get("exclude_games"),
        approved_only=cfg.get("approved_only", True),
    )
    if not games:
        logger.error("未获取到任何游戏，请检查登录态 / org_id。")
        sys.exit(2)

    out = Path(args.out)
    write_games_csv(games, out)
    logger.info("已同步 %d 个游戏 -> %s", len(games), out)
    for g in games:
        logger.info("  %s | %s | %s", g["name"], g["app_id"], g["client_key"])


if __name__ == "__main__":
    main()
