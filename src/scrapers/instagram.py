#!/usr/bin/env python3
"""
instagram_scraper.py — Instagram 媒體爬取模組
提供 do_login、scrape_profile 給 main.py 呼叫。

策略：使用 Playwright headless 開啟個人頁面並滾動，
同時攔截所有含媒體資料的 XHR/Fetch JSON 回應，
萃取圖片、影片及輪播貼文的最高畫質 URL。
"""

import asyncio
import json
import os
import re
import sys

# 修正 Windows 控制台編碼問題
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

from core.downloader import USER_AGENT
from core.paths import get_base_dir

# ── 常數 ──────────────────────────────────────────────────────────────────────

COOKIES_FILE = os.path.join(get_base_dir(), "data", "instagram_session.json")
SCROLL_PAUSE = 2.0      # Instagram 載入較慢，等待稍長
MAX_NO_CHANGE = 6       # 連續無高度變化次數上限


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def extract_username(url: str) -> str:
    """從 Instagram URL 提取使用者名稱"""
    # 支援格式：instagram.com/username 或 instagram.com/username/
    parsed = url.rstrip("/")
    match = re.search(r"instagram\.com/([A-Za-z0-9_.]+)(?:/|$)", parsed)
    if match:
        candidate = match.group(1)
        # 排除特殊路徑段（p/reel/explore 等）
        if candidate not in ("p", "reel", "reels", "explore", "stories", "tv"):
            return candidate
    raise ValueError(f"無法從 URL 解析使用者名稱: {url}")


def is_post_url(url: str) -> bool:
    """判斷 URL 是否為單一 Instagram 貼文（/p/ 或 /reel/）"""
    return bool(re.search(r"instagram\.com/(?:p|reel)/", url))


def extract_shortcode(url: str) -> str:
    """從 Instagram 貼文 URL 提取 shortcode"""
    match = re.search(r"instagram\.com/(?:p|reel)/([\w-]+)", url)
    if match:
        return match.group(1)
    raise ValueError(f"無法從 URL 解析貼文 shortcode: {url}")


def is_profile_pic_url(url: str) -> bool:
    """判斷 URL 是否為頭像圖片"""
    return "/profile_pic/" in url or "150x150" in url


def get_best_image_url(image_versions2: dict) -> str | None:
    """從 image_versions2.candidates 取得最高解析度的圖片 URL"""
    candidates = image_versions2.get("candidates", [])
    if not candidates:
        return None
    # candidates 通常由高到低排列
    url = candidates[0].get("url", "")
    if url and not is_profile_pic_url(url):
        return url
    return None


def extract_media_from_node(node: dict, taken_at: int = 0) -> list[dict]:
    """
    從單一貼文節點（GraphQL node 或 App API post）萃取媒體。
    同時支援：
      - GraphQL 格式（display_url / video_url / edge_sidecar_to_children）
      - App API 格式（image_versions2 / video_versions / carousel_media）
    """
    media_list = []

    # ── App API 格式：輪播 ─────────────────────────────────────────────────
    carousel = node.get("carousel_media", [])
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

    # ── GraphQL 格式：輪播 ────────────────────────────────────────────────
    sidecar = node.get("edge_sidecar_to_children", {})
    if sidecar:
        for edge in sidecar.get("edges", []):
            child = edge.get("node", {})
            child_ts = child.get("taken_at_timestamp", taken_at)
            if child.get("is_video"):
                vurl = child.get("video_url", "")
                if vurl and not is_profile_pic_url(vurl):
                    media_list.append({"url": vurl, "type": "video", "taken_at": child_ts})
            else:
                iurl = child.get("display_url", "")
                if iurl and not is_profile_pic_url(iurl):
                    media_list.append({"url": iurl, "type": "image", "taken_at": child_ts})
        return media_list

    # ── 單一媒體：App API ─────────────────────────────────────────────────
    video_versions = node.get("video_versions", [])
    if video_versions:
        vurl = video_versions[0].get("url", "")
        if vurl and not is_profile_pic_url(vurl):
            media_list.append({"url": vurl, "type": "video", "taken_at": taken_at})
        return media_list  # 有影片就不另外加圖片縮圖

    img_v2 = node.get("image_versions2")
    if img_v2:
        url = get_best_image_url(img_v2)
        if url:
            media_list.append({"url": url, "type": "image", "taken_at": taken_at})
        return media_list

    # ── 單一媒體：GraphQL ─────────────────────────────────────────────────
    if node.get("is_video"):
        vurl = node.get("video_url", "")
        if vurl and not is_profile_pic_url(vurl):
            media_list.append({
                "url": vurl,
                "type": "video",
                "taken_at": node.get("taken_at_timestamp", taken_at),
            })
    else:
        iurl = node.get("display_url", "")
        if iurl and not is_profile_pic_url(iurl):
            media_list.append({
                "url": iurl,
                "type": "image",
                "taken_at": node.get("taken_at_timestamp", taken_at),
            })

    return media_list


