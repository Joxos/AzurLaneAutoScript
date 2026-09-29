# ALAS 待办完成计划

> 核实时间：2026-09-29 · 仓库：`D:\source\dsh\AzurLaneAutoScript` · HEAD `3213ebd67`（master，领先 `origin/master` **74 commits 未推送**）
> 工作区状态：`module/device/method/pool.py`(M) + `tests/test_pool.py`(??) 未提交（线程池僵尸 worker 修复，见知识库 `pool-zombie-worker.md`）
> 基线门：`pytest` **444 passed**（16s）；`ruff check .` **182 errors**（island/island_handler + dev_tools/island_extractor 为主：F401 49 / UP006 28 / F403 16 / I001 13 / W293 11），CI 用 scoped lint 所以没红

本计划按你列的 5 项待办展开，每项先给「核实到的现状」，再给「目标 / 步骤 / 验收门 / 风险」。执行顺序与待办顺序不同，理由见 §1。

---

## 1. 总体判断与执行顺序

三句话结论：

1. **「代码优化（业务逻辑数据化）」的地图/配置数据化其实已经做完了**（campaign 667 `.py` → 1366 `.yaml` + 1393 `.json` + 134 份 legacy snapshot；`module/island/data.py` 340KB、`research/project_data.py` 203KB、`os/map_data.py` 23KB、`config/config_generated.py` 均已就位）。**真正欠账的是 Flow 引擎：13 个 commits 只躺在 `feature/flow-engine` 分支上，master 里没有 `module/flow/`、registry 也没有 `task_flow`。**
2. **「发布体验/更新体验」目前是断的**：CI 只发 portable zip，而 `module/webui/updater.py` 只认 `*setup*.exe` → 应用内更新现在必然报 `Release is missing the setup exe asset`；NSIS 脚本根本没写（`alas build installer` 只打 warning）；新链路（pywebview + PyInstaller）一次 release 都没跑过，最后一个 release 还是 Tauri 时代的 `v2026.08.21`。
3. **「上游整合」没有常态化机制**：仓库里没有 `upstream` remote（只有 `origin`=Joxos、`qoder`=本地路径），上次合并是 2026-09-09 手工 merge。上游已到 `77f4d01fc`(2026-09-28)，**落后 51 commits**，干跑合并 54 处冲突。

**推荐执行顺序**（与待办书写顺序不同，理由在每阶段「为什么排这里」）：

| 阶段 | 内容 | 对应待办 | 估时 | 为什么排这里 |
|---|---|---|---|---|
| **S0** | 收口：提交 pool 修复、清理远端、修 CI 断点、lint 归零 | 全部的前置 | 0.5 天 | 后面每个阶段都依赖「干净基线 + 绿门」 |
| **S1** | 上游整合常态化 + 首次全量合并 | 上游整合 | 1.5 天 | 上游每周动 handler/ui/assets，和 Flow 引擎改同一批文件；先合 Flow 再合上游等于把 54+2 冲突分两次处理 |
| **S2** | Flow 引擎并入 master（丢弃探针） | 代码优化 | 1 天 | 已完工的 13 commits，越晚合越容易被误当"有用代码"；干跑只有 2 处冲突 |
| **S3** | 发布与更新闭环（NSIS + updater + 启动器 + 首个真机 release） | 发布/更新体验 | 3–5 天 | 独立于重构，可与 S5 并行；做完才有真机验证基线给 S4 托盘用 |
| **S4** | 托盘栏 | 托盘栏 | 2–3 天 | 依赖 S3 的桌面窗口/退出语义稳定；托盘与「更新前退出/更新后重启」强耦合 |
| **S5** | 业务逻辑数据化续做（Flow 化剩余站点） | 代码优化 | 2–4 周，滚动 | 长线，按域分批，每批双跑等价 |
| ~~插队~~ | ~~日志报错框对齐~~ | 日志报错框 | 0.5 天 | ✅ 2026-09-29 完成（见 §8），与 S0 同一批落地 |

**执行记录**

