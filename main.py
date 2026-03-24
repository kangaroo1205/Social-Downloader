#!/usr/bin/env python3
"""
main.py — Social Media Downloader 統一入口
自動根據 URL 網域分流至 Threads 或 Instagram 爬蟲。

用法：
  python main.py <URL>                # 自動偵測平台並下載
  python main.py --login-threads      # 登入 Threads
  python main.py --login-instagram    # 登入 Instagram
"""

import asyncio
import os
import sys

# 修正 Windows 控制台編碼問題
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from scrapers import threads as threads_scraper
from scrapers import instagram as instagram_scraper
from core.downloader import download_all


# ── 平台偵測 ──────────────────────────────────────────────────────────────────

def detect_platform(url: str) -> str:
    """根據 URL 網域回傳平台識別字串：'threads' | 'instagram' | 'unknown'"""
    url_lower = url.lower()
    if "threads.com" in url_lower or "threads.net" in url_lower:
        return "threads"
    if "instagram.com" in url_lower:
        return "instagram"
    return "unknown"


# ── 主程式 ────────────────────────────────────────────────────────────────────

async def main():
    # ── 登入模式 ────────────────────────────────────────────────────────────
    if len(sys.argv) >= 2:
        cmd = sys.argv[1].strip()

        if cmd == "--login-threads":
            await threads_scraper.do_login()
            return

        if cmd == "--login-instagram":
            await instagram_scraper.do_login()
            return

        profile_url = cmd
    else:
        profile_url = input("請輸入個人頁面 URL（Threads 或 Instagram）：").strip()

    if not profile_url:
        print("❌ 未輸入 URL，程式結束。")
        return

    # 正規化 URL
    if not profile_url.startswith("http"):
        profile_url = "https://" + profile_url

    # ── 平台分流 ─────────────────────────────────────────────────────────────
    platform = detect_platform(profile_url)

    if platform == "threads":
        # ── Threads ──────────────────────────────────────────────────────────
        try:
            username = threads_scraper.extract_username(profile_url)
        except ValueError as e:
            print(f"❌ {e}")
            return

        output_dir = os.path.join("media", f"threads@{username}")
        print(f"📱 平台：Threads")
        print(f"👤 目標帳號：@{username}")
        print(f"📁 儲存資料夾：{output_dir}")
        print("─" * 50)

        media_list = await threads_scraper.scrape_profile(profile_url)
        if not media_list:
            print("⚠️  未找到任何可下載的媒體，程式結束。")
            return
        await download_all(media_list, output_dir, referer="https://www.threads.com/")

    elif platform == "instagram":
        # ── Instagram ─────────────────────────────────────────────────────────
        try:
            username = instagram_scraper.extract_username(profile_url)
        except ValueError as e:
            print(f"❌ {e}")
            return

        output_dir = os.path.join("media", f"instagram@{username}")
        print(f"📱 平台：Instagram")
        print(f"👤 目標帳號：@{username}")
        print(f"📁 儲存資料夾：{output_dir}")
        print("─" * 50)

        media_list = await instagram_scraper.scrape_profile(profile_url)
        if not media_list:
            print("⚠️  未找到任何可下載的媒體，程式結束。")
            return
        await download_all(media_list, output_dir, referer="https://www.instagram.com/")

    else:
        print(f"❌ 無法辨識的平台 URL：{profile_url}")
        print("   目前支援：threads.com、instagram.com")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