def find_media_in_json(data, seen_ids: set, results: list):
    """
    遞迴搜尋 JSON 結構中的貼文節點，萃取所有媒體 URL。
    同時支援 GraphQL edge 格式與 App API 格式。
    """
    if isinstance(data, dict):
        # App API 格式：items[] 陣列（例如 /api/v1/feed/user/ 回應）
        items = data.get("items")
        if isinstance(items, list):
            for item in items:
                pk = item.get("pk") or item.get("id")
                if pk and pk not in seen_ids:
                    seen_ids.add(pk)
                    taken_at = item.get("taken_at", 0)
                    results.extend(extract_media_from_node(item, taken_at))

        # GraphQL 格式：edge_owner_to_timeline_media / edges[].node 等
        for key in (
            "edge_owner_to_timeline_media",
            "edge_user_to_photos_of_you",
            "xdt_api__v1__feed__user_timeline_graphql_connection",
        ):
            edge_section = data.get(key)
            if isinstance(edge_section, dict):
                for edge in edge_section.get("edges", []):
                    node = edge.get("node", {})
                    shortcode = node.get("shortcode") or node.get("id") or node.get("pk")
                    if shortcode and shortcode not in seen_ids:
                        seen_ids.add(shortcode)
                        ts = node.get("taken_at_timestamp", 0) or node.get("taken_at", 0)
                        results.extend(extract_media_from_node(node, ts))

        # 繼續遞迴其他鍵
        for value in data.values():
            if isinstance(value, (dict, list)):
                find_media_in_json(value, seen_ids, results)

    elif isinstance(data, list):
        for item in data:
            find_media_in_json(item, seen_ids, results)


# ── 單一貼文爬取 ─────────────────────────────────────────────────────────────

async def scrape_post(post_url: str) -> list[dict]:
    """
    使用 Playwright 載入單一 Instagram 貼文頁面，
    攔截含媒體資料的回應並萃取媒體。
    """
    use_session = os.path.exists(COOKIES_FILE)
    if use_session:
        print(f"🔑 偵測到 Instagram 登入 session（{COOKIES_FILE}），將以登入狀態爬取")
    else:
        print("   未偵測到登入 session，以訪客模式爬取")
        print("   ⚠️  Instagram 對未登入訪客限制嚴格，建議先執行 --login-instagram")

    print(f"🌐 開啟瀏覽器，載入貼文：{post_url}")
    all_json_blobs: list[str] = []

    MEDIA_KEYWORDS = (
        "display_url", "video_url", "image_versions2",
        "video_versions", "edge_owner_to_timeline_media",
        "carousel_media", "shortcode",
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context_kwargs: dict = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 900},
            "locale": "zh-TW",
            "timezone_id": "Asia/Taipei",
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
                    if any(kw in text for kw in MEDIA_KEYWORDS):
                        all_json_blobs.append(text)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            await page.goto(post_url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"⚠️  頁面載入警告（將繼續）：{e}")

        await asyncio.sleep(2)
        await browser.close()

    print(f"📦 共收集到 {len(all_json_blobs)} 個含媒體資料的 JSON 片段，開始解析...")
    seen_ids: set = set()
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

        find_media_in_json(data, seen_ids, all_media)

    print(f"✅ 找到 {len(all_media)} 個媒體檔案")
    return all_media


