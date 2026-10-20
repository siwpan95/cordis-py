"""状态遍历（traverse）—— 从 entry 出发真实驱动引擎，走遍全图。

与 :mod:`dse_core.graph` 的分工（重要区别）：

- ``graph.py`` 是**静态**分析：只看场景字典的 goto 拓扑，不解条件、不执行效果，
  回答的是「结构上能到哪」。
- ``traverse.py`` 是**动态**遍历：真的把引擎跑起来，在每个场景用当时的**真实状态**
  求值条件、执行效果、跟随实际跳转，回答的是「跑起来真能到哪、条件与效果有没有炸」。

两者会不一致，且这种不一致本身就是要抓的信号 —— 静态可达但动态走不到，通常意味着
某个 ``if`` 恒假（死选项）或效果写错把状态带偏了。

移植自 dse-core(Node) 的 ``test:traverse`` / ``test:coverage`` 两级门：

1. ``traverse()``：DFS 全图，返回走过的边、可达结局、执行错误。
2. ``coverage()``：判定每个结局是否有「来源」证明它可达，双缺则门禁失败。

设计取舍：为什么用 DFS 而不是 BFS
--------------------------------
结局覆盖关心的是「存在一条能抵达它的路径」，DFS 先钻到底更快碰到结局；
且 DFS 的分支栈天然对应「一个选择点上的多个选项」，与内容作者的心智模型一致。
"""

from __future__ import annotations

import contextlib
import io
import os
import random
from dataclasses import dataclass, field

from .graph import is_ending

#: 单次遍历的步数上限（防御内容里 @loop / 加权随机造成的活锁）
DEFAULT_MAX_STEPS = 500

#: 单条路径上「同一场景」允许重复进入的次数上限。
#: 时间循环（@loop）内容正常会重复进入，但必须收敛，否则 DFS 不会终止。
DEFAULT_MAX_REVISIT = 3


@dataclass
class Trace:
    """一次遍历的完整记录。"""

    #: 走过的边：(from, to, kind)，kind 同 graph.edges_of 的 choice/mode/call
    edges: set[tuple[str, str, str]] = field(default_factory=set)
    #: 实际进入过的场景
    visited: set[str] = field(default_factory=set)
    #: 抵达过的结局场景
    endings: set[str] = field(default_factory=set)
    #: 求值/跳转过程中抛出的异常（场景 ID + 摘要）
    errors: list[dict] = field(default_factory=list)
    #: 走过的完整路径数（DFS 分支数）
    paths: int = 0
    #: 因步数/重访上限而截断的分支（按「场景+原因」去重 —— DFS 会在同一处反复撞限，
    #: 不去重会把几十条相同记录刷进来，反而淹没真正的问题）
    truncated: list[str] = field(default_factory=list)

    def mark_truncated(self, scene_id: str, reason: str) -> None:
        item = f"{scene_id}（{reason}）"
        if item not in self.truncated:
            self.truncated.append(item)

    def to_dict(self) -> dict:
        return {
            "visited": sorted(self.visited),
            "edges": sorted(f"{a}->{b}#{k}" for a, b, k in self.edges),
            "endings": sorted(self.endings),
            "errors": self.errors,
            "paths": self.paths,
            "truncated": self.truncated,
        }


def _children(ctx, scene_id: str, scene: dict) -> list[dict]:
    """当前场景在**当前状态**下的可见去向。

    与 graph.edges_of 的关键差别：这里调用引擎的 ``render`` 求值 ``if`` 条件，
    拿到的才是「玩家此刻真能选的那些」，而不是「字典里写着的全部」。

    ``render`` 会直接往 ctx.io 打印界面（标题/正文/选项），遍历时用
    ``redirect_stdout`` 吞掉 —— 我们只要它的**返回值**（过滤后的选项列表），
    不要它的副作用，否则跑一次 traverse 会把整棵树的剧情刷满屏。
    """
    engine = ctx.services["engine"]
    mode = scene.get("mode") or "normal"
    if mode != "normal":
        # 非 normal 模式由插件接管界面，选项不由引擎渲染；退回静态出边
        from .graph import edges_of

        return [{"to": e["to"], "kind": e["kind"]} for e in edges_of(scene_id, scene)]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            choices = engine.render(scene, mode, False)
    except Exception as exc:  # 条件表达式炸了 —— 正是要抓的东西
        raise _SceneError(f"渲染 {scene_id} 失败: {type(exc).__name__}: {exc}") from exc
    out: list[dict] = []
    for choice in choices:
        goto = choice.get("goto")
        if isinstance(goto, dict):  # P8 tunnels：{call: x}
            call = goto.get("call")
            if isinstance(call, str) and call:
                out.append({"to": call, "kind": "call"})
            continue
        if isinstance(goto, list):  # 加权随机：每个分支都算一条
            for item in goto:
                if isinstance(item, dict):
                    to = str(item.get("to") or "")
                    if to and not to.startswith("@"):
                        out.append({"to": to, "kind": "choice"})
        elif goto:
            to = str(goto)
            if to.startswith("@"):
                continue
            out.append({"to": to, "kind": "choice"})
    return out


