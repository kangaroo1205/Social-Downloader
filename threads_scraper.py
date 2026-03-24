#!/usr/bin/env python3
"""
Threads 媒體下載器
用法: python threads_scraper.py https://www.threads.com/@username
"""

import asyncio
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

# 修正 Windows 控制台編碼問題
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
from playwright.async_api import async_playwright


# ── 常數設定 ──────────────────────────────────────────────────────────────────

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
SCROLL_PAUSE = 1.5          # 每次滾動後等待秒數
MAX_NO_CHANGE = 5           # 連續無高度變化次數上限
MAX_CONCURRENT = 5          # 同時下載數量
DOWNLOAD_TIMEOUT = 60       # 下載逾時秒數
MAX_RETRIES = 3             # 失敗重試次數
COOKIES_FILE = "threads_session.json"  # 登入 session 儲存路徑


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def extract_username(url: str) -> str:
    """從 URL 提取使用者名稱"""
    match = re.search(r"@([\w.]+)", url)
    if match:
        return match.group(1)
    raise ValueError(f"無法從 URL 解析使用者名稱: {url}")


def find_thread_items(data, results=None):
    """
    遞迴搜尋 JSON 結構中所有 thread_items 的值。
    回傳一個 list，包含所有找到的 thread_items 項目（已展開）。
    """
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
    # candidates 通常由高到低排列，取第一個
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
            # 輪播中的圖片
            img_v2 = item.get("image_versions2")
            if img_v2:
                url = get_best_image_url(img_v2)
                if url:
                    media_list.append({"url": url, "type": "image", "taken_at": taken_at})

            # 輪播中的影片
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
            # 有影片時移除已加入的圖片縮圖（通常是影片封面）
            media_list = [m for m in media_list if m["type"] != "image"]
            media_list.append({"url": vurl, "type": "video", "taken_at": taken_at})

    return media_list


def guess_extension(url: str, media_type: str) -> str:
    """根據 URL 或媒體類型推測副檔名"""
    path = urlparse(url).path
    # 移除查詢參數後取副檔名
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return ext.lstrip(".")
    if ext in (".mp4", ".mov", ".m4v", ".webm"):
        return ext.lstrip(".")
    # 根據類型給預設值
    return "mp4" if media_type == "video" else "jpg"


def build_filename(date_str: str, index: int, ext: str) -> str:
    """建立檔名，格式：YYYY_MM_DD_N.ext"""
    return f"{date_str}_{index}.{ext}"


# ── 登入 ──────────────────────────────────────────────────────────────────────

async def do_login():
    """
    開啟有介面的瀏覽器讓使用者手動登入 Threads，
    登入完成後儲存 session 至 COOKIES_FILE。
    """
    print("🔐 開啟瀏覽器，請在瀏覽器中完成登入...")
    print("   登入完成後，程式會自動偵測並儲存 session，請勿手動關閉瀏覽器。")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        await page.goto("https://www.threads.com/login", wait_until="networkidle", timeout=30000)

        print("   等待登入完成（偵測到已登入後自動儲存）...")

        # 等待直到 URL 不再包含 /login（表示登入成功）
        try:
            await page.wait_for_url(
                lambda url: "/login" not in url and "threads.com" in url,
                timeout=120000,
            )
        except Exception:
            print("⚠️  等待逾時，嘗試直接儲存目前 session...")

        # 額外等待一秒確保 cookie 寫入完畢
        await asyncio.sleep(1)

        await context.storage_state(path=COOKIES_FILE)
        await browser.close()

    print(f"✅ 登入 session 已儲存至：{COOKIES_FILE}")
    print("   之後執行爬蟲時將自動使用此 session。\n")


# ── 網頁爬取 ──────────────────────────────────────────────────────────────────

async def scrape_profile(profile_url: str) -> list[dict]:
    """
    使用 Playwright 載入 Threads 個人頁面，滾動至底部，
    解析 <script data-sjs> 標籤中的 JSON 資料，回傳所有媒體資訊。
    """
    use_session = os.path.exists(COOKIES_FILE)
    if use_session:
        print(f"🔑 偵測到登入 session（{COOKIES_FILE}），將以登入狀態爬取")
    else:
        print("   未偵測到登入 session，以訪客模式爬取（可執行 --login 登入以取得更多貼文）")

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

        # 攔截並收集 JSON 資料
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

        # 檢查是否為私人帳號或不存在
        page_text = await page.inner_text("body")
        if any(kw in page_text for kw in ["This profile is private", "Sorry, this page isn't available",
                                            "找不到此頁面", "私人帳號", "Page not found"]):
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

    # 解析所有 JSON blob，萃取 thread_items
    print(f"📦 共收集到 {len(all_json_blobs)} 個含貼文資料的 JSON 片段，開始解析...")

    seen_post_ids: set = set()
    all_media: list[dict] = []

    for blob in all_json_blobs:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            # 部分回應可能夾雜非 JSON 前綴（如 for (;;); ）
            # 嘗試找到第一個 { 或 [ 後解析
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


