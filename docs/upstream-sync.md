# 上游整合 SOP

> 本仓库是 [LmeSzinc/AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 的 fork（经 Joxos）。
> 上游平均每周有 10–20 个提交，其中大部分是**资产更新与实机修复**——这是本 fork 存在的主要价值来源，不能拖。
> 本文件是唯一的整合流程；不要凭记忆手工 merge。

## 0. 远端约定

| 远端 | 指向 | 用途 |
|---|---|---|
| `origin` | `Joxos/AzurLaneAutoScript` | 我们的 fork，唯一可推送目标 |
| `upstream` | `LmeSzinc/AzurLaneAutoScript` | 只 fetch；push URL 指向 `DISABLED://`，物理上推不上去 |

```powershell
git remote -v          # 确认 upstream 的 push 是 DISABLED
```

## 1. 每次整合的标准流程

```powershell
# ① 取上游（partial clone，快）
git fetch upstream

# ② 先看规模与冲突面，不动工作区
git log --oneline master..upstream/master | Measure-Object -Line     # 落后多少提交
git diff --shortstat master...upstream/master                        # 改动规模
git merge-tree --write-tree --name-only master upstream/master      # 干跑：冲突清单 + 数量
```

`merge-tree` 是关键一步：**不产生任何合并状态**，就能拿到真实冲突清单。上游每周 10–20 个提交、冲突面随时间单调增长，先看清楚再动手。

```powershell
# ③ 备份分支（沿用既有命名，冲突处理失败时可整体回退这一个分支）
git branch backup/pre-merge-upstream-YYYYMMDD

# ④ 合并
git merge upstream/master
```

### 冲突策略

| 冲突类型 | 策略 | 理由 |
|---|---|---|
| `campaign/**` 的 modify/delete | **取上游删除**（`git rm`） | 我们的地图数据已转 YAML + `.legacy_snapshot/`；上游在清理过期活动图，被"改"的是它要删的旧 `.py` |
| `module/**/assets.py`、`module/ui/assets.py` | **逐块手工**：取上游新增的按钮/坐标，保留我们的去冗余结果 | 资产是硬故障源：客户端改 UI 后模板相似度跌破 0.85 就会静默卡死 60s（2026-09-08 MAP_PREPARATION 事故） |
| `module/base/*`、`module/ui/{navbar,setting}.py`、`module/handler/*` | **手工**：取上游逻辑，保留我们的改动，跑 verify + 单测 | 这些文件 Flow 引擎也改（S2），先吃上游再吃 Flow，冲突面才可控 |
| `deploy/**`（Dockerfile、Dockerfile.cn、git.py） | **基本取本地**，只在确有必要时取上游 | 上游仍是 PyWebIO GUI 路线，我们的 `alas` CLI + pywebview 与之不同源 |
| `webapp/**`、`module/webui/**`、`module/cli/**` | **完全取本地** | 这些目录上游没有等价物 |
| 纯上游 `Perf:` / `Fix:` / `Upd:` 提交 | **全取** | fork 的核心价值 |

### 合并后必跑的门（顺序即成本从低到高）

```powershell
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe dev_tools\smoke_import_all.py
.venv\Scripts\pyright.exe module/logger.py module/scheduler module/tasks tests
.venv\Scripts\python.exe dev_tools\verify_config_generated.py     # 零漂移
.venv\Scripts\python.exe dev_tools\verify_map_data.py --all        # 等价门（约 45s）
.venv\Scripts\python.exe dev_tools\verify_assets.py check dev_tools/baseline/assets_snapshot.json
```

资产相关的上游提交（`Upd: ... assets`、`threshold in ...`、`FleetBarDetector`）**不能只看 diff 编译过**：用 `log/error/<id>/*.png` 里的实机截图做模板相似度验证（相似度 ≥ 0.85 才算命中），必要时重建模板。

### 真机冒烟清单（合并涉及玩法代码时）

登录 → 地图出击（含自动搜索）→ 活动图入口 → 商店 → 退役/强化 → 岛屿（若上游动了 island）→ 大世界（若动了 os）。

### 提交与推送

```powershell
git commit          # 合并信息里逐条写明「取上游 / 保留本地」的决定与理由
git push origin master
```

## 2. 节奏

- **每周一次**，建议周一；落后超过 3 周或冲突数 > 40 就该先做一次纯策略性合并（先合数据、再合代码）而不是硬啃。
- 上游发布重大重构（例如曾经的大规模目录清理）时，单独排一轮，不与日常修复混在一起。

## 3. 已知的上游行为

- 上游 `master` 每天都有提交，其中相当一部分是客户端更新后的资产/阈值调整——**这类提交拖不得**，它们是实机故障的修复。
- 上游与我们的 `campaign` 表示不同：上游仍是 `.py`，本 fork 是 YAML/JSON + legacy snapshot。所以 `campaign/**` 冲突一律取上游删除。
- 上游没有 `webapp/`、`module/cli/`、`module/webui/` 的等价物（它的 GUI 仍是 PyWebIO），这些路径的冲突不应出现；出现了说明 fetch 范围错了，检查 `remote.upstream.fetch`。
