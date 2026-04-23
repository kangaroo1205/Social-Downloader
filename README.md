# Social Downloader

一個輕鬆將 Threads、Instagram 與 X (Twitter) 上的圖片與影片一網打盡的懶人下載小幫手！自動幫你分門別類、依日期整理，再也不用一張張手動存。

## ✨ 特色 (Features)

- **多平台支援**：自動偵測網址並觸發對應的下載器（支援 Threads、Instagram、X）。
- **兩種模式**：
  - **單一貼文**：只抓取該篇貼文的媒體。
  - **個人頁面（Profile）**：一口氣把帳號下能抓的媒體都抓回來。
- **自動分類命名**：檔案會保存在 `media/{platform}@{username}` 下，並自動依照拍攝時間 `YYYY_MM_DD_N.ext` 格式整齊命名。
- **內建自動登入與 GUI**：可以使用 `--login-*` 參數開啟瀏覽器手動登入。若直接執行不帶參數，還會彈出小巧的輸入視窗方便貼網址。
- **優雅地非同步下載**：使用 `asyncio` + `httpx` 並發下載，自動重試與錯誤處理，網路不穩也不怕！
- **精準的網址解析**：透過內建的 `urlparse` 強化防呆機制，不怕網址打錯或遇到釣魚參數。
- **絕美終端日誌**：全面導入 `loguru`，不管是下載進度、成功或報錯，終端機輸出都變得層次分明又賞心悅目。

## 🚀 環境與安裝 (Installation)

確認你有 **Python 3.13+**，然後就可以開始了：

```bash
# 1. 建立虛擬環境 (如果習慣的話)
python -m venv .venv

# 2. 啟動虛擬環境 (以 Windows 為例)
.venv\Scripts\activate

# 3. 安裝專案依賴
uv sync 
# （當然，如果你習慣比較傳統的作法，也可以用 pip install -e .）
```

> **備註**：核心爬蟲機制依賴 `playwright`。程式第一次執行時會自動檢查並幫你安裝對應的 Chromium 瀏覽器（約 200MB），不用再手動搞環境，超貼心。

## 💡 如何使用 (Usage)

統一由 `src/main.py` 進入程式，下面是一些常見指令：

### 一般下載

```bash
# 只要丟網址給它，它就會自己判斷要呼叫哪家爬蟲
uv run src/main.py "https://www.instagram.com/p/xxxxxx/"
uv run src/main.py "https://www.threads.net/@xxxxxx/post/yyyyyy"
uv run src/main.py "https://x.com/xxxxxx/status/yyyyyy"
```

### 登入模式 (遇到私人帳號或權限問題時)

```bash
# 會開啟瀏覽器，讓你輸入一次密碼並儲存 session
uv run src/main.py --login-instagram
uv run src/main.py --login-threads
uv run src/main.py --login-x
```

如果不加上任何網址直接執行 `uv run src/main.py`，程式會自動問你要下載哪裡，超適合不想記指令的時候使用。

## 🎁 萬用小工具 (Scripts)

專案底下的 `scripts/` 目錄內建了兩支方便的 Windows 批次檔，點擊兩下就能幫你搞定麻煩事：

- **打包成執行檔 (`scripts\build.bat`)**：
  內建一鍵打包！它會自動呼叫 PyInstaller 幫你把專案編譯成單一執行檔。完成後會在 `dist/` 資料夾產出一個 `SocialDownloader.exe`。以後想下載東西，連終端機都不用開，直接點兩下 `exe` 就能執行，傳給朋友用也超級方便！

- **環境大掃除 (`scripts\uninstall_deps.bat`)**：
  覺得環境卡卡或想重新來過？點這支腳本，它會輕輕柔柔地幫你把 `.venv` 虛擬環境、`uv.lock` 和一堆討厭的 `__pycache__` 暫存檔吃得乾乾淨淨，還你一個最純淨的專案。

## 🛠️ 程式架構與設計 (Architecture)


模組化分工明確，如果有興趣加新功能，可以參考以下架構：

- `src/main.py`: 統籌中心，負責參數解析與平台分流
- `src/core/`: 共用的核心工具
  - `browser.py`: 負責瀏覽器的驗證與啟動
  - `downloader.py`: 非同步連線下載、處理 `MAX_CONCURRENT` 排隊與重新嘗試機制
  - `paths.py`: 單純的路徑規劃器
- `src/scrapers/`: 第一線打拼的爬蟲專員們 (`threads.py`, `instagram.py`, `x.py`)