- 2026-09-29：`02d06b7c0` 线程池僵尸 worker 修复入库（原本长期挂在工作区）；`17513b956` 日志格对齐修复 + 等价门；`a2075a543` CI 断点修复（assets 基线入库并重录、`feature/*` 触发、补前端与日志格门）。S0 剩余：远端清理、ruff 182 项归零、基线存档。

---

## 2. S0 收口与基线（0.5 天）

**改动清单**

1. 提交未提交的线程池修复：`module/device/method/pool.py` + `tests/test_pool.py`（知识库已记录根因与反向验证，直接提交即可，不要重做）。
2. 清远端：`git remote remove qoder`（`D:\source\qoder\AzurLaneAutoScript` 已确认完整并入本仓库，KB 记录其 70 个悬空 WIP 提交可弃）。
3. 把我这次核实用的临时 ref `refs/remotes/tmp-upstream/master` 删掉（`git update-ref -d`），S1 里用正式 `upstream` remote 重建。
4. **修 CI 断点**：`ci.yml:51` 的 `verify_assets.py check .qoder/phase456/assets_before.json` —— `.qoder/` 在 `.gitignore` 里，干净 checkout 上该文件不存在 → 每次 CI 都在这一步失败。要么把基线快照挪到被跟踪路径（`dev_tools/baseline/assets_before.json`），要么改成 `dev_tools/verify_assets.py record` 生成并提交。
5. `ci.yml:5` 的 push 触发只有 `master` + `refactor/*`，`feature/*` 不触发 → 把 `feature/*` 加进去（Flow 分支在 feature 下）。
6. **ruff 归零（182 → 0）**：集中在 `module/island_handler/*`（dock_scanner 32 个）、`module/island/*`、`dev_tools/island_extractor.py`。分两步：① `I001`/`W291`/`W293`/`UP006`/`SIM118` 机械修复，`--fix` 逐条过；② `F401`(49)/`F403`(16) **人工审**——知识库有明确教训：ruff 的 F401 曾删掉被 `import *` 消费的 re-export，`--unsafe-fixes` 必须配 `smoke_import_all` 兜底。归零后把 CI 的 scoped lint 放开到全量。
7. 基线存档：把 pytest/ruff/pyright/smoke/verify_* 的输出存 `.qoder/baseline-20260929/`（不入库），供后续每阶段比对。

**验收门**：`pytest` 444+ passed；`ruff check .` 0；`smoke_import_all` 423+ 全过；`git status` 干净。

**风险**：`git remote remove qoder` 不可逆（仅删配置，远端对象还在本地 `.git` 的 remote ref 里，若需要可再加回）。ruff 的 F401 批量修复误伤 re-export —— 靠 smoke + `verify_*` 兜底，不要用 git 清场。

---

## 3. S1 上游整合（1.5 天）

### 3.1 机制常态化（0.5 天）

- `git remote add upstream https://github.com/LmeSzinc/AzurLaneAutoScript`，fetch refspec 收敛为 `+refs/heads/master:refs/remotes/upstream/master`（**明确禁止误 push**，加 `remote.upstream.pushurl` 到一个不存在的地址做保险）。
- 写 `docs/upstream-sync.md` SOP，内容固定为：
  1. `git fetch upstream` → 看 `git log --oneline master..upstream/master` 的 commit 数与 `git diff --shortstat`；
  2. `git merge-tree --write-tree master upstream/master` **干跑数冲突**（本次技巧：不用真合并就能拿到冲突清单和数量）；
  3. 建 `backup/pre-merge-upstream-YYYYMMDD` 分支（沿用 2026-09-09 的既有做法）；
  4. 合并 → 按冲突策略表处理 → 跑全门 → 真机冒烟 → 打 tag 前进 master。
