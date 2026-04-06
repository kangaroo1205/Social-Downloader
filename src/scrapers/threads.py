#!/usr/bin/env python3
"""
threads_scraper.py — Threads 媒體爬取模組
提供 do_login、scrape_profile 給 main.py 呼叫。
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime

# 修正 Windows 控制台編碼問題
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

from core.downloader import USER_AGENT, download_all  # noqa: F401（export 給 main.py 使用）
from core.paths import get_base_dir

# ── 常數 ──────────────────────────────────────────────────────────────────────

SCROLL_PAUSE = 1.5          # 每次滾動後等待秒數
MAX_NO_CHANGE = 5           # 連續無高度變化次數上限
COOKIES_FILE = os.path.join(get_base_dir(), "data", "threads_session.json")


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def extract_username(url: str) -> str:
    """從 Threads URL 提取使用者名稱"""
    match = re.search(r"@([\w.]+)", url)
    if match:
        return match.group(1)
    raise ValueError(f"無法從 URL 解析使用者名稱: {url}")


def is_post_url(url: str) -> bool:
    """判斷 URL 是否為單一 Threads 貼文（含 /post/）"""
    return "/post/" in url


def find_thread_items(data, results=None):
    """遞迴搜尋 JSON 結構中所有 thread_items 並展開回傳"""
    if results is None:
        results = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "thread_items" and isinstance(value, list):
                results.extend(value)
            else:
                find_thread_items(value, results)
    elif isinstance(data, list):
        for item in data:
            find_thread_items(item, results)
    return results


def is_profile_pic_url(url: str) -> bool:
    """判斷 URL 是否為頭像圖片"""
    return "/profile_pic/" in url


def get_best_image_url(image_versions2: dict) -> str | None:
    """從 image_versions2 取得最高解析度的圖片 URL"""
    candidates = image_versions2.get("candidates", [])
    if not candidates:
        return None
    url = candidates[0].get("url", "")
    if url and not is_profile_pic_url(url):
        return url
    return None


def extract_media_from_post(post: dict) -> list[dict]:
    """
    從單一 post 物件萃取所有媒體資訊。
    回傳 list of dict: {"url": str, "type": "image"|"video", "taken_at": int}
    """
    taken_at = post.get("taken_at", 0)
    media_list = []

    # 輪播貼文
    carousel = post.get("carousel_media", [])
    if carousel:
        for item in carousel:
            img_v2 = item.get("image_versions2")
            if img_v2:
                url = get_best_image_url(img_v2)
                if url:
                    media_list.append({"url": url, "type": "image", "taken_at": taken_at})
            video_versions = item.get("video_versions", [])
            if video_versions:
                vurl = video_versions[0].get("url", "")
                if vurl and not is_profile_pic_url(vurl):
                    media_list.append({"url": vurl, "type": "video", "taken_at": taken_at})
        return media_list

    # 單一圖片
    img_v2 = post.get("image_versions2")
    if img_v2:
        url = get_best_image_url(img_v2)
        if url:
            media_list.append({"url": url, "type": "image", "taken_at": taken_at})

    # 單一影片（優先於圖片縮圖）
    video_versions = post.get("video_versions", [])
    if video_versions:
        vurl = video_versions[0].get("url", "")
        if vurl and not is_profile_pic_url(vurl):
            media_list = [m for m in media_list if m["type"] != "image"]
            media_list.append({"url": vurl, "type": "video", "taken_at": taken_at})

    return media_list


# ── 單一貼文爬取 ─────────────────────────────────────────────────────────────

async def scrape_post(post_url: str) -> list[dict]:
    """
    使用 Playwright 載入單一 Threads 貼文頁面，
    攔截含 thread_items 的回應並萃取媒體。
    """
    use_session = os.path.exists(COOKIES_FILE)
    if use_session:
        print(f"🔑 偵測到 Threads 登入 session（{COOKIES_FILE}），將以登入狀態爬取")
    else:
        print("   未偵測到登入 session，以訪客模式爬取（可執行 --login-threads 登入）")

    print(f"🌐 開啟瀏覽器，載入貼文：{post_url}")
    all_json_blobs: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context_kwargs = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 900},
        }
        if use_session:
            context_kwargs["storage_state"] = COOKIES_FILE
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        async def handle_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct or "javascript" in ct:
                    body = await response.body()
                    text = body.decode("utf-8", errors="ignore")
                    if "thread_items" in text:
                        all_json_blobs.append(text)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            await page.goto(post_url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"⚠️  頁面載入警告（將繼續）：{e}")

        # 從 <script data-sjs> 標籤取得靜態 JSON
        script_contents = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[type="application/json"][data-sjs]');
                return Array.from(scripts).map(s => s.textContent);
            }
        """)
        for content in script_contents:
            if content and "thread_items" in content:
                all_json_blobs.append(content)

        await browser.close()

    print(f"📦 共收集到 {len(all_json_blobs)} 個含貼文資料的 JSON 片段，開始解析...")
    seen_post_ids: set = set()
    all_media: list[dict] = []

    for blob in all_json_blobs:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            start = min(
                (blob.find("{") if blob.find("{") != -1 else len(blob)),
                (blob.find("[") if blob.find("[") != -1 else len(blob)),
            )
            try:
                data = json.loads(blob[start:])
            except Exception:
                continue

        thread_items = find_thread_items(data)
        for item in thread_items:
            post = item.get("post", {})
            post_id = post.get("pk") or post.get("id")
            if not post_id or post_id in seen_post_ids:
                continue
            seen_post_ids.add(post_id)
            media = extract_media_from_post(post)
            all_media.extend(media)

    print(f"✅ 找到 {len(all_media)} 個媒體檔案")
    return all_media


