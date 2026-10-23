"""全量回归：跑所有测试套件，汇总结果。

跑法：python -X utf8 tools/run_all_tests.py
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable

SUITES = [
    ("判定回归（39 题真实抓屏）", "src/test_regression.py"),
    ("解析器单测", "src/test_parse.py"),
    ("屏幕准入（非答题页不误判）", "src/test_screens.py"),
    ("功能单测（配置/控分/AI解析/超时/回填）", "src/test_features.py"),
    ("AI 联网路径（本地假接口）", "src/test_ai_http.py"),
    ("桌面后端（HTTP 接口）", "app/test_backend.py"),
    ("画面流集成（假 adb 注入）", "app/test_screen_stream.py"),
]

results = []
for name, rel in SUITES:
    path = ROOT / rel
    if not path.exists():
        results.append((name, rel, "缺失", ""))
        continue
    t0 = __import__("time").perf_counter()
    p = subprocess.run([PY, "-X", "utf8", str(path)],
                       cwd=str(ROOT), capture_output=True, timeout=300)
    dt = __import__("time").perf_counter() - t0
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    status = "通过" if p.returncode == 0 else "失败"
    tail = ""
    if p.returncode != 0:
        # 抓最后几行有信息量的
        lines = [ln for ln in out.splitlines() if ln.strip()]
        tail = " | ".join(lines[-3:])[:200]
    results.append((name, rel, status, f"{dt:.1f}s  {tail}"))

print()
print("=" * 78)
print("全量回归结果")
print("=" * 78)
ok = fail = miss = 0
for name, rel, status, extra in results:
    mark = {"通过": "OK  ", "失败": "FAIL", "缺失": "----"}[status]
    print(f"  [{mark}] {name}")
    print(f"         {rel}  {extra}")
    if status == "通过":
        ok += 1
    elif status == "失败":
        fail += 1
    else:
        miss += 1

print("=" * 78)
print(f"  通过 {ok} / 失败 {fail} / 缺失 {miss}  共 {len(results)} 套")
print("=" * 78)

sys.exit(0 if fail == 0 and miss == 0 else 1)
