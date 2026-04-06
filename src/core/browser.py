import os
import subprocess
import sys


def ensure_chromium() -> None:
    """確保 Playwright Chromium 瀏覽器已安裝。

    若已安裝則快速跳過，若未安裝則自動下載（約 200MB）。
    瀏覽器安裝在 %LOCALAPPDATA%\ms-playwright，跨執行持續有效。
    """
    # 強制 Playwright 把瀏覽器裝在永久路徑，而非 PyInstaller 的臨時目錄
    browsers_path = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ms-playwright"
    )
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

    # 加快檢查：如果已經有 chromium 資料夾，就直接略過
    if os.path.exists(browsers_path):
        try:
            for item in os.listdir(browsers_path):
                if item.startswith("chromium-"):
                    return
        except OSError:
            pass

    try:
        from playwright._impl._driver import compute_driver_executable

        driver_exec, driver_cli = compute_driver_executable()
        print("Checking Chromium browser...")
        result = subprocess.run(
            [str(driver_exec), str(driver_cli), "install", "chromium"],
            capture_output=True,
            text=True,
            env=os.environ,
        )
        if result.returncode != 0:
            print(f"Chromium install failed:\n{result.stderr}")
            sys.exit(1)
    except Exception as e:
        print(f"Chromium check failed: {e}")
        sys.exit(1)
