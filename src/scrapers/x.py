#!/usr/bin/env python3
"""
x_scraper.py — X.com (Twitter) 媒體爬取模組
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

from core.downloader import USER_AGENT
from core.paths import get_base_dir

# ── 常數 ──────────────────────────────────────────────────────────────────────

SCROLL_PAUSE = 1.5          # 每次滾動後等待秒數
MAX_NO_CHANGE = 5           # 連續無高度變化次數上限
COOKIES_FILE = os.path.join(get_base_dir(), "data", "x_session.json")


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def extract_username(url: str) -> str:
    """從 X.com URL 提取使用者名稱"""
    # 支援 https://x.com/username 或 https://twitter.com/username
    match = re.search(r"(?:x\.com|twitter\.com)/([\w_]+)", url)
    if match:
        return match.group(1)
    raise ValueError(f"無法從 URL 解析使用者名稱: {url}")


def is_post_url(url: str) -> bool:
    """判斷 URL 是否為單一 X 貼文（含 /status/<id>）"""
    return bool(re.search(r"(?:x\.com|twitter\.com)/[\w_]+/status/\d+", url))


def extract_media_from_tweet(tweet: dict) -> list[dict]:
    """從單一 tweet 結果萃取所有媒體資訊"""
    media_list = []
    
    # 支援各種 tweet 格式
    legacy = tweet.get("legacy", {})
    if not legacy and "tweet" in tweet:
        legacy = tweet["tweet"].get("legacy", {})
        
    extended_entities = legacy.get("extended_entities", {})
    media_items = extended_entities.get("media", [])

    # 取得推文時間
    created_at_str = legacy.get("created_at", "")
    taken_at = 0
    if created_at_str:
        try:
            # 格式例如: "Wed Oct 10 20:19:24 +0000 2018"
            dt = datetime.strptime(created_at_str, "%a %b %d %H:%M:%S %z %Y")
            taken_at = int(dt.timestamp())
        except Exception:
            pass
    
    for item in media_items:
        m_type = item.get("type")
        if m_type == "photo":
            url = item.get("media_url_https", "")
            if url:
                # 取得原圖大小 (name=orig)
                best_url = url + "?name=orig" if "?" not in url else url.split("?")[0] + "?name=orig"
                media_list.append({"url": best_url, "type": "image", "taken_at": taken_at})
        elif m_type in ("video", "animated_gif"):
            video_info = item.get("video_info", {})
            variants = video_info.get("variants", [])
            # 找 bitrate 最高的 mp4
            best_variant = None
            max_bitrate = -1
            for var in variants:
                if var.get("content_type") == "video/mp4":
                    bitrate = var.get("bitrate", -1)
                    if bitrate > max_bitrate:
                        max_bitrate = bitrate
                        best_variant = var
            if best_variant:
                media_list.append({"url": best_variant["url"], "type": "video", "taken_at": taken_at})
                
    return media_list


def find_tweets_in_timeline(data, results=None):
    """遞迴搜尋 JSON 結構中所有 tweet_results 並展開回傳"""
    if results is None:
        results = []
    if isinstance(data, dict):
        # Twitter GraphQL 的推文通常在 tweet_results.result
        if "tweet_results" in data and "result" in data["tweet_results"]:
            results.append(data["tweet_results"]["result"])
        for key, value in data.items():
            find_tweets_in_timeline(value, results)
    elif isinstance(data, list):
        for item in data:
            find_tweets_in_timeline(item, results)
    return results


# ── 單一貼文爬取 ─────────────────────────────────────────────────────────────

async def scrape_post(post_url: str) -> list[dict]:
    """
    使用 Playwright 載入單一 X.com 貼文頁面，
    攔截 TweetDetail GraphQL 回應並萃取媒體。
    """
    use_session = os.path.exists(COOKIES_FILE)
    if use_session:
        print(f"🔑 偵測到 X.com 登入 session（{COOKIES_FILE}），將以登入狀態爬取")
    else:
        print("   ⚠️ 未偵測到登入 session，X.com 未登入可能無法查看任何內容（建議執行 --login-x 登入）")

    print(f"🌐 開啟瀏覽器，載入貼文：{post_url}")
    all_json_blobs: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context_kwargs = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 900},
        }
        if use_session:
            context_kwargs["storage_state"] = COOKIES_FILE
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        async def handle_response(response):
            try:
                if "graphql" in response.url and (
                    "TweetDetail" in response.url or "TweetResultByRestId" in response.url
                ):
                    ct = response.headers.get("content-type", "")
                    if "json" in ct.lower():
                        text = await response.text()
                        all_json_blobs.append(text)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"⚠️  頁面載入警告（將繼續）：{e}")

        # 等待 API 回應完成
        await asyncio.sleep(3)
        await browser.close()

    print(f"📦 共攔截到 {len(all_json_blobs)} 個 GraphQL 回應，開始解析...")
    seen_post_ids: set = set()
    all_media: list[dict] = []

    for blob in all_json_blobs:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue

        tweets = find_tweets_in_timeline(data)
        for tweet in tweets:
            if "tweet" in tweet and "rest_id" in tweet["tweet"]:
                t_obj = tweet["tweet"]
            else:
                t_obj = tweet

            post_id = t_obj.get("rest_id") or t_obj.get("id_str")
            if not post_id or post_id in seen_post_ids:
                continue
            seen_post_ids.add(post_id)

            media = extract_media_from_tweet(t_obj)
            all_media.extend(media)

    print(f"✅ 找到 {len(all_media)} 個媒體檔案")
    return all_media


# ── 登入 ──────────────────────────────────────────────────────────────────────

async def do_login():
    """開啟有介面的瀏覽器讓使用者手動登入 X.com，完成後儲存 session。"""
    print("🔐 開啟瀏覽器，請在瀏覽器中完成 X (Twitter) 登入...")
    print("   登入完成後程式會自動偵測並儲存 session，請勿手動關閉瀏覽器。")

    os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)

    async with async_playwright() as pw:
        # X 較容易阻擋爬蟲，使用一般瀏覽器參數
        browser = await pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        # 加入防偵測 script
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        await page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=60000)
        print("   等待登入完成（偵測到首頁網址後自動儲存）...")
        try:
            await page.wait_for_url(
                lambda url: url.rstrip("/") == "https://x.com/home" or "twitter.com/home" in url,
                timeout=300000, # 等待最多 5 分鐘
            )
        except Exception:
            print("⚠️  等待逾時，嘗試直接儲存目前 session...")
        await asyncio.sleep(2)
        await context.storage_state(path=COOKIES_FILE)
        await browser.close()

    print(f"✅ X.com 登入 session 已儲存至：{COOKIES_FILE}\n")


# ── 網頁爬取 ──────────────────────────────────────────────────────────────────

async def scrape_profile(profile_url: str) -> list[dict]:
    """
    使用 Playwright 載入 X.com 個人頁面，滾動至底部，
    攔截包含推文媒體的 GraphQL 請求。
    """
    use_session = os.path.exists(COOKIES_FILE)
    if use_session:
        print(f"🔑 偵測到 X.com 登入 session（{COOKIES_FILE}），將以登入狀態爬取")
    else:
        print("   ⚠️ 未偵測到登入 session，X.com 未登入可能無法查看任何內容（建議執行 --login-x 登入）")

    # 確保是跑到 media 分頁比較容易抓到純圖片/影片推文
    if not profile_url.endswith("/media"):
        profile_url = profile_url.rstrip("/") + "/media"

    print(f"🌐 開啟瀏覽器，載入頁面：{profile_url}")
    all_json_blobs: list[str] = []

    async with async_playwright() as pw:
        # headless=True 時 X 可能會封鎖，加上 args
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context_kwargs = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 900},
        }
        if use_session:
            context_kwargs["storage_state"] = COOKIES_FILE
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        async def handle_response(response):
            """攔截 XHR/Fetch 回應，收集 GraphQL 資料"""
            try:
                # 只在 URL 包含 graphql 且可能是 UserMedia 或 UserTweets 時處理
                # X 的 GraphQL 有非常多種 Endpoint，UserMedia 是個人頁面媒體專屬
                if "graphql" in response.url and ("UserMedia" in response.url or "UserTweets" in response.url):
                    ct = response.headers.get("content-type", "")
                    if "json" in ct.lower():
                        text = await response.text()
                        all_json_blobs.append(text)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"⚠️  頁面載入警告（將繼續）：{e}")

        # 簡單檢查頁面是否出現錯誤
        page_text = await page.inner_text("body")
        if "Something went wrong" in page_text or "出錯了" in page_text or "Retry" in page_text:
            print("⚠️  頁面似乎出現錯誤，可能被限制或需登入。")

        print("📜 開始向下滾動載入推文...")
        no_change_count = 0
        last_height = await page.evaluate("document.body.scrollHeight")

        while no_change_count < MAX_NO_CHANGE:
            # X 是 window-level 滾動
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

        await browser.close()

    print(f"📦 共攔截到 {len(all_json_blobs)} 個 GraphQL 回應，開始解析...")
    seen_post_ids: set = set()
    all_media: list[dict] = []

    for blob in all_json_blobs:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue

        tweets = find_tweets_in_timeline(data)
        for tweet in tweets:
            # 某些 result 裡面包在 tweet 層裡面 (如轉推)
            if "tweet" in tweet and "rest_id" in tweet["tweet"]:
                t_obj = tweet["tweet"]
            else:
                t_obj = tweet
                
            post_id = t_obj.get("rest_id") or t_obj.get("id_str")
            if not post_id or post_id in seen_post_ids:
                continue
            seen_post_ids.add(post_id)
            
            media = extract_media_from_tweet(t_obj)
            all_media.extend(media)

    print(f"✅ 共找到 {len(seen_post_ids)} 篇不重複推文，{len(all_media)} 個媒體檔案")
    return all_media
