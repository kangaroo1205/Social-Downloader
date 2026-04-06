import os
import sys


def get_base_dir() -> str:
    """返回應用程式的基礎目錄。

    打包為 exe 時返回 exe 所在目錄；
    一般執行時返回專案根目錄（src/core/ 往上兩層）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
