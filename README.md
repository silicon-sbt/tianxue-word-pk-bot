<div align="center">

# 天学网单词PK助手

**基于 ADB + 无障碍树的自动化答题脚本**
不截屏、不 OCR、不调用大模型 —— 纯本地判定，单题 1.8 毫秒

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)]()
[![ADB](https://img.shields.io/badge/Requires-ADB-3DDC84?logo=android&logoColor=white)]()
[![Tests](https://img.shields.io/badge/Tests-39%2F39-brightgreen)]()

</div>

---

## 这是什么

天学网「单词大 PK」是 1v1 限时答题：每题 6 秒，从 6 个漂浮选项中选出正确释义。

这个脚本通过 ADB 读取 Android 无障碍树拿到题面和选项，用**离线词典**判定答案，再自动点击。

```
dump 屏幕(3.5s) ──► 解析题面+选项+实时坐标 ──► 离线判定(1.8ms) ──► 点击(0.16s)
```

**实测成绩**：单局 130 题中自动作答 34 题 → 33 题确定命中 + 2 题兜底猜测，**0 误判**。

---

## 几个设计取舍

### 不用 OCR

很多人第一反应是截屏 + OCR。但 Android 的**无障碍树里题目和选项就是纯文本**，`uiautomator dump` 直接能拿到，比图像识别准确、快、且零依赖。

### 不缓存坐标

选项位置**每次刷新都在随机漂浮**。所以脚本从不缓存坐标 —— 每帧都重新取当前这一帧的位置再点击。

### 不用云端大模型

第一版曾考虑用决策模型（如 [Jev](https://simonwillison.net/2026/Sep/21/jev/)）判答案。实测后放弃：

| 方案 | 单题判定耗时 |
|---|---|
| 本地词典 | **1.8 ms** |
| 云端 API | ~1000 ms（光网络往返就 660 ms）|

判定本质是「查表」，不是需要推理的问题。**慢 500 倍的方案没有意义**。

### 拿不准就猜，绝不留空

约 12% 的题本地词典查不到（详见[已知限制](#已知限制)）。空着必然 0 分，猜至少有 ~1/6 概率蒙对，所以脚本会猜 —— 但优先猜**语义最接近**的那个，而不是纯随机。

---

## 判定：为什么不能直接查表

这是整个项目最麻烦的地方。**PK 用教材释义，词典用通用释义，两套措辞不同源**：

| 题面 | 词典里的写法 | 字面相同？ |
|---|---|---|
| `adj.宏伟的` | grand = **雄伟的** | ✗ |
| `adj.异常的` | unusual = **不寻常的** | ✗ |
| `v.破坏` | destroy = **毁坏**、**摧毁** | ✗ |

直接查表全部落空。所以改用**反向打分**：拿每个选项词的**全部词典义项**，与题面比中文相似度，取最高分。

三层机制叠加：

1. **同义词归一化** —— 人工搭桥「异常 ↔ 不寻常」「宏伟 ↔ 雄伟」
2. **汉字相似度** —— Jaccard + 包含关系（`活的` ⊂ `活着的`）
3. **领先裕度判定** —— 分数不高但明显领先第二名时也接受

题型还是**双向**的，两个方向都要处理：

| 方向 | 题面 | 选项 |
|---|---|---|
| `zh2en` | 中文 `v.破坏` | 英文 `destroy` / `school` / ... |
| `en2zh` | 英文 `harmony` | 中文 `n.融洽相处` / `n. 歌` / ... |

---

## 快速开始

**环境要求**：Windows + Python 3.10+ + 手机开启 USB 调试

```bash
git clone https://github.com/silicon-sbt/tianxue-word-pk-bot.git
cd tianxue-word-pk-bot
```

1. 手机 USB 连电脑，开启「开发者选项 → USB 调试」
2. 打开天学网 App，进入 PK 房间页面
3. 双击 **`启动.vbs`**（纯后台运行，不弹黑框）
4. 在手机上点「开始 PK」—— 脚本自动接管

脚本会**等待**答题页出现（默认 10 分钟），不用掐时间。

| 文件 | 用途 |
|---|---|
| `启动.vbs` | **正常用这个** — 后台运行，结束时弹结果 |
| `查看日志.bat` | 运行中随时看答到第几题 |
| `停止.bat` | 中途停止（只杀本项目进程） |
| `启动.bat` | 排错用 — 保留了控制台窗口，能看完整输出 |

<details>
<summary>手动运行 / 命令行参数</summary>

```bash
# 全自动实打（会真的点击）
python -X utf8 src/run_watch.py --live

# 只读不点 —— 验证判定准确率，不影响成绩
python -X utf8 src/run_watch.py

# 直接跑（假设已在答题页）
python -X utf8 src/pk_bot.py --live --max 50
```

| 参数 | 说明 | 默认 |
|---|---|---|
| `--live` | 真实点击（不加则只读） | off |
| `--max N` | 最多作答几题 | 130 |
| `--wait S` | 等待答题页多久 | 480s |
| `--minutes M` | 运行上限 | 30 min |

</details>

---

## 项目结构

```
启动.vbs             无窗口启动器（日常用这个）
查看日志.bat          运行中查看进度
停止.bat              中途停止
启动.bat              排错用（保留控制台输出）
src/
  pk_core.py          屏幕解析 + 双向词库判定   ← 核心逻辑
  adb_driver.py       ADB 封装（dump/点击/前台检测）
  pk_bot.py           答题主循环 + 统计
  run_watch.py        等待版入口
  build_bank.py       从 ed.db 构建词库
  learn.py            未匹配题自学习
  test_regression.py  回归测试（39 题真实抓屏）
data/
  wordbank.json       词库：14,030 词 / 42,942 义项
tools/dev/           开发期诊断脚本（归档，非必需）
```

---

## 词库

词库从 App 自带的 `ed.db`（16,915 词条）构建，规模 **14,030 词 / 42,942 义项**。

> **仓库只带构建好的 `wordbank.json`（1.2 MB），不带 `ed.db`（10.4 MB）**。
> `ed.db` 是天学网 App 内的词典数据，属第三方内容，不适合直接分发。
> 日常使用只需 `wordbank.json`；只有想重建词库时才需要 `ed.db`。

<details>
<summary>重建词库</summary>

```bash
# 1. 从手机拉取（先在 App 里打开一次「词典」功能触发下载）
adb pull /sdcard/Android/data/com.up366.mobile/files/dictV1/db/ed.db data/ed.db

# 2. 构建
python -X utf8 src/build_bank.py
```

</details>

<details>
<summary>补漏（自学习）</summary>

判定不了的题会记进 `data/unknown.jsonl`：

```bash
python -X utf8 src/learn.py --report                 # 看待补清单
python -X utf8 src/learn.py --add "update=最新消息"   # 手工登记
```

登记后写入 `data/learned.json`，下次直接命中。

</details>

---

## 测试

```bash
python -X utf8 src/test_regression.py   # 39/39
python -X utf8 src/test_parse.py        # 解析器单测
```

`test_regression.py` 的用例**全部来自实机抓屏**，每题都对应一个踩过的坑。改动判定逻辑后必须全绿。

---

## 踩过的坑

这些都是实测踩到并修掉的，改动相关代码前建议先看一眼。

<details>
<summary><b>1. <code>adb shell cat</code> 返回 UTF-16，管道会二次破坏</b></summary>

直接 `adb shell cat` + 重定向拿到的是 UTF-16（每个 ASCII 字符后跟一个 NUL），所有 `text="..."` 都提取不到。

**必须用 `adb exec-out` 读原始字节**再自己解码。见 `decode_dump()`。

</details>

<details>
<summary><b>2. <code>uiautomator dump</code> 会偶发失败</b></summary>

实测 6 次里失败 4 次，且 adb 返回**非零退出码**。必须显式容忍并重试，否则整个循环被异常打断。

</details>

<details>
<summary><b>3. 切题瞬间会读到「混合画面」</b></summary>

表现为选项变成 7 个且末项重复（新旧两题的选项混在一起）。

**曾用「连 dump 两次比对」检测 —— 结果耗时从 3s 飙到 11-13s，直接打爆 6 秒限时。** 现改为零成本结构判断（`_looks_transitional`）。

</details>

<details>
<summary><b>4. 单字子串不是匹配</b></summary>

`像`（resemble）是 `图像` 的子串，会被误判成答案。**子串匹配要求两边都 ≥2 字**。

</details>

<details>
<summary><b>5. 词库里的垃圾义项</b></summary>

`vi. & vt.` 这类纯词性串被 `/` 切开后会留下 `&`，与选项解析串味，造成 `tend → 举起` 误判。构建时已过滤。

另外 `（建筑物，城镇等的）地点` 会被括号内的逗号切碎，需要**括号感知切分**。

</details>

<details>
<summary><b>6. 别去调全局相似度公式</b></summary>

试过加「覆盖率惩罚」修 `像/图像` 的问题，结果**直接弄坏 3 道原本正确的题**。

正确做法是在**决策层**加针对性规则，不要动全局公式。

</details>

<details>
<summary><b>7. 启动脚本的编码与换行符（改这两个文件前必读）</b></summary>

`启动.vbs` 和 `.bat` 对编码非常挑剔，一开始两个都写错了：

**`.bat` 必须是 CRLF 换行。** 用 LF-only 存会看到命令被逐字拆散：

```
'HIDDEN' is not recognized as an internal or external command
'e_if_visible' is not recognized as an internal or external command
```

因为 cmd.exe 按 CRLF 切分，LF-only 会让 `(` `)` 块和 `:label` 全部错位。

**`.vbs` 必须是 UTF-16LE + BOM。** wscript 按系统 ANSI 码页读 `.vbs`，UTF-8 中文会乱码成空字符串。

**`.bat` 里一律不写非 ASCII。** cmd.exe 按系统 ANSI 码页读 `.bat`，中文在别的语言环境下会打乱命令解析。所有面向用户的中文提示都放在 `.vbs`（UTF-16 可靠）。

改完用这两条自检：

```powershell
# .bat 应为纯 ASCII + 全 CRLF
$b=[IO.File]::ReadAllBytes("启动.bat"); ($b|?{$_ -gt 127}).Count   # 期望 0
# .vbs 前两字节应为 FF FE
$b=[IO.File]::ReadAllBytes("启动.vbs"); '{0:X2} {1:X2}' -f $b[0],$b[1]
```

</details>

---

## 已知限制

- **约 12% 的题判定不了** —— 教材释义在词典里根本不存在。例如 `site` 在 `ed.db` 里只有「地点/现场」，**没有「网站」**；`element` 没有「基本部分」。这是**数据缺失，不是算法问题**。这些题会走猜测分支。
- **dump 耗时 2.4-8s 波动** —— 4 秒限时下会漏题，6 秒限时基本够用。想更稳可用 `screencap`（0.6s）替代，但需自己做图像识别。
- **必须在答题页才工作** —— 脚本会等待，但不会替你点「开始 PK」。

---

## 免责声明

本项目仅供**技术学习与个人研究**，用于理解 Android 无障碍服务、ADB 自动化与中文语义匹配。

- 使用者需为自己的账号行为负责
- 分数会真实计入账号与班级排行
- 请勿用于代替他人作答或任何违反平台服务条款的场景
- 项目不含任何天学网的词典数据或私有接口，词库需使用者自行从本地设备构建