# ── 下載邏輯 ──────────────────────────────────────────────────────────────────

async def download_file(
    client: httpx.AsyncClient,
    url: str,
    dest_path: str,
    semaphore: asyncio.Semaphore,
) -> bool:
    """下載單一檔案，失敗時重試最多 MAX_RETRIES 次"""
    if os.path.exists(dest_path):
        print(f"   ⏭  已存在，跳過：{os.path.basename(dest_path)}")
        return True

    async with semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await client.get(url, timeout=DOWNLOAD_TIMEOUT)
                response.raise_for_status()
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(response.content)
                print(f"   ✅ 下載完成：{os.path.basename(dest_path)}")
                return True
            except Exception as e:
                if attempt < MAX_RETRIES:
                    print(f"   ⚠️  下載失敗（第 {attempt} 次），重試中：{os.path.basename(dest_path)} — {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    print(f"   ❌ 下載失敗（已達最大重試次數）：{os.path.basename(dest_path)} — {e}")
        return False


async def download_all(media_list: list[dict], output_dir: str):
    """將所有媒體並行下載至指定資料夾"""
    os.makedirs(output_dir, exist_ok=True)

    # 按日期分組，並指派每日序號
    day_counters: dict[str, int] = defaultdict(int)
    tasks_info: list[tuple[str, str]] = []  # (url, dest_path)

    # 先按 taken_at 排序（舊到新），確保序號一致
    sorted_media = sorted(media_list, key=lambda m: (m["taken_at"], m["url"]))

    for media in sorted_media:
        ts = media["taken_at"]
        url = media["url"]
        mtype = media["type"]

        if ts:
            dt = datetime.fromtimestamp(ts, tz=datetime.now().astimezone().tzinfo)
            date_str = f"{dt.year:04d}_{dt.month:02d}_{dt.day:02d}"
        else:
            date_str = "0000_00_00"

        day_counters[date_str] += 1
        idx = day_counters[date_str]
        ext = guess_extension(url, mtype)
        filename = build_filename(date_str, idx, ext)
        dest_path = os.path.join(output_dir, filename)
        tasks_info.append((url, dest_path))

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.threads.com/"}

    print(f"\n📥 開始下載 {len(tasks_info)} 個媒體檔案至：{output_dir}")

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        coros = [
            download_file(client, url, dest_path, semaphore)
            for url, dest_path in tasks_info
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

    success = sum(1 for r in results if r is True)
    fail = len(results) - success
    print(f"\n🎉 下載完成！成功：{success} 個，失敗：{fail} 個")


# ── 主程式 ────────────────────────────────────────────────────────────────────

async def main():
    # 登入模式
    if len(sys.argv) >= 2 and sys.argv[1].strip() == "--login":
        await do_login()
        return

    # 取得目標 URL
    if len(sys.argv) >= 2:
        profile_url = sys.argv[1].strip()
    else:
        profile_url = input("請輸入 Threads 個人頁面 URL：").strip()

    if not profile_url:
        print("❌ 未輸入 URL，程式結束。")
        return

    # 正規化 URL
    if not profile_url.startswith("http"):
        profile_url = "https://" + profile_url

    # 提取使用者名稱
    try:
        username = extract_username(profile_url)
    except ValueError as e:
        print(f"❌ {e}")
        return

    output_dir = os.path.join("media", f"threads@{username}")
    print(f"👤 目標帳號：@{username}")
    print(f"📁 儲存資料夾：{output_dir}")
    print("─" * 50)

    # 爬取所有媒體 URL
    media_list = await scrape_profile(profile_url)

    if not media_list:
        print("⚠️  未找到任何可下載的媒體，程式結束。")
        return

    # 下載所有媒體
    await download_all(media_list, output_dir)


if __name__ == "__main__":
    asyncio.run(main())
