@echo off
cd /d "%~dp0\.."
chcp 65001 >nul
echo 正在為您清理虛擬環境與解除安裝所有依賴項...

if exist ".venv" (
    echo [執行] 刪除 .venv 資料夾...
    rmdir /s /q .venv
) else (
    echo [略過] 找不到 .venv 資料夾。
)

if exist "uv.lock" (
    echo [執行] 刪除 uv.lock 檔案...
    del /f /q uv.lock
) else (
    echo [略過] 找不到 uv.lock 檔案。
)

:: 若有傳統的 requirments.txt 產生之殘留，也可以斟酌加入清理其他 pycache
echo [執行] 清理 Python 暫存檔...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"

echo.
echo 完成！所有的依賴項與環境都已經乾淨清除了。
echo 若要重新安裝，請隨時再次執行「uv sync」或建立新環境。
echo.
pause