- **冲突策略表**（写进 SOP，避免每次重新想）：

  | 冲突类型 | 策略 | 理由 |
  |---|---|---|
  | `campaign/**` 的 modify/delete（本次 7 处） | 取上游删除；我们要的地图数据已在 `.yaml` + `.legacy_snapshot/` | 上游在清理旧活动图 |
  | `module/*/assets.py`、`ui/assets.py` | 逐块手工：取上游新增按钮/坐标，保留我们的去冗余生成结果 | 资产是硬故障源（见 KB 里 2026-09-08 MAP_PREPARATION 事故：相似度跌破 0.85 直接卡死 60s） |
  | `module/base/*`、`module/ui/{navbar,setting}.py` | 手工：取上游逻辑，保留我们的改动，回归走 verify + 单测 | Flow 引擎也改这些文件 |
  | `deploy/**`（Dockerfile/Dockerfile.cn/git.py） | 基本取本地（我们的 CLI 入口/pywebview 路线与上游 PyWebIO 路线不同源） | 上游的 GUI 路线对我们无意义 |
  | 纯上游性能/修复提交（`Perf:`/`Fix:`） | 全取 | 这是我们 fork 的主要价值来源 |

- 节奏：固定每周一次（建议周一），51 commits/19 天的节奏意味着拖过两周冲突面会明显变大。

### 3.2 首次全量合并（1 天）

- 现状：落后 51 commits，`5061 files changed, +158067 / -552294`（删除量主要来自上游清理旧活动图）。干跑冲突 **54 处**：7 处 campaign modify/delete + 47 处内容冲突（`base/base.py`、`base/utils.py`、`handler/{assets,fast_forward,info_handler,login}.py`、`map/{assets,map_fleet_preparation,map_operation}.py`、`os/*`、`shop*`、`retire/dock.py`、`raid/raid.py`、`ui/{assets,navbar,setting}.py`、`deploy/docker/Dockerfile(.cn)`、`deploy/git.py` 等）。
- 步骤：备份分支 → merge → 按上表逐类处理 → 跑门（S0 起全套）→ `verify_map_data.py --all`、`verify_config_generated.py` 零漂移 → 重点真机回归：登录/出击/活动图/商店/退役（这几处冲突密集）。
- **验收门**：全门绿 + `pytest` 不低于 444 + 真机冒烟通过 + 合并提交信息里逐条列出「取上游 / 保留本地」的决定。

**风险**：上游这批提交里有多处资产与阈值调整（`Upd: [TW] MAP_PREPARATION assets`、`threshold in image_color_count`、`FleetBarDetector` 等），合并后必须用真实截图做模板相似度验证，不能只看 diff 编译过。

---

## 4. S2 Flow 引擎并入 master（1 天）

**为什么先合**：`feature/flow-engine` 有 13 commits（基于 `b7b4259bd`，Tauri 移除那次），master 已走到 `3213ebd67` 且合过上游；干跑合并结果非常干净——`module/alas.py`、`module/webui/api/__init__.py` 自动合并，**只有 2 处内容冲突**（`webapp/src/api/store.svelte.ts`、`webapp/src/components/LogView.svelte`）外加 1 处文件搬家（`webapp-tauri/src/lib/webviewProbe.ts` → `webapp/src/lib/`）。

**步骤**

1. 分支里混着 3 个诊断探针，合并时**直接丢弃**（不要试图保留）：
   - `module/ocr/al_ocr.py` 里的计时探针（KB 记录 OCR/CPU 探针已在主线 revert 过，这里是分支上的残留）；
   - `module/webui/api/routers/probe.py`（新增的 stutter 指标路由）；
   - `webviewProbe.ts` + `store.svelte.ts`/`LogView.svelte`/`main.ts` 里的 `[PROBE][WEB]` 上报。
   判定方法：凡带 `[PROBE]` 前缀的改动一律不取。