# ── 登入 ──────────────────────────────────────────────────────────────────────

async def do_login():
    """開啟有介面的瀏覽器讓使用者手動登入 Threads，完成後儲存 session。"""
    print("🔐 開啟瀏覽器，請在瀏覽器中完成 Threads 登入...")
    print("   登入完成後程式會自動偵測並儲存 session，請勿手動關閉瀏覽器。")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        await page.goto("https://www.threads.com/login", wait_until="networkidle", timeout=30000)
        print("   等待登入完成（偵測到已登入後自動儲存）...")
        try:
            await page.wait_for_url(
                lambda url: "/login" not in url and "threads.com" in url,
                timeout=120000,
            )
        except Exception:
            print("⚠️  等待逾時，嘗試直接儲存目前 session...")
        await asyncio.sleep(1)
        await context.storage_state(path=COOKIES_FILE)
        await browser.close()

    print(f"✅ Threads 登入 session 已儲存至：{COOKIES_FILE}\n")


# ── 網頁爬取 ──────────────────────────────────────────────────────────────────

async def scrape_profile(profile_url: str) -> list[dict]:
    """
    使用 Playwright 載入 Threads 個人頁面，滾動至底部，
    解析 <script data-sjs> 標籤中的 JSON 資料，回傳所有媒體資訊。
    """
    use_session = os.path.exists(COOKIES_FILE)
    if use_session:
        print(f"🔑 偵測到 Threads 登入 session（{COOKIES_FILE}），將以登入狀態爬取")
    else:
        print("   未偵測到登入 session，以訪客模式爬取（可執行 --login-threads 登入）")

    print(f"🌐 開啟瀏覽器，載入頁面：{profile_url}")
    all_json_blobs: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context_kwargs = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 900},
        }
        if use_session:
            context_kwargs["storage_state"] = COOKIES_FILE
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        async def handle_response(response):
            """攔截 XHR/Fetch 回應，收集含 thread_items 的 JSON"""
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct or "javascript" in ct:
                    body = await response.body()
                    text = body.decode("utf-8", errors="ignore")
                    if "thread_items" in text:
                        all_json_blobs.append(text)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            await page.goto(profile_url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"⚠️  頁面載入警告（將繼續）：{e}")

        page_text = await page.inner_text("body")
        if any(kw in page_text for kw in [
            "This profile is private", "Sorry, this page isn't available",
            "找不到此頁面", "私人帳號", "Page not found",
        ]):
            print("❌ 此帳號為私人帳號或不存在，無法爬取內容。")
            await browser.close()
            return []

        print("📜 開始向下滾動載入所有貼文...")
        no_change_count = 0
        last_height = await page.evaluate("document.body.scrollHeight")

        while no_change_count < MAX_NO_CHANGE:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(SCROLL_PAUSE)
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                no_change_count += 1
                print(f"   頁面高度未變化（{no_change_count}/{MAX_NO_CHANGE}）")
            else:
                no_change_count = 0
                last_height = new_height
                print(f"   已滾動，頁面高度：{new_height}px")

        # 從 <script data-sjs> 標籤取得靜態 JSON
        print("🔍 解析頁面內嵌 JSON 資料...")
        script_contents = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[type="application/json"][data-sjs]');
                return Array.from(scripts).map(s => s.textContent);
            }
        """)
        for content in script_contents:
            if content and "thread_items" in content:
                all_json_blobs.append(content)

        await browser.close()

    print(f"📦 共收集到 {len(all_json_blobs)} 個含貼文資料的 JSON 片段，開始解析...")
    seen_post_ids: set = set()
    all_media: list[dict] = []

    for blob in all_json_blobs:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            start = min(
                (blob.find("{") if blob.find("{") != -1 else len(blob)),
                (blob.find("[") if blob.find("[") != -1 else len(blob)),
            )
            try:
                data = json.loads(blob[start:])
            except Exception:
                continue

        thread_items = find_thread_items(data)
        for item in thread_items:
            post = item.get("post", {})
            post_id = post.get("pk") or post.get("id")
            if not post_id or post_id in seen_post_ids:
                continue
            seen_post_ids.add(post_id)
            media = extract_media_from_post(post)
            all_media.extend(media)

    print(f"✅ 共找到 {len(seen_post_ids)} 篇不重複貼文，{len(all_media)} 個媒體檔案")
    return all_media
