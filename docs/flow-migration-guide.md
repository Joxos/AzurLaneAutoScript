# Flow 迁移指南（S5）

> Flow 引擎怎么用、怎么证明迁移没改行为、还剩多少。2026-09-29 建立，
> 第一个批次（awaken）已用它证明等价。

## 1. 双跑门（`dev_tools/flow_replay.py`）

迁移一个 `while 1:` 循环，唯一能接受的说法是**逐帧设备调用轨迹完全一致**。
harness 做的事：

- 场景 = 一串 frame，每个 frame 说明这一帧"世界长什么样"（哪些按钮可见、
  哪些颜色/模板/页面命中、哪些 custom 能力为真）；
- `Replay` 扮演 owner + device，**记录每一次 click/swipe/sleep/interval**，
  并接管识别（`appear` / `match_template_color` / `match_luma` /
  `image_color_count` / `ui_page_appear`）；
- `compare(old, new, scenario)` 跑两套实现，逐帧比对调用序列 + 返回值。

**harness 自己也必须能被证伪**（`tests/test_flow_replay.py`）：多一次点击、
换了顺序、差一帧、少一个 `interval` 守卫、循环不收敛——它都得报出来。

### 写法上最容易踩的坑

1. **`appear_then_click(X, interval=n)` 不能拆成 `check` + `action`。**
   `check` 先消耗一次 interval 计时器，`action` 里的第二次 `appear` 立刻被
   挡住 → 点击永远不发生。正确形状是 `{"action": {"call_if": fn}}`：
   检测与动作是同一次调用（引擎为此专门留了这个语义）。
   *awaken 迁移就是这样被门抓出来的。*
2. **两侧必须用同一个 owner**。拿 Replay 去比真实 `ModuleBase`，差异是假的。
3. **`Frame` 用关键字集合**：`Frame(luma={...})`。`Frame({"luma": ...})` 会
   静默忽略字典（场景字典走 `Frame.from_dict`）。
4. 循环不收敛时 harness 抛异常而不是挂死（`max_frames` + 截图驱动推进），
   跑测试时务必**带超时并按 PID 收进程**。

## 2. 迁移一个循环的步骤

1. 在 `module/<domain>/<file>.py` 里写 `make_<name>_flow(...)` 工厂，**符号
   做成参数**（默认真实资产），这样测试能用记录驱动的替身。
2. 原来 `while 1:` 的每个分支对应一条 rule，逐条标注原行号。
   - `if handler(): continue` → `{"action": {"call_if": fn}}`
   - `if appear(X, interval=3): click(X)` → `{"action": {"call_if": fn}}`
   - 需要区分"命中即停"与"命中继续往下" → `stop`
   - `while` 的退出条件 → state 的 `exit.check` + `on_success`
3. 方法体只剩 `run_flow(self._x_flow(), owner=self, skip_first=...)`。
4. **测试**：把迁移前的循环原样抄进 `tests/test_flow_awaken.py` 之类的文件，
   写场景，`_differences(legacy, flow) == []`。
5. 跑全门：`ruff` / `pyright` / `pytest` / `smoke_import_all`。

## 3. 引擎能力与坑

- **`validate_flow` 会校验载荷**：check/action/control/state/rule 的未知键在
  `run()` 开始时就报错，不会等到实机循环中途。
- **默认值归 owner**：check/action 只传 spec 显式写出的键，其余用
  `module/base/base.py` 里的签名默认值。（引擎曾写死 `threshold=221`，上游
  改了 `image_color_count` 语义后全量静默恒真——`dev_tools/verify_thresholds.py`
  现在会全量扫这类漂移。）
- 没有 `luma` 检查就是能力缺口：需要整图亮度匹配时**先加引擎能力**，不要在
  flow 里用 `custom` 绕。
- 引擎有 `run()` / `run_group()`（单趟，ui_additional 语义）/ `run_task()`
  三个入口，共用同一个 `_eval_rules`。

## 4. 剩余队列（2026-09-29 实测 272 处 while）

已 flow 化：handler（login / auto_search / strategy / ambush / enemy_searching /
info_handler）、ui（navbar / setting / switch / scroll / ui）、freebies（4 个）、
**awaken.popup_close**。

按域（数字 = 剩余 `while 1:` 数，设备层与战斗引擎按设计排除）：

| 域 | 数 | 备注 |
|---|---|---|
| os / os_ash / os_shop / os_combat | 42 | 大世界，二期；依赖地图检测，建议最后做 |
| device | 19 | 设备抽象层，按设计**不** flow 化 |
| meowfficer | 18 | 第 1 批候选（无设备耦合，纯点击循环） |
| map | 17 | 依赖地图识别 |
| event_hospital | 14 | 第 1 批候选 |
| retire | 13 | 第 1 批候选 |
| shop / shop_event | 13 | |
| research / dorm / storage / guild / minigame | 47 | 第 2 批 |
| 其余（campaign / base / combat / exercise / gacha / raid / scheduler / …） | 136 | 逐个评估，多数是"一次性顺序"而非可循环规则，**不必** flow 化 |

**建议的下一批**：meowfficer / event_hospital / retire（合计 45 处，纯
点击 + 弹窗循环，harness 直接能覆盖）。做完这些，剩下的基本都依赖图像
识别或属于一次性代码，收益/风险比明显下降。