2. 取真正的引擎与迁移：`module/flow/{__init__,model,engine,guards,runtime}.py`、`module/tasks/registry.py` 的 `task_flow`、`module/freebies/*`、`module/handler/{login,auto_search,strategy,ambush,enemy_searching,info_handler}.py`、`module/ui/{ui,navbar,setting,scroll,switch}.py`、`tests/test_flow_engine.py` + `tests/conftest.py` 的 runtime 重置 fixture。
3. 验证：pytest（应 ≥ 444 + 新增 flow 用例）、ruff、pyright、`smoke_import_all`、真机冒烟四件事：app 登录、地图自动搜索设置确保、任意页面切换的弹窗组单趟、Freebies 任务流。
4. 合并后删掉 `feature/flow-engine` 与 `backup/pre-reorg`（同指向 `03135da3e`，是 Flow 试验的备份，确认 master 等价后再删；删分支属高危命令，需你确认）。

**验收门**：上面 4 项冒烟 + 全门绿；`git log master -- module/flow` 能看到引擎进入主线。

**风险**：Flow 化的 `login.py`/`ui.py` 与 S1 合并进来的上游改动语义重叠，**顺序必须是 S1 → S2**（先吃上游，再吃 Flow 迁移），反过来要返工。

---

## 5. S3 发布与更新闭环（3–5 天）

这是当前**用户可感知价值最高、也最断**的一块。断点清单（全部已核实）：

| # | 断点 | 证据 |
|---|---|---|
| 1 | NSIS 安装器根本没写 | `module/cli/build.py:57` `installer()` 只 `logger.warning`；`deploy/packaging/alas_installer.nsi` 不存在 |
| 2 | CI 只发 portable zip | `.github/workflows/release.yml:61-74`：nsi 不存在就 `Compress-Archive` |
| 3 | 应用内更新必然失败 | `module/webui/updater.py:154-158` 只找 `*setup*.exe`，zip 资产直接 `RuntimeError` |
| 4 | updater 里全是 Tauri 时代的假设 | `updater.py:5-8, 174-186` 仍在讲 shell job object / `CREATE_BREAKAWAY_FROM_JOB`，注释与真实进程模型已不符 |
| 5 | 桌面 exe 会常驻黑窗 | spec `console=True` 的理由是"shell 用 CREATE_NO_WINDOW 拉起"，Tauri 已删 → 用户双击看到黑窗 |
| 6 | 用户数据目录没人设置 | `ALAS_DATA_DIR` 全仓只出现在 `module/base/paths.py:14` 的注释里；CWD 就是数据目录，exe 放 Program Files 会写失败 |
| 7 | 新链路从未成功发布过一次 | GitHub 上最后一个 release 是 `v2026.08.21` 的 Tauri setup.exe（201MB） |
| 8 | Docker 镜像没有前端 | `deploy/docker/Dockerfile` CMD 已是 `python -m module.cli run web`，但 `webapp/dist` 被 gitignore，compose 靠宿主挂载 → 干净环境只有 API 没 UI；且本机无 docker，从未实构 |

**步骤**

1. **启动器**（解决 5、6，并给托盘留落点）：新增 `deploy/packaging/launcher/`（GUI 子系统的 `Alas.exe`，或更轻的方案：sidecar 保持 `console=True`，另出一个 winforms/pystray 启动器）。职责：设 `ALAS_DATA_DIR`（默认 `%LOCALAPPDATA%\Alas`）→ 以 `CREATE_NO_WINDOW` 拉起 `alas-backend.exe run desktop` → 把子进程 stderr 落 `backend.log` → 转发退出码。托盘（S4）直接长在这个进程里。
2. **NSIS 脚本** `deploy/packaging/alas_installer.nsi`（解决 1、3）：
   - 安装目录、`$LOCALAPPDATA\Alas` 数据目录分离、开始菜单 + 桌面快捷方式、卸载时**只删程序不删数据**（或卸载时询问）；
   - `SilentInstall silent` + `SetShellVarContext current`（免管理员权限，这是 `/S` 静默升级能跑通的前提）；
   - 写 `version.txt` = tag；注册表登记安装版本供 updater 判重。