# ── 登入 ──────────────────────────────────────────────────────────────────────

async def do_login():
    """開啟有介面的瀏覽器讓使用者手動登入 Instagram，完成後儲存 session。"""
    print("🔐 開啟瀏覽器，請在瀏覽器中完成 Instagram 登入...")
    print("   登入完成後程式會自動偵測並儲存 session，請勿手動關閉瀏覽器。")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        await page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle", timeout=30000)
        print("   等待登入完成（偵測到已登入後自動儲存）...")
        try:
            # 等待直到 URL 不再包含 login
            await page.wait_for_url(
                lambda url: "login" not in url and "instagram.com" in url,
                timeout=180000,
            )
        except Exception:
            print("⚠️  等待逾時，嘗試直接儲存目前 session...")
        await asyncio.sleep(2)
        await context.storage_state(path=COOKIES_FILE)
        await browser.close()

    print(f"✅ Instagram 登入 session 已儲存至：{COOKIES_FILE}\n")


# ── 網頁爬取 ──────────────────────────────────────────────────────────────────

async def scrape_profile(profile_url: str) -> list[dict]:
    """
    使用 Playwright 載入 Instagram 個人頁面並向下滾動，
    攔截所有含媒體資料的 XHR/Fetch JSON 回應，回傳媒體列表。
    """
    use_session = os.path.exists(COOKIES_FILE)
    if use_session:
        print(f"🔑 偵測到 Instagram 登入 session（{COOKIES_FILE}），將以登入狀態爬取")
    else:
        print("   未偵測到登入 session，以訪客模式爬取")
        print("   ⚠️  Instagram 對未登入訪客限制嚴格，建議先執行 --login-instagram")

    print(f"🌐 開啟瀏覽器，載入頁面：{profile_url}")

    # 收集所有含媒體資訊的 JSON blob
    all_json_blobs: list[str] = []

    # 用來判斷哪些 URL 包含媒體資料的關鍵字
    MEDIA_KEYWORDS = (
        "display_url", "video_url", "image_versions2",
        "video_versions", "edge_owner_to_timeline_media",
        "carousel_media", "shortcode",
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context_kwargs: dict = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 900},
            # 設定語言與時區讓 Instagram 認為是正常瀏覽器
            "locale": "zh-TW",
            "timezone_id": "Asia/Taipei",
        }
        if use_session:
            context_kwargs["storage_state"] = COOKIES_FILE

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        async def handle_response(response):
            """攔截 XHR/Fetch 回應，收集含媒體資料的 JSON"""
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct or "javascript" in ct:
                    body = await response.body()
                    text = body.decode("utf-8", errors="ignore")
                    # 只保留含媒體資訊的回應
                    if any(kw in text for kw in MEDIA_KEYWORDS):
                        all_json_blobs.append(text)
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            await page.goto(profile_url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"⚠️  頁面載入警告（將繼續）：{e}")

        # 等待頁面主要內容出現
        await asyncio.sleep(2)

        # 檢查是否為私人帳號或不存在
        page_text = await page.inner_text("body")
        if any(kw in page_text for kw in [
            "This account is private", "Sorry, this page isn't available",
            "Page Not Found", "此帳號為私人帳號",
        ]):
            print("❌ 此帳號為私人帳號或不存在，無法爬取內容。")
            await browser.close()
            return []

        # Instagram 需要滾動讓 API 持續回傳更多貼文
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

        await browser.close()

    # 解析所有收集到的 JSON blob
    print(f"📦 共收集到 {len(all_json_blobs)} 個含媒體資料的 JSON 片段，開始解析...")

    seen_ids: set = set()
    all_media: list[dict] = []

    for blob in all_json_blobs:
        # 部分回應前面有 "for (;;);" 之類的前綴，嘗試跳過
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

        find_media_in_json(data, seen_ids, all_media)

    print(f"✅ 共找到 {len(seen_ids)} 篇不重複貼文，{len(all_media)} 個媒體檔案")
    return all_media
