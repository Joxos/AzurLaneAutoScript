# 桌面打包与分发

> 状态：P0.5 进行中（2026-09-02 起 Tauri 壳归档，桌面窗口改用 pywebview）。
> 构建与发布由 `.github/workflows/release.yml` 在 CI 完成。

## 目标架构

```
[portable zip / NSIS 安装包]（P0.5 前为 zip；NSIS 后为 setup.exe）
  └─ alas-backend/            ← PyInstaller onedir（一体化,无独立壳）
       ├─ alas-backend.exe    ← 入口（console; deploy/packaging/entry.py → module.cli）
       ├─ version.txt         ← release tag
       └─ _internal/          ← 运行时 + 打包 datas（含 webapp-tauri/dist 与 pywebview）
```

- **一体化解耦壳**：桌面窗口 = `alas-backend.exe run desktop`（pywebview + 系统
  WebView2，缺失时回退浏览器）；无 GUI 场景 = `alas run headless`；远程/浏览器
  场景 = `alas run web`。全部由一个 Python 发行物承载。
- 用户数据目录：`config/ log/ assets/ bin/` 与发行物并列；首次运行由 backend 播种，
  更新整包替换，用户数据天然保留。
- 更新：后端 `module/webui/updater.py` 拉取 GitHub release 列表，安装 = 整包替换
  （NSIS 就绪前为手动替换 zip，`/S /R` 静默安装为 P0.5 目标）。无 tauri updater、
  无签名依赖（SmartScreen 可能提示）。

## 1. PyInstaller onedir（唯一产物）

```powershell
# 推荐走统一入口
uv run alas build frontend    # pnpm build → webapp-tauri/dist
uv run alas build sidecar     # pyinstaller deploy/packaging/alas_backend.spec
# 产物：dist/alas-backend/（CI 里再写 version.txt = tag）
```

- spec 要点：`console=True`（未捕获异常走 stderr 而非隐藏的模态框）；datas 为
  assets/bin/config/module 子目录 + `webapp-tauri/dist`（SPA 由后端托管）；
  `hiddenimports` 增加 uvicorn/websockets/multipart/webview；`pathex` 用绝对路径
  （含 `.venv/Lib/site-packages`，规避 packaging 20.9 遮蔽）。
- 冻结适配最小集：`module/base/paths.py::get_resource_root()`（_MEIPASS）、
  `module/logger.py` 的 `not frozen` chdir 守卫、`module/cli/app.py::main()` 的
  `freeze_support()`。
- 前端 dev：`cd webapp-tauri && pnpm dev`（vite 代理到 `alas run web` 的 22267）。

## 2. 旧 Tauri 壳（已移除）

2026-09-02 起 `webapp-tauri/src-tauri/` 从仓库删除（git 历史可随时恢复）。删除前它
提供：frameless 窗口、托盘、NSIS 外部捆绑、Job Object 整树收割。对应的替代实现：
- 窗口 → pywebview（`module/cli/run.py::run_desktop`）；
- 杀进程树 → 关窗触发 uvicorn 优雅停机，lifespan `_shutdown` 停止 bot 进程；
- NSIS 捆绑 → P0.5 目标（`deploy/packaging/alas_installer.nsi` + makensis）。

## 3. 发布新版本（操作手册）

**版本规则**：对外版本 = GitHub tag / release 标题 = `vYYYY.MM.DD`（如
`v2026.08.21`）；资产名 `Alas_<tag>_x64-portable.zip`（NSIS 就绪后为
`..._x64-setup.exe`）、应用内"当前版本"（version.txt）均为 tag 值，三者一致。

**发布一个版本只需三步**：

```powershell
# ① 提交改动（无需改内部版本号；版本全部由 tag 决定）
git add -A
git commit -m "release v2026.08.22"
git push fork master

# ② 打 tag 并推送 → CI 自动构建并发布（约 10 分钟）
git tag v2026.08.22
git push fork v2026.08.22
```

CI 完成后 GitHub Release `v2026.08.22` 自动创建并上传资产。已安装的应用在
主页→更新器 刷新后即可看到并安装该版本（zip 阶段需手动解压替换）。

**注意事项**：
- tag 不可重用：同一版本要重发时，先删掉再重打——
  `gh release delete v2026.08.22 --cleanup-tag && git tag -d v2026.08.22 && git tag v2026.08.22 && git push fork v2026.08.22`
- 推 tag 前先确认 ci.yml 通过（前端 lint/测试、pyright、导入冒烟）；
  推送 tag 前请确保所有改动已 commit 在 master 上——CI 构建的是 tag 指向的提交。
- 手动重跑（不发新版本）：Actions → Release → Run workflow（此时资产名会带
  分支名，仅用于调试，不建议）。
- 下载 GitHub 资产需代理（国内网络环境）。

## 4. 发布流水线内部（CI）

`.github/workflows/release.yml`：推 tag → Windows runner 上 `uv sync`（含
pywebview 主依赖）→ 前端 `pnpm build` → PyInstaller sidecar（`version.txt =
$GITHUB_REF_NAME`）→ 打包（`deploy/packaging/alas_installer.nsi` 存在则 makensis
出 setup.exe，否则出 portable zip）→ softprops/action-gh-release 上传资产。

## 5. 已知权衡

- **portable zip 阶段**：无安装器、无开始菜单快捷方式、无自动更新替换（用户手动
  解压覆盖）；NSIS 落地（P0.5）后自动升级链路（`/S /R` 静默安装重启）才闭环。
- **WebView2 runtime**：pywebview 使用系统 WebView2（Win10+ 随 Edge 预装）；
  极老系统缺失时 `alas run desktop` 自动回退浏览器窗口（见 run.py）。
- 更新下载走 GitHub 资产地址（国内网络环境可能需要 VPN）。