3. **updater 适配**（解决 3、4）：`/S` 静默安装 → 升级后重启；删掉 Tauri job object 相关注释与 flag 逻辑（若无 job object 就不需要 `CREATE_BREAKAWAY_FROM_JOB`）；加失败回滚（安装前把 `version.txt` 与程序目录做个 manifest，失败提示用户手动恢复）；下载走 `assets.browser_download_url` 保持不变（国内网络需代理，README 已提示，可加 `ALAS_UPDATE_MIRROR` 环境变量）。
4. **CI**（解决 7）：`release.yml` 已有 nsi 分支，脚本落地即自动生效；加一步产物冒烟 `alas-backend.exe version` 与 `alas-backend.exe doctor`，构建失败早暴露；tag 前必须 `ci.yml` 绿（已有约定，写进 SOP）。
5. **源码侧体验**（对应待办里的"源代码 alas 命令"）：`alas` 命令本身已在 master（`[project.scripts]`，`.venv/Scripts/alas.exe` 存在），要做的是把"源码运行"路径写顺并可自检：
   - README 开发段补齐完整链路：`uv sync` → `uv run alas doctor` → `uv run alas build frontend` → `uv run alas run desktop`；
   - `doctor` 从"只报 MISSING"升级为**给可执行修复建议**（缺 pnpm → 提示 corepack；缺 dist → 提示 `alas build frontend`；缺 WebView2 → 提示下载），并对 Windows 装 WebView2 这类一次性动作给出命令。
6. **Docker**（解决 8）：改多阶段构建——`node:24` 阶段 `pnpm build` 出 `webapp/dist`，Python 阶段 COPY 进去；`CMD ["python","-m","module.cli","run","web","--host","0.0.0.0"]`；`docker-compose.yml` 补端口与 `ALAS_DATA_DIR` 卷；至少在一台机器上真构一次并 `curl :22267/api/status` 冒烟（本机无 docker，需你指定一台有 docker 的机器或用 WSL）。
7. **发第一个新链路 release**：`v2026.10.01`（tag 即版本号，不改 pyproject 版本），走完 zip→setup.exe 全流程，并在一台干净 Windows 上验证：安装 → 跑一次任务 → 应用内检查更新 → 升级 → 数据（`config/`、`log/`）未丢。

**验收门**：干净机安装/启动/升级三连通过；`alas doctor` 在缺依赖时给出可执行建议；docker 镜像 `curl /api/status` 200 且 UI 可访问。

**风险**：NSIS 免管理员 + 数据目录分离是这套方案里最容易翻车的地方（UAC、路径含中文、文件被占用）；真机验证必须在**干净 Windows**上做，本机有历史包袱会掩盖问题。

---

## 6. S4 托盘栏（2–3 天）

**现状**：pywebview 6.2.1 没有托盘 API；`pystray` 未安装（`Pillow 12.3` 在，可直接生成图标）；原 Tauri 托盘随 `webapp/src-tauri/` 一起删了（`deploy/packaging/README.md:46` 留了记录）；现在 `alas run desktop` 关窗 = 整个进程退出（`module/cli/run.py:216-222`）。

**步骤**

1. 新增 `module/cli/tray.py`：`pystray.Icon` + 动态菜单（打开主界面 / 各配置启动·停止 / 打开日志目录 / 检查更新 / 退出）。图标用 Pillow 现生成（assets 里已有 gui 图标可裁）。
2. **关闭语义改为"隐藏到托盘"**：拦截 `window.events.closing`（cancelable）→ `window.hide()`；托盘"退出"才是真退出（停 `ProcessManager` 里的 bot → 置 `server.should_exit` → 退出托盘与主进程）。
3. 启动参数：`alas run desktop --tray`（默认关窗即退，保留脚本/远程用户旧行为）与 `--minimized`（启动即进托盘），避免破坏现有 headless/web 用法。
4. 单实例互斥：托盘进程写 pid/命名互斥体，重复启动时只唤起已有窗口（pywebview 侧可用 `window.show()` + `restore()`）。
5. 开机自启（KB 里 D 项遗留）：`alas run desktop --tray --autostart` 写 `HKCU\...\Run`，设置页给开关，写在启动器进程里。
6. 与更新器协同：安装更新前从托盘退出（updater 已有 `_stop_tasks()`，再补"通知托盘退出"）；`/S /R` 重启后自动恢复托盘。
7. spec 与 CI：把 `pystray`/`PIL` 加进 PyInstaller `hiddenimports` 与 `collect_all`，重出产物验证。

