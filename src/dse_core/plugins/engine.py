"""引擎服务：字典场景解释器（游戏主循环）。

移植自 dse-core(Node) plugins/engine.js。事件驱动设计（其他插件可通过
ctx.on 扩展，无需改引擎代码）：

- emit:      scene/leave, scene/enter, scene/rendered, choice/made,
             engine/start, engine/end, engine/stop
- bail:      scene/mode（mode 委托：能力插件返回 True 接管界面；
             返回 {redirect: 场景ID} 请求立即正规流转；返回 None/False 回退渲染）
- dispatch:  engine/command（插件逆序拦截输入命令，放行后回落默认命令）
- pipeline:  text/render（文本渲染管道：插值 → 装饰）

命令返回协议：{type: 'choice', index} / {type: 'scene', id} /
{type: 'rerender'} / {type: 'quit'} / {type: 'noop'} / {type: 'nothing'}

「进入场景」与「重绘场景」是两条独立路径：进入（外层）只在 current 真正
变化后发生一次（scene/leave → onEnter → scene/enter）；重绘（内层）只重新
输出界面，不触碰任何状态。
"""

from __future__ import annotations

import os
import random
import sys
import traceback

from .. import modes
from ..runtime import Service


class EngineService(Service):
    """游戏主循环服务（ctx.engine）。"""

    name = "engine"
    inject = ("scenes", "state", "io")

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        # DSE_ENTRY（CLI --entry 透传）优先于 dse.yml 的 engine.entry
        self.entry = os.environ.get("DSE_ENTRY") or self.config.get("entry") or "start"
        self.current: str | None = None
        self.running = False
        self.exit_code = 0
        # P6：加权随机跳转的确定性来源（dse.yml engine.seed 可复现；缺省真随机。
        # rng 状态不入存档 —— 读档后随机序列重新洗牌，属可接受语义）
        self.rng = random.Random(self.config.get("seed"))
        self._pending_exit: str | None = None  # 待执行 onExit 的旧场景 id

    # ------------------------------------------------------------ 生命周期

    def start(self, entry_id: str | None = None) -> None:
        """开始游戏（默认从配置的 entry 场景入场）。"""
        if self.running:
            return
        self.running = True
        self.current = entry_id or self.entry
        self.ctx.emit("engine/start", self.current)
        try:
            self.run()
        except Exception as exc:  # noqa: BLE001 — 异常必须体现在退出码上
            traceback.print_exc()
            print(f"[engine] {exc}", file=sys.stderr)
            self.stop(1)

    def goto(self, scene_id: str) -> None:
        """跳转场景（下一轮循环生效）。记录旧场景供 onExit 挂账。"""
        if self.current is not None and self.current != scene_id:
            self._pending_exit = self.current
        self.current = scene_id

    def stop(self, exit_code: int = 0) -> None:
        """结束游戏：设置退出码并主动清理根作用域。"""
        if not self.running:
            return
        self.running = False
        self.ctx.emit("engine/stop")
        self.ctx.io.blank()
        self.ctx.io.print("游戏已退出，感谢游玩！")
        self.exit_code = exit_code
        self.ctx.dispose()

    # ------------------------------------------------------------ 主循环

    def run(self) -> None:
        while self.running:
            # 0. 旧场景 onExit 挂账结算（goto 时记录，此处兑现；先于新场景一切逻辑）
            if self._pending_exit is not None:
                old_id, self._pending_exit = self._pending_exit, None
                old_scene = self.ctx.scenes.get(old_id)
                if old_scene:
                    for change in self.ctx.state.apply(old_scene.get("onExit")):
                        self.ctx.info("engine", f"effect {change['path']}: {change['from']} -> {change['to']}")

            scene = self.ctx.scenes.get(self.current)

            # 1. 进入场景：离开旧场景 / 应用 onEnter 效果（每进入一次只做一次）
            self.ctx.emit("scene/leave", self.current)
            for change in self.ctx.state.apply(scene.get("onEnter")):
                self.ctx.info("engine", f"effect {change['path']}: {change['from']} -> {change['to']}")

            # mode 扩展点：默认 normal（引擎渲染选项并判定结局）；
            # 其他 mode 由插件接管界面与输入（bail 首个非 None/False 停）。
            mode = scene.get("mode") or "normal"
            mode_result = None if mode == "normal" else self.ctx.bail("scene/mode", self.current, scene, mode)
            if isinstance(mode_result, dict) and isinstance(mode_result.get("redirect"), str):
                self.goto(mode_result["redirect"])
                continue
            handled = bool(mode_result)
            if not handled and mode != "normal":
                # 已注册模式但无插件接管 = 配置错误。Node 版此处静默回退 normal
                # 渲染，会把 mode 场景误判成结局（无选项 → 「（完）」）；
                # Python 版选择响亮失败，避免内容在半个引擎上跑出静默错误行为。
                plugin = modes.MODE_REGISTRY.get(mode, {}).get("plugin") or mode
                raise RuntimeError(
                    f'场景 "{self.current}" 使用模式 "{mode}"，但没有插件接管'
                    f"（请在 dse.yml 安装 {plugin} 插件）"
                )
            self.ctx.emit("scene/enter", self.current, scene)

            # 2. 首次渲染（纯输出，不改状态）
            choices = self.render(scene, mode, handled)

            # 3. 结局判定：仅 normal 模式且无选项时算结局
            #    （battle 等模式由插件控制流转；@restart 选项不计入结局）
            if mode == "normal" and not choices:
                self.ctx.emit("engine/end", self.current, scene)
                self.ctx.io.print("（完）")
                self.ctx.io.ask("按回车结束游戏...")
                return self.stop()

            def redraw() -> list[dict]:
                # 重绘重新取场景对象 —— 内容热重载可能已替换字典里的场景定义
                fresh = self.ctx.scenes.get(self.current)
                return self.render(fresh, mode, handled)

            # 4. 内层输入循环：只有 choice / scene 才跳出到外层（重进新场景）
            while self.running:
                line = self.ctx.io.ask(self.config.get("prompt") or ">> ")
                if not line:
                    choices = redraw()
                    continue  # 空输入 = 刷新界面
                result = self.ctx.dispatch_command(line, choices)
                if result is None:
                    result = self.default_command(line, choices)
                if not result:
                    choices = redraw()
                    continue
                rtype = result.get("type")
                if rtype == "noop":
                    continue  # 插件已自行渲染界面，继续等待输入
                if rtype == "choice":
                    choice = choices[result["index"]]
                    effects = self.ctx.state.apply(choice.get("do"))
                    for change in effects:
                        self.ctx.info("engine", f"effect {change['path']}: {change['from']} -> {change['to']}")
                    self.ctx.emit("choice/made", self.current, choice, effects)
                    goto = choice.get("goto")
                    if isinstance(goto, list):
                        goto = self._pick_weighted(goto)
                    if goto is not None:
                        target = str(goto)
                        if target == "@restart":
                            self.ctx.state.reset()  # 全量重置回 entry（开局重玩）
                            self.goto(self.entry)
                        elif target.startswith("@loop:"):
                            loop_entry = target[len("@loop:"):]
                            self.ctx.state.reset(keep=self.ctx.state.config.get("loopKeep") or [])
                            self.goto(loop_entry)
                        else:
                            self.goto(target)
                    break  # 跳出内层循环 → 外层重新进入新场景
                if rtype == "scene":
                    self.goto(result["id"])
                    break
                if rtype == "quit":
                    return self.stop()
                if rtype == "rerender":
                    choices = redraw()
                    continue
                self.ctx.io.print("（未识别的输入，输入 help 查看帮助）")
                choices = redraw()

    # ------------------------------------------------------------ 渲染与命令

    def _pick_weighted(self, options: list) -> str:
        """加权随机跳转：从 [{to, weight}] 中按权重抽一个目标。

        内容错误响亮报错（dse check 应已拦截，此处为运行时兜底）。
        """
        if not options:
            raise RuntimeError("加权 goto 列表为空")
        total = 0.0
        for item in options:
            weight = (item or {}).get("weight", 1)
            if not isinstance(weight, (int, float)) or weight <= 0:
                raise RuntimeError(f"加权 goto 权重必须为正数: {item!r}")
            if not isinstance((item or {}).get("to"), str):
                raise RuntimeError(f"加权 goto 缺少 to: {item!r}")
            total += weight
        pick = self.rng.random() * total
        for item in options:
            pick -= item.get("weight", 1)
            if pick < 0:
                return item["to"]
        return options[-1]["to"]

    def render(self, scene: dict, mode: str, handled: bool) -> list[dict]:
        """渲染当前场景界面（不产生任何状态变更），返回过滤后的选项列表。"""
        text = scene.get("text", "")
        # P6 条件文本段：extraText 逐项求值，为真才拼接（Ink 条件段的 YAML 化）
        for seg in scene.get("extraText") or []:
            if isinstance(seg, dict) and self.ctx.state.check(seg.get("if")):
                text = f"{text}\n{seg.get('text', '')}"
        text = self.ctx.state.interpolate(text)
        text = self.ctx.pipeline("text/render", text)

        # 条件求值过滤选项（每次重绘都重新求值，反映最新状态）
        choices = [c for c in (scene.get("choices") or []) if self.ctx.state.check(c.get("if"))]

        title = self.ctx.state.interpolate(scene.get("title") or self.current)
        self.ctx.io.blank()
        self.ctx.io.print(f"── {title} ──")
        self.ctx.io.print(text)
        self.ctx.io.blank()

        # 页面渲染完成：插件可在此补充自己的界面（如战斗血条）
        self.ctx.emit("scene/rendered", self.current, scene, mode)

        # 选项渲染：normal 模式由引擎渲染；其他模式交给插件（handled 时跳过）
        if mode == "normal" or not handled:
            for i, choice in enumerate(choices):
                self.ctx.io.print(f"  [{i + 1}] {self.ctx.state.interpolate(choice['text'])}")
            self.ctx.io.blank()
        return choices

    def default_command(self, line: str, choices: list) -> dict:
        """默认命令处理器：编号选项 + 内置命令。"""
        try:
            number = int(line)
        except ValueError:
            number = None
        if number is not None and 1 <= number <= len(choices):
            return {"type": "choice", "index": number - 1}
        cmd = line.strip().lower()
        if cmd in ("help", "?"):
            self.ctx.io.print("内置命令: 选项编号进行选择 | help 帮助 | stats 查看状态 | quit 退出")
            return {"type": "rerender"}
        if cmd in ("stats", "status"):
            get = self.ctx.state.get
            self.ctx.io.print(f"  {get('name')} | HP {get('hp')} | ATK {get('atk')} | 金币 {get('gold')}")
            items = get("items") or {}
            held = [(k, v) for k, v in items.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0]
            self.ctx.io.print("  背包: " + ("，".join(f"{k}×{v}" for k, v in held) if held else "（空）"))
            return {"type": "rerender"}
        if cmd in ("quit", "exit"):
            return {"type": "quit"}
        return {"type": "nothing"}
