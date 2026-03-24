# Threads 媒體下載器 (Threads Media Scraper)

這是一個用 Python 撰寫的 Threads 媒體下載工具，可以幫助你自動化下載指定 Threads 帳號的圖片與影片。工具使用 Playwright 模擬瀏覽器行為進行滾動載入，並擷取網頁中的高畫質媒體檔案。

## 功能特色
- 支援自動找尋並下載指定 Threads 帳號的圖片 (最高解析度) 與影片。
- 自動處理多圖輪播 (Carousel) 貼文。
- 支援「登入模式」(儲存登入 Session)，讓你能夠爬取更多貼文內容。
- 支援非同步並行下載 (Concurrent Downloads)，提升下載速度。
- 檔案自動以「年份_月份_日期_序號」命名整理，並集中存在專屬資料夾 (如 `media/threads@username`) 中。

## 環境需求
- Python >= 3.13
- 此專案使用 `uv` 進行套件管理 (也可使用標準的 `pip`)。

## 安裝步驟

1. 確保你已安裝 Python 3.13 以上版本，並建議安裝 [uv](https://github.com/astral-sh/uv)。
2. 透過 uv 自動同步環境（這會自動建立虛擬環境並安裝依賴）：
   ```bash
   # 使用 uv 進行環境同步 (推薦)
   uv sync
   ```
   *若不使用 uv，請手動建立虛擬環境並執行 `pip install httpx>=0.28.1 playwright>=1.58.0`*

3. 安裝 Playwright 所需的瀏覽器（使用 uv 執行）：
   ```bash
   uv run playwright install chromium
   ```

## 使用方法

### 透過 uv 執行 (推薦)
使用 `uv run` 可以自動在虛擬環境中執行腳本，無需手動啟動 venv：

```bash
# 執行下載
uv run threads_scraper.py https://www.threads.com/@username

# 執行登入模式
uv run threads_scraper.py --login
```

### 傳統執行方式
若你沒有透過 `uv run`，請先確定已手動啟動虛擬環境 (.venv)，然後直接執行：

```bash
python threads_scraper.py
```
程式執行後，便會提示你輸入要爬取的網址。

### 登入模式 (爬取更多內容)
如果你發現爬取的貼文數量有限，可能是因為未登入的限制。你可以執行以下指令來進入登入模式：

```bash
python threads_scraper.py --login
```
這會開啟一個瀏覽器視窗，請手動在視窗中完成 Instagram / Threads 登入。登入完成後，程式會自動將 Session 儲存到 `threads_session.json`。之後再次執行爬蟲便會自動帶入登入狀態。

## 輸出路徑
所有下載的媒體檔案將會被分類儲存至專案目錄下的 `media/threads@<username>` 資料夾中，檔名格式為 `YYYY_MM_DD_N.ext`。

## 清理與重置環境
若後續有移除所有依賴項、重置虛擬環境的需求，專案內附有 `uninstall_deps.bat`：
- Windows 用戶請直接**連按兩下執行 `uninstall_deps.bat`**，即可一鍵清除所有環境與快取。
- 若需再次安裝，只需重新執行 `uv sync` 即可再次快速建置。

## 注意事項
- 請勿將此工具用於非法用途或侵犯他人版權。
- 若 Threads 官方更動了網頁架構或 API 格式，此工具可能須同步更新才能繼續正常運作。
