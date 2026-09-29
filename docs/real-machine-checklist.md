# 真机实测清单（安装版）

> 覆盖 2026-09-29 之前所有无法在本机验证的部分：NSIS 装包、pywebview 窗口、
> 托盘、升级链路。**每一项都写了"失败长什么样"和"去哪看日志"**——
> 装完发现问题时按这个走，比重装快。

## 0. 前置

- 一台**干净的 Windows 10/11**（没装过 Alas、没有 WebView2 缺失的怪环境）。
- 模拟器（MuMu 12 / 雷电 / 夜神 任一），已开启 ADB 调试。
- 一个可用的配置文件（国服即可）。

## 1. 安装与首次启动

| # | 动作 | 期望 | 失败长什么样 |
|---|---|---|---|
| 1.1 | 跑 `Alas_<tag>_x64-setup.exe` | 无 UAC 弹窗；装到 `%LOCALAPPDATA%\Programs\Alas` | UAC 弹窗 = NSIS `RequestExecutionLevel` 没生效 |
| 1.2 | 安装完点"启动" | 出现 Alas 窗口，**没有黑窗** | 黑窗 = 启动器没带 `--tray`/CREATE_NO_WINDOW 路径 |
| 1.3 | 托盘出现图标 | 右键菜单：Open window / Hide window / Configs / Log folder / Data folder / Quit | 没图标 = `dist/Alas` 里缺 pystray（看 `%LOCALAPPDATA%\Alas\log\launcher.log`） |
| 1.4 | 首次运行后检查 `%LOCALAPPDATA%\Alas\` | 有 `config/ log/ assets/ bin/`，`config/deploy.yaml` 已生成 | 数据落在程序目录 = `ALAS_DATA_DIR` 没生效（`module/logger.py` frozen 分支） |
| 1.5 | WebUI 首页 | 能看到配置列表与调度状态 | 空白页 = `webapp/dist` 没进 sidecar |

## 2. 窗口与托盘（这批改动的核心）

| # | 动作 | 期望 | 失败长什么样 |
|---|---|---|---|
| 2.1 | 点窗口 X | 窗口消失，**任务继续跑**，托盘图标还在 | 整个应用退出 = 关窗没走 `call_if/return False` 取消协议 |
| 2.2 | 托盘 → Open window | 窗口回来 | 只开浏览器 = `/api/window/show` 报 `exists: false`（`State.window` 没发布） |
| 2.3 | 再点一次桌面图标 | 已有窗口被唤起（不启动第二个进程） | 弹"already running"或起第二个后端 = pid 文件/单实例判断失效 |
| 2.4 | 托盘 → Hide window | 窗口隐藏，任务不受影响 | 任务停了 = hide 误触发了关窗逻辑 |
| 2.5 | 托盘 → Quit | 应用退出，**没有残留 alas-backend.exe** | 残留进程 = 退出路径没杀 sidecar（看 `State.clearup`） |
| 2.6 | Quit 后再启动 | 正常启动 | 提示"已在运行" = pid 文件没清（launcher.log 末尾应有 `launcher stopped`） |

## 3. 任务真跑（S2 flow 化的部分 + 刚迁移的 awaken）

| # | 动作 | 期望 | 看哪里 |
|---|---|---|---|
| 3.1 | 启动一个配置 | 正常登录进主页 | `log/<配置名>/*.txt` |
| 3.2 | 观察自动搜索开关 | 点一次生效、不会被连点 | 同上，`[flow]` 行 |
| 3.3 | 任意切页触发弹窗 | 弹窗被关掉 | 同上 |
| 3.4 | 跑 **觉醒（Awaken）** | 正常觉醒；退出/取消弹窗正常 | 同上（本批迁移的循环） |
| 3.5 | **大量报错**场景（例如断网/模拟器卡住） | 日志里的报错框**右侧对齐** | 直接肉眼比：每行 `│` 应该在同一列 |
| 3.6 | 商店/活动/退役各点一次 | 无异常 | 日志里 traceback |

> 3.5 是这次最核心的用户可见修复。如果框还是歪的，把那一屏截图存下来，
> 里面有中文报错就能直接复现（`dev_tools/gen_log_sample.py` 同款样本）。

## 4. 更新

| # | 动作 | 期望 | 失败长什么样 |
|---|---|---|---|
| 4.1 | 主页 → 更新器 → 刷新 | 列出 release，版本号 = tag | 空列表 = GitHub API/网络（可用 `ALAS_UPDATE_MIRROR`） |
| 4.2 | 点安装 | 下载进度 → 应用退出 → 安装器静默跑 → **应用自动重启** | 应用退出但不重启 = NSIS 缺 `/R` 或 `MUI_FINISHPAGE_RUN` 未在静默路径生效 |
| 4.3 | 重启后 | 版本号变了；`config/` 里的配置还在 | 配置丢失 = 数据目录被写进程序目录 |
| 4.4 | 升级时正在跑任务 | 任务先停、文件不被占用 | 安装失败 = 退出顺序问题 |

## 5. Docker（可选）

```powershell
docker build -f deploy/docker/Dockerfile -t alas:local .
docker run --rm -p 22267:22267 -v ${PWD}:/app/AzurLaneAutoScript alas:local
curl http://127.0.0.1:22267/api/status   # 期望 JSON
# 浏览器打开 http://127.0.0.1:22267/     # 期望能看到 UI（这次把前端打进镜像了）
```

## 6. 出问题时的取证顺序

1. `%LOCALAPPDATA%\Alas\log\launcher.log` —— 启动器做了什么（启动/退出/托盘/忽略的参数）
2. `%LOCALAPPDATA%\Alas\log\backend.log` —— **崩溃 traceback 就在这里**（控制台被隐藏了）
3. `%LOCALAPPDATA%\Alas\log\<配置名>\*.txt` —— 业务日志
4. 复现日志对齐问题：截一屏含中文报错的日志，`dev_tools/verify_log_align.mjs` 能同源复现

## 7. 本机已验证 / 未验证

已验证（自动化门，每次提交都跑）：ruff 0 · pyright 0 · pytest 1459 ·
导入冒烟 445/445 · 配置零漂移 · 地图数据 1366/1366 · 资产语义 1343/441 ·
资产去冗余格式 · 日志格对齐（真实浏览器逐行量）· 识别参数 vs 上游 550 站点 ·
docker 打包静态检查。

**未验证（只有真机能验）**：NSIS 装/卸、托盘图标与菜单、pywebview 窗口关闭隐藏、
升级重启、数据目录在真实安装下的表现、docker 实际构建。
