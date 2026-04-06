# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# 找到 playwright driver 目錄（包含 node.exe 與 cli.js）
import playwright as _pw
playwright_driver = os.path.join(os.path.dirname(_pw.__file__), "driver")

a = Analysis(
    ["../src/main.py"],
    pathex=["../src"],
    binaries=[],
    datas=[
        (playwright_driver, "playwright/driver"),
    ],
    hiddenimports=[
        "playwright",
        "playwright.async_api",
        "playwright._impl._driver",
        "httpx",
        "httpx._transports.default",
        "tkinter",
        "scrapers.threads",
        "scrapers.instagram",
        "scrapers.x",
        "core.downloader",
        "core.paths",
        "core.browser",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SocialDownloader",
    debug=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)