class _SceneError(RuntimeError):
    """场景求值错误（内部信号，由 traverse 捕获转成 errors 记录）。"""


def traverse(ctx, *, entry: str, max_steps: int = DEFAULT_MAX_STEPS,
             max_revisit: int = DEFAULT_MAX_REVISIT, seed: int | None = None) -> Trace:
    """从 entry 出发 DFS 遍历全图，真实执行每条边。

    会临时接管引擎的输入通道（脚本模式），遍历结束后恢复，**不产生外部副作用**
    （不写存档、不改进程环境 —— ``DSE_INPUT`` 用 try/finally 清掉）。
    """
    trace = Trace()
    state = ctx.services["state"]
    scenes = ctx.services["scenes"]
    engine = ctx.services["engine"]
    if seed is not None:
        engine.rng = random.Random(seed)

    base_state = state.snapshot()

    def walk(scene_id: str, path: list[str], steps: int) -> None:
        if steps > max_steps:
            trace.mark_truncated(scene_id, f"步数超限 {max_steps}")
            return
        if path.count(scene_id) > max_revisit:
            trace.mark_truncated(scene_id, f"重访超限 {max_revisit}")
            return
        if not scenes.has(scene_id):
            trace.errors.append({"scene": scene_id, "error": "场景不存在（悬空跳转）"})
            return
        scene = scenes.get(scene_id)

        trace.visited.add(scene_id)
        if is_ending(scene):
            trace.endings.add(scene_id)
            trace.paths += 1
            return

        try:
            children = _children(ctx, scene_id, scene)
        except _SceneError as exc:
            trace.errors.append({"scene": scene_id, "error": str(exc)})
            return

        if not children:
            # 非结局却没有去向 —— 动态意义上是死路（静态可能认为它有选项，但条件全假）
            trace.errors.append({"scene": scene_id, "error": "无可用去向（所有选项条件均为假）"})
            return

        for child in children:
            to = child["to"]
            trace.edges.add((scene_id, to, child["kind"]))
            snapshot = state.snapshot()
            try:
                state.restore(snapshot)
            except Exception:  # noqa: BLE001 —— 快照恢复失败要记账，不能静默
                trace.errors.append({"scene": scene_id, "error": "状态快照恢复失败"})
                return
            walk(to, path + [to], steps + 1)
            state.restore(snapshot)

    # 遍历从干净初始状态开始，结束后还原，避免污染调用方
    state.reset()
    try:
        walk(entry, [entry], 0)
    finally:
        state.restore(base_state)
    return trace


@dataclass
class CoverageReport:
    """结局覆盖门的结果。"""

    endings: list[str] = field(default_factory=list)
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    sources: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.missing

    def to_dict(self) -> dict:
        return {
            "endings": self.endings,
            "covered": self.covered,
            "missing": self.missing,
            "sources": self.sources,
            "ok": self.ok,
        }


def coverage(scenes, trace: Trace, *, e2e_endings=None) -> CoverageReport:
    """结局覆盖门：每个结局都必须有来源证明它可达。

    参数 ``scenes`` 接受 ``SceneService``（``ctx.services["scenes"]``）或普通
    ``dict[scene_id, scene]`` —— 前者更常见，故不再强制调用方先转一层。

    来源分两类（对齐 Node 版的双缺判定）：

    - ``T``（traverse）：本次动态遍历实际走到过；
    - ``E``（e2e）：由调用方传入的既有端到端用例断言过的结局。

    双缺 → 该结局进 ``missing``，门禁失败。这条门的价值在于：内容加了新结局却没人
    验证过，静态 lint 看不出来（悬空/可达都正常），只有「没人走过」这件事本身是信号。
    """
    e2e = set(e2e_endings or ())
    # SceneService 暴露 .dict；裸 dict 直接用
    mapping = getattr(scenes, "dict", scenes)
    report = CoverageReport()
    for scene_id, scene in mapping.items():
        if not is_ending(scene):
            continue
        report.endings.append(scene_id)
        src: list[str] = []
        if scene_id in trace.endings:
            src.append("T")
        if scene_id in e2e:
            src.append("E")
        report.sources[scene_id] = src
        if src:
            report.covered.append(scene_id)
        else:
            report.missing.append(scene_id)
    report.endings.sort()
    report.covered.sort()
    report.missing.sort()
    return report


def trail_env_cleanup() -> None:
    """清掉遍历可能残留的进程环境（traverse 自身不设，但调用方可能设过）。"""
    os.environ.pop("DSE_INPUT", None)
