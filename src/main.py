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
import tkinter as tk
from tkinter import simpledialog

# 修正 Windows 控制台編碼問題
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from scrapers import threads as threads_scraper
from scrapers import instagram as instagram_scraper
from scrapers import x as x_scraper
from core.downloader import download_all
from core.paths import get_base_dir
from core.browser import ensure_chromium


# ── 平台偵測 ──────────────────────────────────────────────────────────────────

def detect_platform(url: str) -> str:
    """根據 URL 網域回傳平台識別字串：'threads' | 'instagram' | 'unknown'"""
    url_lower = url.lower()
    if "threads.com" in url_lower or "threads.net" in url_lower:
        return "threads"
    if "instagram.com" in url_lower:
        return "instagram"
    if "x.com" in url_lower or "twitter.com" in url_lower:
        return "x"
    return "unknown"


# ── 主程式 ────────────────────────────────────────────────────────────────────

async def main():
    # ── 登入模式 ────────────────────────────────────────────────────────────
    if len(sys.argv) >= 2:
        cmd = sys.argv[1].strip()

        if cmd == "--login-threads":
            ensure_chromium()
            await threads_scraper.do_login()
            return

        if cmd == "--login-instagram":
            ensure_chromium()
            await instagram_scraper.do_login()
            return

        if cmd == "--login-x":
            ensure_chromium()
            await x_scraper.do_login()
            return

        profile_url = cmd
    else:
        try:
            if sys.stdin.isatty():
                profile_url = input("請輸入個人頁面 URL（Threads、Instagram 或 X）：").strip()
            else:
                raise EOFError
        except EOFError:
            root = tk.Tk()
            root.withdraw()
            profile_url = simpledialog.askstring(
                "Social Downloader",
                "請輸入貼文或個人頁面 URL：",
                parent=root,
            )
            root.destroy()
            if not profile_url:
                print("❌ 未輸入 URL，程式結束。")
                return
            profile_url = profile_url.strip()

    if not profile_url:
        print("❌ 未輸入 URL，程式結束。")
        return

    # 正規化 URL
    if not profile_url.startswith("http"):
        profile_url = "https://" + profile_url

    ensure_chromium()

    # ── 平台分流 ─────────────────────────────────────────────────────────────
    platform = detect_platform(profile_url)

    if platform == "threads":
        # ── Threads ──────────────────────────────────────────────────────────
        try:
            username = threads_scraper.extract_username(profile_url)
        except ValueError as e:
            print(f"❌ {e}")
            return

        output_dir = os.path.join(get_base_dir(), "media", f"threads@{username}")
        print(f"📱 平台：Threads")
        print(f"👤 目標帳號：@{username}")
        print(f"📁 儲存資料夾：{output_dir}")

        if threads_scraper.is_post_url(profile_url):
            print(f"🎯 模式：單一貼文")
            print("─" * 50)
            media_list = await threads_scraper.scrape_post(profile_url)
        else:
            print(f"📋 模式：個人頁面（全部媒體）")
            print("─" * 50)
            media_list = await threads_scraper.scrape_profile(profile_url)

        if not media_list:
            print("⚠️  未找到任何可下載的媒體，程式結束。")
            return
        await download_all(media_list, output_dir, referer="https://www.threads.com/")

    elif platform == "instagram":
        # ── Instagram ─────────────────────────────────────────────────────────
        print(f"📱 平台：Instagram")

        if instagram_scraper.is_post_url(profile_url):
            try:
                shortcode = instagram_scraper.extract_shortcode(profile_url)
            except ValueError as e:
                print(f"❌ {e}")
                return
            output_dir = os.path.join(get_base_dir(), "media", f"instagram_post@{shortcode}")
            print(f"🎯 模式：單一貼文")
            print(f"📁 儲存資料夾：{output_dir}")
            print("─" * 50)
            media_list = await instagram_scraper.scrape_post(profile_url)
        else:
            try:
                username = instagram_scraper.extract_username(profile_url)
            except ValueError as e:
                print(f"❌ {e}")
                return
            output_dir = os.path.join(get_base_dir(), "media", f"instagram@{username}")
            print(f"👤 目標帳號：@{username}")
            print(f"📋 模式：個人頁面（全部媒體）")
            print(f"📁 儲存資料夾：{output_dir}")
            print("─" * 50)
            media_list = await instagram_scraper.scrape_profile(profile_url)

        if not media_list:
            print("⚠️  未找到任何可下載的媒體，程式結束。")
            return
        await download_all(media_list, output_dir, referer="https://www.instagram.com/")

    elif platform == "x":
        # ── X (Twitter) ────────────────────────────────────────────────────────
        try:
            username = x_scraper.extract_username(profile_url)
        except ValueError as e:
            print(f"❌ {e}")
            return

        output_dir = os.path.join(get_base_dir(), "media", f"x@{username}")
        print(f"📱 平台：X (Twitter)")
        print(f"👤 目標帳號：@{username}")
        print(f"📁 儲存資料夾：{output_dir}")

        if x_scraper.is_post_url(profile_url):
            print(f"🎯 模式：單一貼文")
            print("─" * 50)
            media_list = await x_scraper.scrape_post(profile_url)
        else:
            print(f"📋 模式：個人頁面（全部媒體）")
            print("─" * 50)
            media_list = await x_scraper.scrape_profile(profile_url)

        if not media_list:
            print("⚠️  未找到任何可下載的媒體，程式結束。")
            return
        await download_all(media_list, output_dir, referer="https://x.com/")

    else:
        print(f"❌ 無法辨識的平台 URL：{profile_url}")
        print("   目前支援：threads.com、instagram.com、x.com、twitter.com")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
