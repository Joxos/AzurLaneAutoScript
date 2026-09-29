# AzurLaneAutoScript（Joxos fork）

本仓库是 [LmeSzinc/AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 的 fork。

仓库地址：https://github.com/Joxos/AzurLaneAutoScript

---

# ⚠ 本 fork 自有改动（不属于上游，请勿混淆）

> 这一节只描述**我们相对上游的差异**。上游自己的功能请看下文与上游仓库。
> 与上游 `master` 的差异规模：**745 个文件 / +382,976 −44,925**（不含 `campaign/`，
> 那部分是地图数据格式差异，见下表）。

## 1. 功能矩阵：相对上游改了什么

| 领域 | 上游 | 本 fork | 状态 |
|---|---|---|---|
| 前端 | `webapp/`（Electron + 13 个前端源文件，2026-09 新增，与我们无关） | `webapp/` **Svelte 5 + Vite + UnoCSS 从零重写**，语义化设计令牌，主题走 `data-theme`，后端 FastAPI 提供 REST+SSE | 完成 |
| 桌面壳 | 自带 Electron 打包 | **PyInstaller 双 exe**：`Alas.exe`（启动器，GUI 子系统）+ `alas-backend.exe`（console 子系统）。Tauri 壳 2026-09 归档 | 完成 |
| 系统托盘 | 有（Electron 提供） | **有**（pystray，随启动器分发），关窗口 = 隐藏到托盘，只有 Quit 才停机 | 完成，真机待验 |
| 安装包 | 自己的发布流程 | **自写 NSIS**（免管理员、装到 `%LOCALAPPDATA%`、升级前自动退旧版、卸载不动用户数据） | 完成，真机待验 |
| 应用内更新 | 无 | **有**：拉 release → 下载 setup.exe → 停任务 → 分离启动安装器 `/S /R` → 自动重启 | 完成，真机待验 |
| 入口 | 多脚本 | **单一 `alas` 命令**：`alas run headless/web/desktop`、`alas build frontend/sidecar/launcher/installer`、`alas doctor`、`alas version` | 完成 |
| 业务逻辑表达 | 散落各模块的 `while 1:` | **`module/flow/` 声明式执行核**（flow 数据 + 共享引擎 + 双跑等价门） | 进行中（详见 §4） |
| 地图数据 | `campaign/*.py` | **YAML/JSON + legacy snapshot**（1366 yaml / 1393 json / 667 py / 134 份快照），运行时天然广播 | 完成 |
| 任务清单 | 各任务自己 `run()` | `module/tasks/registry.py` 声明式任务表（含 family），调度与配置生成共用一份事实源 | 完成 |
| 设备层 | 全量 | 保留全部；**主动移除** uiautomator2 XPath 登录旧路径（handler 层） | 完成 |
| 工程门 | 无 | ruff 全树 0、pyright（运行时状态相关层）0、pytest 1459、导入冒烟 445/445、配置零漂移、地图数据 1366/1366、资产语义 1343/441、资产去冗余格式、**日志格对齐（真实浏览器逐行量）**、**识别参数 vs 上游 549 站点**、docker 打包静态检查 | 完成 |
| Docker | 官方镜像 | 多阶段构建，**镜像内含前端**（此前只发 API，干净检出会得到一个"看起来坏了"的镜像） | 完成，真机待验 |

### 我们修掉的、上游还没有的问题

| 问题 | 现象 | 根因 | 门 |
|---|---|---|---|
| 日志报错框右侧对不齐 | 满屏报错时 rich 框右边缘整片漂移（实测最差 −17.2px） | 浏览器按字体自然宽度渲染，后端按 rich 的格宽排版：CJK 实际 1.871 格（rich 按 2 格）、`✔✖⚠` 实际 1.1–2.5 格（rich 按 1 格） | `dev_tools/verify_log_align.mjs`（headless Edge 逐行量，修复后最差 0.03px） |
| 每条日志后多一个空行 | 日志看起来"行距 double" | rich capture 输出每行以 `ESC[0m\r` 结尾，`render_log` 只 `rstrip("\n")`，`\r` 被浏览器归一化成换行 | 同上门 + `helpers.py` 改 `rstrip("\r\n")` |
| 识别参数静默漂移 | 上游把 `image_color_count` 的 threshold 从"相似度下限"改成"容差"后，**所有没显式写阈值的颜色检查几乎恒真** | 调用点散落各处，无人比對上游 | `dev_tools/verify_thresholds.py`（AST 逐站点比对，549 站点） |
| 资产格式被上游覆盖 | 每次取上游 `assets.py` 就丢掉我们的四服同值折叠 | 上游统一写字典形式 | `dev_tools/dedup_assets.py`（AST 重写 + 语义等价门，CI 检查） |
| 升级链路从未成立 | CI 发 zip，updater 只认 `*setup*.exe` → 应用内更新必然失败 | 两条路径各自演进 | 见 §2 |

## 2. 更新流程与逻辑（本 fork 自有）

```
应用内（WebUI 主页 → 更新器）
  refresh ──► GET api.github.com/repos/Joxos/…/releases?per_page=30
           （或 ALAS_UPDATE_MIRROR 指定的镜像前缀，只影响下载源）
  install ──► 下载 <tag>_x64-setup.exe（进度回传前端）
           ──► 停所有运行中的任务（ProcessManager，等 ≤30s）
           ──► **分离启动**安装器 /S /R（DETACHED_PROCESS）
                 · 安装器要求 Alas.exe --quit 退掉旧版
                 · 替换整个程序目录（数据目录不在其中）
                 · /R 安装完自动拉起新版本
           ──► 本进程随后被安装器终止

离线/手动
  删掉旧 tag 重打（tag 不可重用）→ CI 重新构建
  或本地：alas build frontend → sidecar → launcher → installer
```

要点与边界：

- **数据目录分离**：程序目录 `%LOCALAPPDATA%\Programs\Alas`（可整体替换），
  用户数据 `%LOCALAPPDATA%\Alas`（`config/ log/ assets/ bin/`，更新不动）。
  启动器设置 `ALAS_DATA_DIR` 并以其为 CWD；frozen 后端在 `module/logger.py` 里
  `chdir` 到该目录。
- **为什么安装器必须分离启动**：它要替换正在运行的程序文件，必须活过后端进程；
  代价是"安装成功"无法同步确认（应用会被自己重启）。
- **崩溃可见**：控制台被隐藏，所以启动器把 sidecar 的 stderr 镜像到
  `<数据目录>/log/backend.log`；启动器自身的一切动作记 `log/launcher.log`。
- **未签名**：没有代码签名证书，SmartScreen 可能提示；不做自动更新校验。
- 源码检出不支持应用内安装（会明确报错），开发者用 git 更新。

## 3. 发布端（本 fork 自有）

```
git push origin master
git tag v2026.10.01 && git push origin v2026.10.01
        │
        └─ CI (.github/workflows/release.yml, windows-latest)
             uv sync --frozen → pnpm build（webapp/dist）
             → dev_tools/gen_app_icon.py（NSIS 只认 .ico）
             → pyinstaller alas_backend.spec（console）→ version.txt = tag
             → pyinstaller launcher.spec（GUI，带托盘）
             → **冒烟两个 exe**（sidecar version + 启动器存在）
             → makensis alas_installer.nsi  → Alas_<tag>_x64-setup.exe
             → softprops/action-gh-release 上传
```

- 版本号唯一事实源 = **tag**（应用内"当前版本"读 `version.txt`）。
- 产物结构：`%LOCALAPPDATA%\Programs\Alas\{Alas\Alas.exe, alas-backend\…}`。
- 免管理员安装（`RequestExecutionLevel user`），所以 `/S` 静默升级不会被 UAC 挡。
- nsi 缺失时回退 portable zip（此时应用内更新会明确报错，不静默失败）。
- 日常质量门：`.github/workflows/ci.yml`（ruff 全树 / pyright / pytest / 前端 vitest /
  日志格对齐 / 识别参数比对 / 等价门 / docker 静态检查）。
- **上游同步**是另一条线：`docs/upstream-sync.md`（每周一次，`git merge-tree` 先干跑数冲突）。

## 4. Flow：业务逻辑数据化（迁移前 / 迁移后）

同一个循环，两种写法。左边是上游风格（优先级藏在缩进与 `continue` 里），右边是本 fork
的 flow 数据 + 共享执行核。

**迁移前**（`module/awaken/awaken.py`）：

```python
def awaken_popup_close(self, skip_first_screenshot=True):
    self.interval_clear(AWAKEN_CANCEL)
    while 1:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()

        if self.is_in_awaken():          # 退出条件
            break
        if self.appear_then_click(AWAKEN_CANCEL, offset=(20, 20), interval=3):
            continue                       # ← 优先级顺序 = 代码顺序
        if self.handle_awaken_finish():
            continue
```

**迁移后**（同一文件，循环变成数据，规则顺序显式且带名字）：

```python
def _awaken_popup_close_flow(self, *, cancel=AWAKEN_CANCEL, finish=AWAKEN_FINISH,
                             level_check=SHIP_LEVEL_CHECK) -> dict:
    def in_view(ctx, args=None):     # 退出条件
        return bool(level_check.match_luma(ctx.owner.device.image, similarity=0.7))
    def finish_handled(ctx, args=None): ...   # call_if：检测与动作同一次调用
    def click_cancel(ctx, args=None):   ...
    return {
        "name": "awaken_popup_close", "entry": "wait",
        "states": {"wait": {
            "exit": {"check": {"custom": in_view}, "on_success": {"exit": True}},
            "rules": [
                {"name": "cancel", "action": {"call_if": click_cancel}},   # 规则①
                {"name": "finish", "action": {"call_if": finish_handled}},   # 规则②
            ],
            "on_timeout": {"seconds": 60, "mode": "warn"},
        }},
    }
```

得到什么：

- **优先级顺序变成可读、可 diff、可校验的数据**（`validate_flow` 在加载时就检查
  状态引用与 check/action/control 的合法键）。
- **行为等价由门证明**：`dev_tools/flow_replay.py` 逐帧回放录制场景，比对两套实现的
  设备调用序列（`tests/test_flow_awaken.py` 里保留着迁移前的循环原文作为参照）。
  这道门已经抓到过一次真 bug：把 `appear_then_click(X, interval=3)` 拆成
  `check`+`action` 会同帧消耗两次 interval 计时器 → 点击永不触发。
- **默认值不复制**：check/action 只传 spec 显式写出的键，其余用 `module/base/base.py`
  的签名默认值（引擎曾写死 `threshold=221`，上游改语义后全量静默恒真——见 §1）。
- **门自己必须能被证伪**：`tests/test_flow_replay.py` 验证 harness 对"多一次点击 /
  换顺序 / 差一帧 / 丢 interval / 循环不收敛"都会报差异。

**进度**：已 flow 化 `handler`（登录/自动搜索/strategy/ambush/enemy_searching/
info_handler）、`ui`（navbar/setting/switch/scroll/ui）、`freebies`（4 个）、
`awaken.popup_close`。剩余 `while 1:` 共 272 处，其中约 45 处（meowfficer /
event_hospital / retire）是下一批的合理目标；其余多为一次性顺序代码或设备层，
按设计**不**应 flow 化。明细见 `docs/flow-migration-guide.md`。

## 5. 文档

- `docs/plan-2026-09-todo.md` —— 五项待办的完成计划与执行记录
- `docs/flow-engine-review.md` —— Flow 引擎并入前的评审（含 2 个 P0）
- `docs/flow-migration-guide.md` —— 迁移步骤、坑、剩余队列
- `docs/real-machine-checklist.md` —— 真机实测清单（每步的失败表现与取证位置）
- `docs/upstream-sync.md` —— 上游同步 SOP 与冲突策略
- `deploy/packaging/README.md` —— 打包/安装/发布全流程

## 开发

- 后端环境：`uv sync`（Python ≥ 3.12,含 pywebview）
- 统一入口：`alas run headless|web|desktop`、`alas build frontend|sidecar|launcher|installer`、`alas doctor`（唯一入口;`alas.py`/`gui.py` 旧脚本已移除,python 侧请用 `python -m module.cli`）
- 桌面窗口：`alas run desktop`（pywebview;WebView2 缺失时自动回退浏览器）；`--tray` 让关窗口=隐藏到托盘
- 前端：`cd webapp && pnpm install && pnpm dev`（vite 开发服务器把 API/SSE 代理到 `127.0.0.1:22267` 的后端）
- 测试：`pnpm test`（前端 vitest）；后端 `uv run pytest`

---


**| [English](README_en.md) | 简体中文 | [日本語](README_jp.md) |**

# AzurLaneAutoScript

#### Discord [![](https://img.shields.io/discord/720789890354249748?logo=discord&logoColor=ffffff&color=4e4c97)](https://discord.gg/AQN6GeJ) QQ群  ![](https://img.shields.io/badge/QQ%20Group-1087735381-4e4c97)
Azur Lane bot with GUI (Supports CN, EN, JP, TW, able to support other servers), designed for 24/7 running scenes, can take over almost all Azur Lane gameplay. Azur Lane, as a mobile game, has entered the late stage of its life cycle. During the period from now to the server down, please reduce the time spent on the Azur Lane and leave everything to Alas.

Alas is a free open source software, link: https://github.com/LmeSzinc/AzurLaneAutoScript

Alas，一个带GUI的碧蓝航线脚本（支持国服, 国际服, 日服, 台服, 可以支持其他服务器），为 7x24 运行的场景而设计，能接管近乎全部的碧蓝航线玩法。碧蓝航线，作为一个手游，已经进入了生命周期的晚期。从现在到关服的这段时间里，请减少花费在碧蓝航线上的时间，把一切都交给 Alas。

Alas 是一款免费开源软件，地址：https://github.com/LmeSzinc/AzurLaneAutoScript

EN support, thanks **[@whoamikyo](https://github.com/whoamikyo)** and **[@nEEtdo0d](https://github.com/nEEtdo0d)**.

JP support, thanks **[@ferina8-14](https://github.com/ferina8-14)**, **[@noname94](https://github.com/noname94)** and **[@railzy](https://github.com/railzy)**.

TW support, thanks **[@Zorachristine](https://github.com/Zorachristine)** , some features might not work.

GUI development, thanks **[@18870](https://github.com/18870)** , say HURRAY.

![](https://img.shields.io/github/commit-activity/m/LmeSzinc/AzurLaneAutoScript?color=4e4c97) ![](https://img.shields.io/tokei/lines/github/LmeSzinc/AzurLaneAutoScript?color=4e4c97) ![](https://img.shields.io/github/repo-size/LmeSzinc/AzurLaneAutoScript?color=4e4c97) ![](https://img.shields.io/github/issues-closed/LmeSzinc/AzurLaneAutoScript?color=4e4c97) ![](https://img.shields.io/github/issues-pr-closed/LmeSzinc/AzurLaneAutoScript?color=4e4c97)

这里是一张GUI预览图：
![gui](https://raw.githubusercontent.com/LmeSzinc/AzurLaneAutoScript/master/doc/README.assets/gui.png)



## 功能 Features

- **出击**：主线图，活动图，共斗活动，紧急委托刷钻石。
- **收获**：委托，战术学院，科研，后宅，指挥喵，大舰队，收获，商店购买，开发船坞，每日抽卡，档案密钥。
- **每日**：每日任务，困难图，演习，潜艇图，活动每日AB图，活动每日SP图，共斗活动每日，作战档案。
- **大世界**：余烬信标，每月开荒，大世界每日，隐秘海域，短猫相接，深渊海域，塞壬要塞。

#### 突出特性：

- **心情控制**：计算心情防止红脸或者保持经验加成状态。
- **活动图开荒**：支持在非周回模式下运行，能处理移动距离限制，光之壁，岸防炮，地图解谜，地图迷宫等特殊机制。
- **无缝收菜**：时间管理大师，计算委托科研等的完成时间，完成后立即收获。
- **大世界**：一条龙完成，接大世界每日，买空港口商店，做大世界每日，短猫相接，购买明石商店，每27分钟清理隐秘海域，清理深渊海域和塞壬要塞，~~计划作战模式是什么垃圾，感觉不如Alas......好用~~。
- **大世界月初开荒**：大世界每月重置后，不需要购买作战记录仪（5000油道具）即可开荒。



## 安装 Installation [![](https://img.shields.io/github/downloads/LmeSzinc/AzurLaneAutoScript/total?color=4e4c97)](https://github.com/LmeSzinc/AzurLaneAutoScript/releases)

[中文安装教程](https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/Installation_cn)，包含自动安装教程，使用教程，手动安装教程，远程控制教程。

[设备支持文档](https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/Emulator_cn)，包含模拟器运行、云手机运行以及解锁各种骚方式运行。



## 正确地使用调度器

- **理解 *任务* 和 *调度器* 的概念**

  在 Alas 中每个任务都是独立运行的，被一个统一的调度器调度，任务执行完成后会自动设置这个任务的下一次运行时间。例如，*科研* 任务执行了一个 4 小时的科研，调度器就会把 *科研* 任务推迟 4 小时，以达到无缝收菜的目的。

- **理解 *自动心情控制* 机制**

  Alas 的心情控制以预防为主，不会等到出现红脸弹窗才去解决，这样可以保持心情值在 120 以上，贪到 20% 的经验。例如，当前心情值是 113，放置于后宅二楼（+50/h），未婚（+0/h），Alas 会等到 12 分钟之后，心情值回复到 120 以上再继续出击。而在这个等待的期间，Alas 也会穿插执行其他任务。

- **正确地使用调度器**

  调度器的 **错误使用方法是只开一两个** 任务，手动管理任务或开关 Alas，调度器的 **正确使用方法是启用全部** 你觉得可能有用的任务，让调度器自动调度，把模拟器和 Alas 都最小化到托盘，忘记碧蓝航线这个游戏。



## 修改游戏设置

对照这个表格修改游戏内的设置，~~正常玩过游戏的都这么设置~~。

> 对着改的意思是，这是统一的标准，照着给定的内容执行，不要问为什么，不允许有不一样的。

主界面 => 右下角：设置 => 左侧边栏：选项

| 设置名称                            | 值   |
| ----------------------------------- | ---- |
| 帧数设置                            | 60帧 |
| 大型作战设置 - 减少TB引导           | 开   |
| 大型作战设置 - 自律时自动提交道具   | 开   |
| 大型作战设置 - 安全海域默认开启自律 | 关   |
| 剧情自动播放                        | 开启 |
| 剧情自动播放速度调整                | 特快 |
| 待机模式设置 - 启用待机模式         | 关    |
| 其他设置 - 重复角色获得提示         | 关   |
| 其他设置 - 快速更换二次确认界面     | 关   |
| 其他设置 - 展示结算角色             | 关   |

大世界 => 右上角：雷达 => 指令模块(order)：潜艇支援：
| 设置名称                                                 | 值               |
| -------------------------------------------------------- | ---------------- |
| X 消耗时潜艇出击  |取消勾选|

主界面 => 右下角：建造 => 左侧边栏： 退役 => 左侧齿轮图标：一键退役设置：

| 设置名称                                                 | 值               |
| -------------------------------------------------------- | ---------------- |
| 选择优先级1                                              | R                |
| 选择优先级2                                              | SR               |
| 选择优先级3                                              | N                |
| 「拥有」满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 不保留           |
| 「没有」满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 满星所需或不保留 |

将角色设备的装备外观移除，以免影响图像识别

## 如何上报bug How to Report Bugs

在提问题之前至少花费 5 分钟来思考和准备，才会有人花费他的 5 分钟来帮助你。"XX怎么运行不了"，"XX卡住了"，这样的描述将不会得到回复。

- 在提问题前，请先阅读 [常见问题(FAQ)](https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/FAQ_en_cn)。
- 检查 Alas 的更新和最近的 commit，确认使用的是最新版。
- 上传出错 log，在 `log/error` 目录下，以毫秒时间戳为文件夹名，包含 log.txt 和最近的截图。若不是错误而是非预期的行为，提供在 `log` 目录下当天的 log和至少一张游戏截图。



## 已知问题 Known Issues

- **无法处理网络波动**，重连弹窗，跳小黄鸡。
- **在极低配电脑上运行可能会出现各种问题**，极低配指截图耗时大于1s，一般电脑耗时约0.5s，高配耗时约0.3s。
- **演习可能SL失败**，演习看的是屏幕上方的血槽，血槽可能被立绘遮挡，因此需要一定时间（默认1s）血量低于一定值（默认40%）才会触发SL。一个血皮后排就有30%左右的血槽，所以有可能在 1s 内被打死。
- **极少数情况下 ADB 和 uiautomator2 会抽风**，是模拟器的问题，重启模拟器即可。
- **拖动操作在模拟器卡顿时，会被视为点击**



## Alas 社区准则 Alas Community Guidelines

见 [#1416](https://github.com/LmeSzinc/AzurLaneAutoScript/issues/1416)。



## 文档 Documents

[海图识别 perspective](https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/perspective)

`海图识别` 是一个碧蓝航线脚本的核心，如果只是单纯地使用 `模板匹配 (Template matching)` 来进行索敌，就不可避免地会出现 BOSS被小怪堵住 的情况。 Alas 提供了一个更好的海图识别方法，在 `module.map_detection` 中，你将可以得到完整的海域信息，比如：

```
2020-03-10 22:09:03.830 | INFO |    A  B  C  D  E  F  G  H
2020-03-10 22:09:03.830 | INFO | 1 -- ++ 2E -- -- -- -- --
2020-03-10 22:09:03.830 | INFO | 2 -- ++ ++ MY -- -- 2E --
2020-03-10 22:09:03.830 | INFO | 3 == -- FL -- -- -- 2E MY
2020-03-10 22:09:03.830 | INFO | 4 -- == -- -- -- -- ++ ++
2020-03-10 22:09:03.830 | INFO | 5 -- -- -- 2E -- 2E ++ ++
```

更多文档，请前往 [WIKI](https://github.com/LmeSzinc/AzurLaneAutoScript/wiki)。



## 参与开发 Join Development

Alas 仍在活跃开发中，我们会不定期发布未来的工作在 [Issues](https://github.com/LmeSzinc/AzurLaneAutoScript/issues?q=is%3Aopen+is%3Aissue+label%3A%22help+wanted%22) 上并标记为 `help wanted`，欢迎向 Alas 提交 [Pull Requests](https://github.com/LmeSzinc/AzurLaneAutoScript/pulls)，我们会认真阅读你的每一行代码的。

哦对，别忘了阅读 [开发文档](https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/1.-Start)。



## 相关项目 Relative Repositories

- [AzurStats](https://azur-stats.lyoko.io/)，基于 Alas 实现的碧蓝航线掉落统计平台。
- [AzurLaneUncensored](https://github.com/LmeSzinc/AzurLaneUncensored)，与 Alas 对接的碧蓝航线反和谐。
- [ALAuto](https://github.com/Egoistically/ALAuto)，EN服的碧蓝航线脚本，已不再维护，Alas 模仿了其架构。
- [ALAuto homg_trans_beta](https://github.com/asd111333/ALAuto/tree/homg_trans_beta)，Alas 引入了其中的单应性变换至海图识别模块中。
- [PyWebIO](https://github.com/pywebio/PyWebIO)，Alas 使用的 GUI 库。
- [MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights)，明日方舟小助手，全日常一键长草，现已加入Alas豪华午餐 -> [MAA 插件使用教程](https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/submodule_maa_cn)
- [FGO-py](https://github.com/hgjazhgj/FGO-py)，全自动免配置跨平台开箱即用的Fate/Grand Order助手.启动脚本,上床睡觉,养肝护发,满加成圣诞了解一下?
- [StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot)，星铁速溶茶，崩坏：星穹铁道脚本，基于下一代Alas框架。



## 联系我们 Contact Us

- Discord: [https://discord.gg/AQN6GeJ](https://discord.gg/AQN6GeJ)
- QQ 八群：[938081688](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=3h8Gl323WkIt6yGx8Jx5Ht93puZxeA8T&authKey=xPT6kPm7W9jWO2TNzPdohJ27l1njxorwKmkDrbwwYGGA6Oni1xQSJhHsRIJ8w7GZ&noverify=0&group_code=938081688)
- QQ 一群：[1087735381](https://jq.qq.com/?_wv=1027&k=I4NSqX7g) （有开发意向请加一群，入群需要提供你的Github用户名）
- Bilibili 直播间：https://live.bilibili.com/22216705 ，偶尔直播写Alas，~~为了拯救Alas，Lme决定出道成为偶像~~
