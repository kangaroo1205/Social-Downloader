# Social Media Downloader

這是一個用 Python 撰寫的社群媒體下載工具，支援自動辨識 **Threads** 與 **Instagram** 網址，只需輸入 URL 即可下載指定帳號的圖片與影片。

## 功能特色

- 🔍 **自動分流**：自動根據 URL 網域判斷平台，無須切換腳本
- 🖼️ 支援下載圖片（最高解析度）、影片、多圖輪播貼文
- 🔐 支援登入模式（儲存 Session），可突破訪客瀏覽限制
- ⚡ 非同步並行下載，速度更快
- 📁 以 `YYYY_MM_DD_N.ext` 格式自動整理命名，儲存至對應帳號資料夾

## 環境需求

- Python >= 3.13
- 建議使用 [uv](https://github.com/astral-sh/uv) 進行套件管理

## 安裝步驟

```bash
# 1. 同步虛擬環境與依賴
uv sync

# 2. 安裝 Playwright 瀏覽器
uv run playwright install chromium
```

## 使用方法

### 下載媒體（自動辨識平台）

```bash
# 下載 Instagram 帳號媒體
uv run src/main.py https://www.instagram.com/username

# 下載 Threads 帳號媒體
uv run src/main.py https://www.threads.com/@username

# 不帶參數執行，程式會提示輸入 URL
uv run src/main.py
```

### 登入模式（建議先執行，爬取更多內容）

Instagram 與 Threads 對未登入訪客的限制較嚴格，建議首次使用前先執行登入：

```bash
# 登入 Instagram（儲存至 instagram_session.json）
uv run src/main.py --login-instagram

# 登入 Threads（儲存至 threads_session.json）
uv run src/main.py --login-threads
```

執行後會開啟瀏覽器視窗，請手動完成登入。登入成功後 session 會自動儲存，之後執行下載時便會自動帶入登入狀態。

## 封裝為執行檔 (Build EXE)

如果你想要將程式打包成獨立的 `.exe` 檔案（方便在沒有安裝 Python 的電腦執行）：

1. 進入 `scripts/` 資料夾。
2. 點兩下執行 `build.bat`。
3. 等待完成後，執行檔會產出在 `dist/SocialDownloader.exe`。

> [!NOTE]
> 打包過程會自動將 `data/` 資料夾複製到 `dist/` 目錄下，確保登入資訊可以被讀取。

## 輸出資料夾

| 平台 | 儲存路徑 |
|------|---------|
| Instagram | `media/instagram@<username>/` |
| Threads | `media/threads@<username>/` |

檔名格式：`YYYY_MM_DD_N.ext`（例：`2024_03_25_1.jpg`）

## 專案結構

```
Social Downloader/
├── src/                  # 應用程式原始碼
│   ├── main.py           # 統一入口（自動分流）
│   ├── scrapers/         # 各平台爬取模組
│   └── core/             # 共用核心與下載工具
├── scripts/              # 建置與輔助腳本
│   ├── build.bat         # 封裝執行檔腳本
│   ├── uninstall_deps.bat
│   └── social_downloader.spec
├── media/                # 下載媒體輸出目錄
├── data/                 # Session 與設定檔目錄
```

## 注意事項

- 請勿將此工具用於非法用途或侵犯他人版權。
- Instagram / Threads 若更動網頁架構或 API 格式，此工具可能須同步更新。
- 若遇到爬取數量少的問題，請先執行登入模式（`--login-instagram` / `--login-threads`）。
