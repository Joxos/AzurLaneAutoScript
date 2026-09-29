# 需求矩阵（Joxos fork）

> 五项待办的逐条核对。**每条都写明"实现是什么 / 谁在自动证明 / 真机是否已验"**——
> 没有自动化证据的行不算满足，只算"写了代码"。
> 复跑：`python dev_tools/verify_requirements.py`（核对实现与证据文件是否还在）；
> 自动化门本身在 CI 里跑（见 §3）。

图例：✅ 自动门已通过 · 🟡 需要真机 · ⬜ 未做

## 1. 日志报错框右侧对不齐

| 需求 | 实现 | 自动化证据 | 真机 |
|---|---|---|---|
| 报错框按 rich 的格宽对齐 | `webapp/src/lib/cells.ts`（目标宽度取自 rich 表；是否钉宽由浏览器实测决定并缓存；连续字符合并成一个盒子） | `dev_tools/verify_log_align.mjs`：真实 rich 输出走真实前端管线，headless Edge 逐行量，>1px 即失败。**修复后 70 行最差 0.03px（修复前 −17.19px）** | 🟡 §4 第 3.5 项 |
| 宽度表与后端同源 | `webapp/src/lib/cell-widths.json` ← `dev_tools/gen_log_cell_widths.py`（从 `rich._unicode_data` 导出） | `gen_log_cell_widths.py --check`（零漂移门） | ✅ |
| 每条日志后多一个空行 | `module/webui/api/helpers.py::render_log` 改 `rstrip("\r\n")`；前端 `ansiToHtml` 归一化 CR | 同上（样本含 CRLF） | 🟡 |
| 两个日志面板用同一排版 | `webapp/src/styles/base.css::.alas-log` + `LogView.svelte` 拥有排版 | 前端 vitest 19 例 | 🟡 |

## 2. 发布体验 / 更新体验

| 需求 | 实现 | 自动化证据 | 真机 |
|---|---|---|---|
| 源代码统一入口 | `module/cli/`（`alas run headless/web/desktop`、`alas build frontend/sidecar/launcher/installer`、`alas doctor`、`alas version`）；`alas.py`/`gui.py` 已删 | `tests/test_cli.py` 13 例 | ✅ |
| 桌面窗口无黑窗 | `deploy/packaging/launcher.py`（GUI 子系统 + CREATE_NO_WINDOW 拉起 sidecar） | `tests/test_launcher.py` 14 例 | 🟡 |
| 数据目录与程序目录分离 | `%LOCALAPPDATA%\Alas` vs `%LOCALAPPDATA%\Programs\Alas`；`ALAS_DATA_DIR` + frozen `chdir` | 同上（`test_seed_*`、`test_data_dir_*`） | 🟡 |
| 崩溃可见 | 启动器镜像 sidecar stderr → `<data>/log/backend.log`；自身动作 → `launcher.log` | `tests/test_launcher.py`（pid 文件/日志落盘） | 🟡 |
| 安装包 | `deploy/packaging/alas_installer.nsi`（免管理员、静默、升级前退旧版、卸载不动数据） | `dev_tools/verify_docker_packaging.py` 同类静态检查思路；NSIS 本身需真机 | 🟡 |
| CI 出 setup.exe | `.github/workflows/release.yml`：frontend → icon → sidecar → launcher → **冒烟两个 exe** → makensis → 上传 | ci.yml 全绿才允许打 tag（流程约定） | 🟡 |
| 应用内更新可用 | `module/webui/updater.py`：下载 setup.exe → 停任务 → **分离启动** `/S /R`；`ALAS_UPDATE_MIRROR` 支持 | `dev_tools/verify_docker_packaging.py` 之外无（更新链需真机） | 🟡 |
| Docker 镜像含前端 | `deploy/docker/Dockerfile(.cn)` 两阶段；`.dockerignore` 移到仓库根；compose context 修正为仓库根 | `dev_tools/verify_docker_packaging.py`（COPY 源存在且未被 ignore） | 🟡 |

## 3. 托盘栏

