"""一键打包：exe + 运行时资源 + zip 便携版。

跑法：python -X utf8 tools/build.py [--skip-exe]

产出：
  dist/TianxuePK/          可直接运行的目录
  pk_release\TianxuePK-Portable-vX.Y.Z.zip

为什么要有这个脚本而不是手敲命令：
  复制运行时资源时**目录创建顺序**很容易错（先复制文件后建目录会把目录变成文件，
  实测踩过），这里统一按「先建目录、再放文件」的顺序做。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "TianxuePK"
# 产物必须放纯 ASCII 路径：实测安装包放在含中文的目录（如 单词pk）下运行，
# Inno 初始化会失败（退出码 1，连 /LOG 都不生成）；换英文目录就正常。
RELEASE = Path(r"E:\pk_release")
PY = sys.executable
VERSION = "1.0.0"

# 需要跟 exe 放在一起的运行时资源（源路径 -> 目标相对路径）
RUNTIME_FILES = [
    ("config.toml", "config.toml"),
    ("data/wordbank.json", "data/wordbank.json"),
]
RUNTIME_DIRS = [
    ("src", "src"),
    ("tools", "tools"),
    # app/ 必须一起带上：main.py / screen_stream.py 在这个目录，
    # 少了它 exe 起来后后端导入失败，表现为「后端 20 秒内没起来」。
    ("app", "app"),
]
RUNTIME_EMPTY_DIRS = ["logs", "data"]


def run(cmd: list[str], **kw) -> int:
    print("  $", " ".join(str(c) for c in cmd[:4]), "..." if len(cmd) > 4 else "")
    return subprocess.run(cmd, cwd=str(ROOT), **kw).returncode


def build_exe() -> bool:
    print("\n[1/4] 打包 exe ...")
    t0 = time.time()
    rc = run([PY, "-X", "utf8", "-m", "PyInstaller", "build/app.spec",
              "--noconfirm", "--clean",
              "--distpath", str(ROOT / "dist"),
              "--workpath", str(ROOT / "build" / "work")])
    if rc != 0:
        print("  打包失败")
        return False
    print(f"  完成，{time.time()-t0:.0f}s")
    return True


def copy_runtime() -> None:
    """复制运行时资源。

    顺序很重要：**先建目录再复制文件**。反过来会把目录创建成同名文件，
    之后 mkdir 抛 FileExistsError（实测踩过，进程启动即死）。
    """
    print("\n[2/4] 复制运行时资源 ...")
    DIST.mkdir(parents=True, exist_ok=True)

    # 1) 先确保所有需要的目录存在
    for d in RUNTIME_EMPTY_DIRS:
        (DIST / d).mkdir(parents=True, exist_ok=True)
    for _, dst in RUNTIME_DIRS:
        (DIST / dst).mkdir(parents=True, exist_ok=True)

    # 2) 再复制文件（目标父目录已存在）
    for src_rel, dst_rel in RUNTIME_FILES:
        src = ROOT / src_rel
        dst = DIST / dst_rel
        if not src.exists():
            print(f"  跳过（源不存在）: {src_rel}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  {src_rel} -> {dst_rel}")

    # 3) 目录整体复制
    for src_rel, dst_rel in RUNTIME_DIRS:
        src = ROOT / src_rel
        dst = DIST / dst_rel
        if not src.exists():
            continue
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        print(f"  {src_rel}/ -> {dst_rel}/")

    # 4) 校验：data 必须是目录
    data = DIST / "data"
    if data.exists() and not data.is_dir():
        print("  !! data 被建成了文件，修正")
        data.unlink()
        data.mkdir(parents=True, exist_ok=True)


def make_zip() -> Path | None:
    print("\n[3/4] 打包 zip 便携版 ...")
    RELEASE.mkdir(parents=True, exist_ok=True)
    out = RELEASE / f"TianxuePK-Portable-v{VERSION}.zip"

    if out.exists():
        out.unlink()

    total = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"  压缩 {len(list(DIST.rglob('*')))} 项 / {total/1024/1024:.0f} MB ...")

    t0 = time.time()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(DIST.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(DIST.parent))
    print(f"  完成 {out.name}  {out.stat().st_size/1024/1024:.0f} MB  "
          f"{time.time()-t0:.0f}s")
    return out


def summary(zip_path: Path | None) -> None:
    print("\n[4/4] 结果")
    exe = DIST / "TianxuePK.exe"
    if exe.exists():
        size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
        print(f"  exe: {exe.name}  {exe.stat().st_size/1024:.0f} KB")
        print(f"  目录: {DIST}")
        print(f"  总计: {size/1024/1024:.1f} MB")
        # 校验无控制台
        b = exe.read_bytes()
        off = int.from_bytes(b[0x3C:0x40], "little")
        sub = int.from_bytes(b[off + 0x5C:off + 0x5E], "little")
        print(f"  PE 子系统: {sub}  ({'GUI 无控制台' if sub == 2 else 'Console 有黑框'})")
    if zip_path and zip_path.exists():
        print(f"  zip: {zip_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-exe", action="store_true", help="跳过 PyInstaller，只重做资源与 zip")
    a = ap.parse_args()

    if not a.skip_exe:
        if not build_exe():
            return 1

    copy_runtime()
    z = make_zip()
    summary(z)
    return 0


if __name__ == "__main__":
    sys.exit(main())
