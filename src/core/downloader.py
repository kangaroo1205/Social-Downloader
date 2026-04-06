#!/usr/bin/env python3
"""
downloader.py — 共用下載工具模組
提供 download_file、download_all、guess_extension、build_filename 等共用函式，
供 threads_scraper 與 instagram_scraper 引用。
"""

import asyncio
import os
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

import httpx

# ── 常數 ──────────────────────────────────────────────────────────────────────

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)
MAX_CONCURRENT = 5      # 同時下載數量
DOWNLOAD_TIMEOUT = 60   # 下載逾時秒數
MAX_RETRIES = 3         # 失敗重試次數


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def guess_extension(url: str, media_type: str) -> str:
    """根據 URL 或媒體類型推測副檔名"""
    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return ext.lstrip(".")
    if ext in (".mp4", ".mov", ".m4v", ".webm"):
        return ext.lstrip(".")
    return "mp4" if media_type == "video" else "jpg"


def build_filename(date_str: str, index: int, ext: str) -> str:
    """建立檔名，格式：YYYY_MM_DD_N.ext"""
    return f"{date_str}_{index}.{ext}"


# ── 下載邏輯 ──────────────────────────────────────────────────────────────────

async def download_file(
    client: httpx.AsyncClient,
    url: str,
    dest_path: str,
    semaphore: asyncio.Semaphore,
    referer: str = "https://www.instagram.com/",
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


async def download_all(
    media_list: list[dict],
    output_dir: str,
    referer: str = "https://www.instagram.com/",
):
    """
    將所有媒體並行下載至指定資料夾。
    media_list 每個元素格式：{"url": str, "type": "image"|"video", "taken_at": int}
    """
    os.makedirs(output_dir, exist_ok=True)

    # 按 taken_at 排序（舊到新），確保序號一致
    sorted_media = sorted(media_list, key=lambda m: (m["taken_at"], m["url"]))

    day_counters: dict[str, int] = defaultdict(int)
    tasks_info: list[tuple[str, str]] = []

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
    headers = {"User-Agent": USER_AGENT, "Referer": referer}

    print(f"\n📥 開始下載 {len(tasks_info)} 個媒體檔案至：{output_dir}")

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        coros = [
            download_file(client, url, dest_path, semaphore, referer)
            for url, dest_path in tasks_info
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)

    success = sum(1 for r in results if r is True)
    fail = len(results) - success
    print(f"\n🎉 下載完成！成功：{success} 個，失敗：{fail} 個")
