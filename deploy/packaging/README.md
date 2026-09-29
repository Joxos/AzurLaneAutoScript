# 桌面打包与分发

> 状态：P0.5 进行中（2026-09 起 Tauri 壳归档，桌面窗口 = pywebview；安装器 = 自写 NSIS）。
> 构建与发布由 `.github/workflows/release.yml` 在 CI 完成。

## 目标架构

```
Alas_<tag>_x64-setup.exe                 （NSIS 安装包，免管理员）
  └─ %LOCALAPPDATA%\Programs\Alas\      （程序目录，更新时整体替换）
       ├─ Alas\Alas.exe                 ← 启动器（GUI 子系统：无黑窗、数据目录、托盘、单实例）
       └─ alas-backend\                 ← PyInstaller onedir（console 子系统）
            ├─ alas-backend.exe         ← 入口（deploy/packaging/entry.py → module.cli）
            ├─ version.txt               ← release tag
            └─ _internal\                ← 运行时 + 打包数据（assets/bin/config/webapp/dist）

%LOCALAPPDATA%\Alas\                    （用户数据，更新不动）
  ├─ config\   log\   assets\   bin\    launcher.pid
```

- **为什么有两个 exe**：`alas-backend.exe` 必须是 console 构建——windowed 的 PyInstaller
  程序会把未捕获异常弹成看不见的模态框（`alas_backend.spec` 里写明了）；而用户不该看到黑窗。
  原来由 Tauri 用 `CREATE_NO_WINDOW` 拉起，Tauri 下线后无人负责，启动器接手。
- **数据目录分离**：程序目录被更新整体替换，`config/ log/ assets/ bin/` 必须住在
  `%LOCALAPPDATA%\Alas`（启动器设置 `ALAS_DATA_DIR` 并把它作为 CWD；`module/logger.py`
  在 frozen 时 `chdir` 到该目录）。可用 `ALAS_DATA_DIR` 覆盖（便携包 / 测试）。
- **崩溃可见**：控制台被隐藏了，所以启动器把 sidecar 的 stderr 镜像到
  `<数据目录>/log/backend.log`。

## 1. PyInstaller（两个产物）

```powershell
uv run alas build frontend              # pnpm build → webapp/dist
uv run alas build sidecar               # pyinstaller deploy/packaging/alas_backend.spec
uv run alas build launcher              # pyinstaller deploy/packaging/launcher.spec（新增）
uv run python dev_tools/gen_app_icon.py # build/alas.ico（NSIS 只认 .ico，图标是构建产物）
```

- sidecar spec 要点：`console=True`；datas 为 assets/bin/config/module 子目录 + `webapp/dist`；
  `hiddenimports` 增加 uvicorn/websockets/multipart/webview；`pathex` 用绝对路径。
- 启动器 spec 要点：`console=False`；**不 import 任何项目模块**（保持小体积），只 stdlib
  + 托盘依赖；`dist/Alas/Alas.exe` 与 `dist/alas-backend/` 并列。
- 冻结适配：`module/base/paths.py::get_resource_root()`（_MEIPASS）、
  `module/logger.py` 的 frozen chdir 分支、`module/cli/app.py::main()` 的 `freeze_support()`。
- 前端 dev：`cd webapp && pnpm dev`（vite 代理到 `alas run web` 的 22267）。

## 2. 安装器（NSIS）

`deploy/packaging/alas_installer.nsi`，关键决定：

- **免管理员**：装到 `$LOCALAPPDATA\Programs\Alas`（`RequestExecutionLevel user`），
  `/S` 静默升级不会被 UAC 挡住，也不会因为 Program Files 被占用而失败。
- **升级前先退出**：`nsExec` 调 `Alas.exe --quit`（启动器按 pid 文件停掉整棵进程树）。
- **卸载只删程序**：数据目录在交互式卸载时询问是否删除，静默卸载保留。
- 快捷方式：开始菜单 + 桌面；卸载程序登记在 `HKCU\Software\Alas`。

CI（`release.yml`）里 `makensis /DVERSION=<tag> deploy/packaging/alas_installer.nsi`；
nsi 缺失时回退到 portable zip（此时应用内更新不可用，updater 会明确报错而不是静默失败）。

## 3. 发布新版本（操作手册）

**版本规则**：对外版本 = GitHub tag / release 标题 = `vYYYY.MM.DD`；资产名
`Alas_<tag>_x64-setup.exe`；应用内"当前版本"（version.txt）均为 tag 值，三者一致。

```powershell
# ① 提交改动（无需改内部版本号；版本全部由 tag 决定）
git add -A && git commit -m "release v2026.10.01" && git push origin master

# ② 打 tag 并推送 → CI 自动构建并发布
git tag v2026.10.01
git push origin v2026.10.01
```

CI 完成后 GitHub Release 自动创建并上传资产。已安装的应用在 主页→更新器 刷新后即可看到
并安装该版本（下载 setup.exe → `/S /R` 静默安装并重启）。

**注意事项**：

- tag 不可重用：重发同一版本要先 `gh release delete <tag> --cleanup-tag`，再重打 tag。
- 推 tag 前先确认 `ci.yml` 通过；CI 构建的是 tag 指向的提交。
- CI 在发布前会冒烟两个 exe（`alas-backend.exe version` + 启动器存在性）。
- 下载 GitHub 资产需要代理（国内网络环境）；可用 `ALAS_UPDATE_MIRROR` 指定镜像前缀。

## 4. 应用内更新（`module/webui/updater.py`）

- 拉 release 列表 → 下载 `*setup.exe` → 停 bot 任务 → **detached** 启动安装器 `/S /R`。
  分离启动是必须的：安装器要替换正在运行的程序文件，因此必须活过后端进程。
- 旧实现的 Tauri 痕迹（job object、`CREATE_BREAKAWAY_FROM_JOB`）已删除。
- 源码检出不支持安装（会明确报错），开发者用 git 更新。
- `ALAS_UPDATE_REPO` 可换仓库，`ALAS_UPDATE_MIRROR` 可换下载源。

## 5. 已知权衡

- **WebView2 runtime**：pywebview 用系统 WebView2（Win10+ 随 Edge 预装）；极老系统缺失时
  `alas run desktop` 自动回退浏览器窗口。
- **未签名**：没有代码签名证书，SmartScreen 可能提示；这也是不做自动更新校验的原因。
- **托盘**：启动器已预留挂载点（`launcher_tray.run_tray`），未实现前它是纯启动器。
