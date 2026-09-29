# Flow 引擎评审（并入 master 前）

> 评审对象：`feature/flow-engine`（13 commits，基于 `b7b4259bd`）的 `module/flow/{model,engine,guards,runtime}.py` + 迁移样例。
> 评审时间：2026-09-29，在**完成上游合并之后**的 master 上做的——这一点很关键，下面第 1 条就是合并引入的。
> 结论：设计方向对（Flow 数据 + 共享执行核 + 零字符串引用），但**不能原样并入**：有 1 个 P0 正确性缺陷、1 个 P0 可测性缺陷、3 个 P1 结构问题。

## 先说结论：这套东西值得留

它解决的问题是真的：50+ 模块重复实现 `while 1: if handler(): continue` 的优先级规则集，规则的**顺序**本身就是语义。转成数据后，顺序可见、可 diff、可校验（`validate_flow`），这是纯代码写法给不了的。样例转写也做得扎实（每条 rule 带 `name` + 指向原代码行号的注释），双跑等价的前提是有的。

因此本次不是"重写"，而是**并入 + 定点改造**：下面的 P0 必须改，P1 建议改，P2 顺手改。

## P0-1 引擎写死了设备 API 的默认值，上游一改就静默错

`_check_color()` 里：

```python
return ctx.owner.image_color_count(spec["button"], color=spec["color"],
                                   threshold=spec.get("threshold", 221), count=spec.get("count", 50))
```

上游 2026-09 的 `color_mask` 重构把 `image_color_count` 的 `threshold` 语义从**相似度下限**（255=完全相同）改成**容差**（0=完全相同），默认值 221 → 30。合并后签名是：

```python
def image_color_count(self, button, color, threshold=30, count=50):
```

于是引擎里每一条**没显式写 threshold 的颜色检查**，实际容差是 221——几乎所有颜色都命中，规则静默恒真。这类 bug 不会抛异常，只会让 bot 少点一次按钮或多点一次，最晚在实机上以"任务没反应"的形式暴露。

同样的问题在 `_check()` 的 `appear(similarity=0.85, threshold=10)`、`_check_template()` 的 `threshold=30` 上：引擎复制了一份设备层默认值，两边会随时间漂移。

**改法**：引擎不再拥有默认值。只把 spec 里**显式写了**的键传给 owner 的方法，其余交给 owner 自己的签名默认值：

```python
def _kwargs(spec: dict, *names: str) -> dict:
    return {k: v for k, v in ((n, spec.get(n)) for n in names) if v is not None}
```

这样默认值只有一个事实源（`module/base/base.py`），上游改默认值时 flow 自动跟随。这类"复制默认值"的 bug 在别的项目里也反复出现，值得当成一条规矩写进评审。

## P0-2 数据写错要等到循环里才炸

`validate_flow()` 在 `run()` 开头跑，但只校验**结构**（state 引用、goto 目标、attempts.limit），不校验 check/action 的**载荷**。于是：

- `{"buton": X}`（拼错）→ 引擎跑到那条规则时 `raise ValueError: unknown check spec`，此时已经截了图、可能已经点过别的按钮；
- `{"colour": ...}` 同理；
- `{"action": {"click": X, "sleep": 1}}` 两个键同时存在 → 引擎按固定顺序取 `click`，`sleep` 被静默忽略。

7×24 的 bot 里，这种错误应该在**加载 flow 的那一刻**就炸，而不是在实机循环中途。

**改法**：`_check`/`_action`/`_apply_control` 各自暴露一张"合法键"表，`validate_flow` 遍历 rules 校验 check/action/control 的键集合（组合键 `and/or/not` 递归）；未知键 → 明确的错误信息（含 flow 名、state 名、rule 名）。顺手把"多键冲突"也判掉。

## P1-3 `run()` 是一个 100 行闭包，两个可变 holder