**验收门**：托盘常驻、关窗不退出、托盘菜单四项可用、退出后无残留 `alas-backend.exe` 进程、更新后能自动重启回托盘。

**风险**：pywebview 的 `closing` 事件在部分平台不可靠（winforms 后端已知有差异），必须在真机验证；托盘线程与 uvicorn 线程的退出顺序要显式收口，否则会留下孤儿进程。

---

## 7. S5 业务逻辑数据化续做（2–4 周，滚动）

**已完成的部分不必重做**：campaign YAML/JSON 化（1366 yaml / 1393 json / 134 legacy snapshot）、`island/data.py`、`research/project_data.py`、`os/map_data.py`、`config_generated.py`、`event_table.py` 都已落地，`verify_map_data.py` / `verify_config_generated.py` 等价门也在 CI 里跑着。

**欠账的是命令式流程**：master 上仍有 **316 处 `while True`**（os 24 / handler 20 / map 19 / device 19 / meowfficer 18 / retire 15 / event_hospital 14 / shop 11 / research 11 …）。设计文档 `.qoder/doc/reorg-cli-flow-2026.md` 已把 320 个锚点分成 A/B/C/D 四组共 247 站点，并写明排除项（战斗级、设备级、纯算法）。

**步骤**

1. **先补双跑 harness**（P1 计划里写了但没做）：`dev_tools/flow_replay.py` + fake Device（记录 `click(按钮名)/swipe/sleep` 调用序列），同一份录制序列下旧实现与新 Flow 各跑一遍，逐步比对调用流 + 出口值。这是"逐元素对答案"的先例（OCR 迁移用过）。
2. **按域分批**，每批"旧实现保留至双跑等价通过、独立合入"：
   - 第 1 批（低风险高确定性）：`meowfficer` / `event_hospital` / `retire` / `shop_event`（无设备依赖或依赖轻，18+14+15+若干站点）；
   - 第 2 批：`research` / `commission` / `daily` / `dorm`（日常高频，出错最影响体验）；
   - 第 3 批：`os` / `os_ash` / `map`（24+19 站点，大但收益高，需真机）；
   - 设备层（19 处）与战斗级按文档排除或单独立项。
3. **补 `verify_no_data_in_code.py`**：先定义"什么算数据在代码里"的判定标准（文档 §6 遗留项），再实现，挂了 CI。
4. **分层收口（P3）**：`verify_layer_deps.py` 挂 CI，解 `map → os` 环，死代码清理，`code_generator`/`code_generation` 改名合并。

**验收门**：每批双跑调用流逐步相等 + pytest/pyright/smoke 全绿 + 真机冒烟；`verify_no_data_in_code` 与 `verify_layer_deps` 进 CI。

**风险**：声明式/数据化把"代码错误"变成"数据错误"（配置写错不会抛异常，只会让任务空转）。必须靠 verify 层 + 真机冒烟兜底，不能只看单测绿。

---

## 8. 日志报错框不对齐（✅ 已完成 2026-09-29）

用户确认的症状：**大量报错出现时，rich 文字方框右侧对不齐**——不是字体"看起来"的问题，是字符格宽度与后端排版不一致。

**根因（Edge 实测，Consolas + 微软雅黑回退，0.85rem 日志字体）**：

| 字符类 | rich 排版假定 | 浏览器实测 | 每字符误差 |
|---|---|---|---|
| 拉丁 / 数字 / 空格 / 制表符 `│ ─ ╭` | 1 格 | 1.000 格 | 0 |
| CJK 汉字 / 假名 / 全角标点 / `　` | 2 格 | **1.871 格** | −0.13（往左漂） |
| `✔ ✖ ⚠` 等 U+2600–U+2BFF 符号、emoji | 1 格 | **1.1–2.50 格** | +0.1~+1.5（往右漂） |