| 需求 | 实现 | 自动化证据 | 真机 |
|---|---|---|---|
| 托盘图标与菜单 | `deploy/packaging/launcher_tray.py`（pystray；开关窗口/按配置启停/日志目录/数据目录/退出；失败经 tooltip 报告） | `tests/test_launcher_tray.py` 24 例 | 🟡 |
| 关窗口 = 隐藏，任务继续 | `module/cli/run.py::_install_tray_close_behavior`（pywebview 取消协议：返回 `False`；窗口经 `window` 参数注入） | `tests/test_window_tray.py` 13 例 | 🟡 |
| 窗口找回 / 单实例唤起 | `module/webui/api/routers/window.py`（show/hide/state）；启动器第二次启动调 `/api/window/show` | 同上（路由经 `app.openapi()` 断言真的挂上了） | 🟡 |
| 退出即真退出 | 托盘 Quit 终止 sidecar → 其 lifespan 收掉 bot 进程 | `test_quit_stops_the_sidecar*` | 🟡 |
| 开机自启 | ⬜ 未做（`pystray` 可做，但本次未实现） | — | — |

## 4. 上游整合

| 需求 | 实现 | 自动化证据 | 真机 |
|---|---|---|---|
| 常态化 SOP + 远端 | `upstream` 远端（push 指向 `DISABLED://`）+ `docs/upstream-sync.md`（先 `merge-tree` 干跑、按目录的冲突策略、门顺序、真机冒烟清单） | `git remote -v` 可查 | — |
| 首次全量合并 | 51 个提交 / 66 处冲突，按策略解决（campaign 取删除、deploy 取本地、handler 登录层保我方删掉的 u2 旧路径并移植上游阈值） | merge 提交 + 全部门 | — |
| 识别参数不漂移 | `dev_tools/verify_thresholds.py`：AST 逐站点比对上游，**549 站点 0 漂移**；<400 可比站点判失败（防假绿） | CI 门 | — |
| 资产格式不退化 | `dev_tools/dedup_assets.py`（AST 折叠四服同值）+ 语义门 | CI 门（1343 buttons / 441 templates 语义一致） | — |
| 引擎默认值不复制 | flow 的 check/action 只传 spec 显式键，其余用 owner 签名默认值 | `tests/test_flow_engine.py` 40 例 | — |

## 5. 代码优化（业务逻辑数据化）

| 需求 | 实现 | 自动化证据 | 真机 |
|---|---|---|---|
| 地图/配置数据化 | `campaign/` YAML+JSON（2759 个文件）+ 134 份 legacy snapshot；`module/{island,research,os,config}` 的数据模块 | `verify_map_data --all`（1366/1366）、`verify_config_generated`（零漂移） | 🟡 需实机跑一次活动 |
| 任务清单声明式 | `module/tasks/registry.py` | `verify_task_registry` / `verify_task_families` | 🟡 |
| flow 执行核 | `module/flow/`（model/engine/guards/runtime），默认值透传、载荷校验、`_RunState` 拆开闭包、`run`/`run_group` 共用求值器 | `tests/test_flow_engine.py` 40 例 | 🟡 |
| 迁移等价可证 | `dev_tools/flow_replay.py` + `tests/test_flow_replay.py`（harness 自身可被证伪）+ `tests/test_flow_awaken.py`（保留迁移前循环原文作参照） | 14 + 6 例 | — |
| 剩余 272 处 while | ⬜ 本轮只迁了 awaken 一个（+ 上游已有的 11 个文件）。队列与建议批次见 `docs/flow-migration-guide.md` | — | — |

## 6. 质量门现状（每次提交都跑）

| 门 | 范围 | 现状 |
|---|---|---|
| `ruff check .` | 全树 | 0 |
| `pyright` | logger/scheduler/tasks/webui/cli/config.utils/flow/packaging/tests | 0 errors |
| `pytest` | 全树 | 1459 passed |
| `pnpm test` | webapp | 19 passed |
| `smoke_import_all` | module 全树导入 | 445/445 |
| `verify_config_generated` | 生成物零漂移 | OK |
| `verify_map_data --all` | 1366 张图逐格等价 | OK |
| `verify_stage_meta` / `verify_task_families` | stage meta / 任务族 | 27 / 8 族 |
| `verify_assets check` | 资产语义 | 1343 buttons / 441 templates |
| `dedup_assets --check` | 资产格式 | OK |
| `gen_log_cell_widths --check` | 与 rich 17.0.0 同源 | OK |
| `verify_log_align` | headless Edge 逐行量 | 最差 0.03px |
| `verify_thresholds --check` | 549 站点 vs 上游 | 0 漂移 |
| `verify_docker_packaging` | COPY 源/ignore/compose | OK |
| `verify_requirements` | 本矩阵的实现与证据 | 16/16 |