```python
state_holder = [entry or ...]
timeout_holder = [self._make_timeout(...)]
while True: ...
```

`state_holder[0]` / `timeout_holder[0]` 在闭包间传递，规则求值、退出守卫、超时都在同一个函数体里。后果：单测只能整体跑一个 flow（`tests/test_flow_engine.py` 786 行就是这么来的），任何对规则求值逻辑的改动都要靠端到端 flow 测；`apply()` 返回 `("__done__", value) | None` 的约定也让调用点要再判一次。

**改法**：把一轮循环拆成方法，状态收进一个 dataclass：

```python
@dataclass
class _RunState:
    name: str
    timeout: Timer | None
    attempts: dict[int, dict]
    exit_timers: dict[str, Timer | None]
```

`run()` 只负责 `while True: self._frame(state, flow, ctx)`，`_frame` 再调 `_eval_rules`。规则求值因此能脱离截图单独测（给假 device 就行）。

## P1-4 `run()` 与 `run_group()` 是两套规则求值

`run_group()`（`ui_additional` 的单趟语义）另写了一遍循环，**不支持** `attempts` / `stop` / `then` / `reset_confirm`。今天两边行为一致纯属人工同步；哪天给 `run()` 加个规则字段，忘了 `run_group()`，就是"主页弹窗组和弹窗组行为不一致"这种极难查的问题。

**改法**：抽 `_eval_rules(rules, ctx, state, single_pass)`，`single_pass=True` 时命中即返回（`run_group` 语义），否则按 `stop` 决定是否继续。

## P1-5 没有超时也没有退出条件的 state = 无限循环

`make_loop_flow()` 的 `on_timeout` 默认 None，`_make_timeout()` 返回 None，于是"不截图成功、也不超时"的状态会永远转。原代码里对应的是 `while 1:`，所以这不算回归；但引擎是**新抽象**，应该在启动时就对"既无 exit 又无 on_timeout"的 state 打一条 warning（不改变行为，只是让人知道自己在裸奔）。

## P2-6 小事

- `_timer()` 重新实现了 `Timer.from_seconds(limit, speed=0.5)`（`module/base/timer.py` 已有）。直接复用，少一处 `_SPEED` 常量。
- `{"__var__": name}` 用字符串键做动态退出值的哨兵，和 D14"零字符串引用"的原则有点自相矛盾。可以用一个 3 行的 `Var` 类替代；不改也能接受，但值得记一笔。
- `guard` 与 `check` 是两套几乎一样的机制（`_guard_ok(guard)` vs `_check(spec)`），差别只是 guard 不接 args。`server_eq("cn")` 这种完全可以写成 `{"custom": ...}`。留着也行——guard 在 check 缺席（call_if）时有意义——但文档要写清楚二者何时用哪个。

## 合并时的额外处理

- **丢弃全部探针**：`module/ocr/probe.py`、`module/ocr/al_ocr.py` 的计时、`module/webui/api/routers/probe.py`、`webapp*/src/lib/webviewProbe.ts`、`store.svelte.ts`/`LogView.svelte`/`main.ts` 里的 `[PROBE]` 改动。凡带 `[PROBE]` 前缀一律不取。
- `tests/conftest.py` 与 master 冲突：master 现在有 loguru→caplog 桥（上游的岛屿测试需要它），flow 分支的 runtime 重置 fixture 要**合并**进去，不能整份取一边。
- `module/ui/{navbar,setting}.py` 与上游合并后的改动冲突，需要逐块看。

## 验收

- 引擎单测覆盖到 `_eval_rules` / `_check` / `_action` 三层（不依赖真实 flow）。
- `validate_flow` 能对上面列的每一类错数据报错（每类一个用例）。
- 合并后跑全门：ruff / pyright / pytest / smoke / verify_* / 日志格对齐。
- 真机冒烟：app 登录、地图自动搜索设置确保、任意切页弹窗组单趟、Freebies 任务流。