一行 12 个中文字符就少 1.6 格，样本里最差一行漂 **−17.2px**；报错越多、满屏 traceback，漂移越明显。旧的 `.cjk` 修补只对**含制表符的行**生效，所以纯中文报错行（正是失败运行会产生的那种）一直错着。

顺带查出**第二个缺陷**：rich 的 capture 输出每行以 `ESC[0m\r` 结尾，`render_log` 只 `rstrip("\n")`，尾部的 `\r` 被浏览器 HTML 解析器归一化成换行 → **每条日志后面多一个空行**；而按 rich 表格把控制字符当成 1 格去钉，还会凭空多出 1 格。

**修复（commit `17513b956`）**：

1. **目标宽度以 rich 自己的表为准**（`dev_tools/gen_log_cell_widths.py` 从 `rich._unicode_data` 导出 126 个宽字符区间 + 控制字符区间 → `webapp/src/lib/cell-widths.json`，带 `--check` 零漂移门）。绝不让浏览器按字体自然宽度说了算。
2. **是否需要钉宽由浏览器实测决定**：每个码位量一次并缓存，所以换字体栈/换机器会自动自愈，而不是硬编码"CJK = 2 格"（那只对 CJK 等宽字体成立，Windows 默认没有）。
3. **连续字符合并成一个盒子**（run 而非 per-char）：12 个汉字 = 1 个 span 而不是 12 个——这正是旧代码为了性能把钉宽限制在制表符行的原因，现在性能约束解除了。
4. `ansi.ts` 改为**先切 ANSI 段再在段内钉宽**，盒子不再跨颜色边界；并归一化 CR、去掉尾部换行。
5. `render_log()` 一并 `rstrip("\r\n")`（源头也干净）。
6. `LogView` 自己拥有日志排版（等宽、不换行、关连字、8 空格 tab）；设置页此前用 UI 无衬线字体 + 软换行渲染同一组件，边框偏出几百像素。

**验收门（已落地）**：`dev_tools/verify_log_align.mjs` 用仓库真实 rich 输出走真实前端管线，在 headless Edge 里逐行量，与 rich 的格数对比，>1px 即失败。修复后：70 行最差漂移 **0.03px**，行高不变（CJK 不再让行跳动），反向验证（关掉钉宽）→ 15/70 行漂移、门变红。前端 19 个单测覆盖降级路径与 CR 归一化。

---

## 9. 全阶段通用验证门

每阶段收尾必须全绿（顺序即成本从低到高）：

```powershell
.venv\Scripts\ruff.exe check .                    # S0 后应为 0
.venv\Scripts\python.exe -m pytest -q             # 不低于上一阶段基线（当前 444）
.venv\Scripts\python.exe dev_tools/smoke_import_all.py
.venv\Scripts\python.exe dev_tools/verify_config_generated.py   # 零漂移
.venv\Scripts\python.exe dev_tools/verify_map_data.py --all      # 等价门
# 前端：cd webapp; pnpm test; pnpm lint
```

S0 之后把 `ci.yml` 的 scoped lint 放开到全量并把 `feature/*` 加进触发分支；打 tag 前 `ci.yml` 必绿（CI 构建的是 tag 指向的提交）。

**红线**（沿用既有纪律）：不 `reset --hard` / `checkout --` / `stash` 清场；破坏性命令（删远端、删分支、推 tag、删 release）先跟我确认；`--unsafe-fixes` 逐条人工审并配 smoke 兜底；`.qoder/` 勿提交（内含 tauri-keys 等敏感件）。

---

## 10. 里程碑

| 周 | 交付 |
|---|---|
| 第 1 周前半 | S0 收口 + S1 上游整合（含首次全量合并） |
| 第 1 周后半 | S2 Flow 并入 master + 日志报错框修复 |
| 第 2–3 周 | S3 发布与更新闭环 → 发出第一个 pywebview 版 release |
| 第 4 周 | S4 托盘栏 |
| 第 5 周起 | S5 数据化续做，按域滚动推进；此后固定每周一次上游同步 |
