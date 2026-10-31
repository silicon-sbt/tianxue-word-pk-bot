"""仓库根目录。

这些诊断脚本按「相对仓库根」定位文件，克隆到任何目录都能直接跑，
不依赖作者本机的绝对路径。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
