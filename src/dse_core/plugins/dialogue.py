"""对话/谈判模式插件 —— 多角色对话界面（引擎零改动）。

移植自 dse-core(Node) plugins/dialogue.js。

接入方式：场景声明 ``mode: 'dialogue'`` + ``dialogue: {npc, notes, onEnd, topics}``；
引擎 bail 'scene/mode' 时本插件返回 True 接管。玩家「问」一个话题 → 显示 reply、
执行 effect；``end`` 或注意点耗尽 → 流转 onEnd。

设计原则：**确定性优先** —— 话题 reply 与 effect 全部数据驱动，e2e 可精确复现；
注意点预算（notes，可选）约束「每轮取舍」，问满强制结束（0 = 不限）。

状态：state.dialogueAsked（已问话题 ID 数组，防重复，存档可恢复）
命令：ask <话题编号或名称> | topics 话题列表 | again 重看 | end 结束
"""

from __future__ import annotations

from ..runtime import Service
from .commands import is_global_command


class DialogueService(Service):
    """对话服务（ctx.dialogue，可选插件）。"""

    name = "dialogue"
    inject = ("state", "engine", "io")

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.active: dict | None = None

    def setup(self) -> None:
        self.ctx.on("scene/mode", self._on_scene_mode)
        self.ctx.on("engine/command", self._on_command)
        self.ctx.on("scene/rendered", self._on_scene_rendered)
        self.ctx.on("scene/leave", self._on_scene_leave)
        self.ctx.info("dialogue", "loaded")

    # ------------------------------------------------------------ 事件钩子

    def _on_scene_mode(self, scene_id, scene, mode):
        if mode != "dialogue":
            return None
        self.begin(scene.get("dialogue") or {})
        return True

    def _on_command(self, line, choices):
        if not self.active:
            return None
        return self.handle(line)

    def _on_scene_rendered(self, *_args) -> None:
        if self.active:
            self.render()

    def _on_scene_leave(self, *_args) -> None:
        self.active = None

    # ------------------------------------------------------------ 开谈

    def begin(self, dlg: dict) -> None:
        state = self.ctx.state
        if state.get("dialogueAsked") is None:
            state.set("dialogueAsked", [])
        self.active = {
            "onEnd": dlg.get("onEnd"),
            "npc": dlg.get("npc") or "那人",
            "notes": dlg.get("notes") or 0,   # 注意点预算：0 = 不限
            "topics": dlg.get("topics") or [],
            "asked": list(state.get("dialogueAsked") or []),
            "used": 0,                        # 本场已问次数（插件内计数，不进 state）
        }

    def visible(self) -> list:
        """当前可见话题（按 if 条件过滤；编号随可见列表重排）。"""
        if not self.active:
            return []
        return [t for t in self.active["topics"] if not t.get("if") or self.ctx.state.check(t["if"])]

    # ------------------------------------------------------------ 命令

    def handle(self, line: str):
        parts = line.strip().split()
        cmd = parts[0].lower() if parts else ""
        args = parts[1:]
        if cmd in ("ask", "a", "问"):
            return self.do_ask(" ".join(args))
        if cmd in ("topics", "t", "话题"):
            self.render()
            return {"type": "noop"}
        if cmd in ("again", "再看"):
            self.render()
            return {"type": "noop"}
        if cmd in ("end", "n", "next", "结束"):
            return self.finish()
        if cmd in ("help", "?"):
            self.ctx.io.print("  对话指令: ask <话题编号或名称> 询问 | topics 话题列表 | end 结束")
            self.render()
            return {"type": "noop"}
        if is_global_command(line):
            return None
        self.ctx.io.print(f"  对话中不可用：{line.strip() or '(空)'}（指令: ask <话题> | topics | end）")
        self.render()
        return {"type": "noop"}

    def do_ask(self, value: str):
        active = self.active
        if not value:
            self.render()
            return {"type": "noop"}
        topic = None
        for i, t in enumerate(self.visible()):
            if value in (t.get("id"), t.get("name")) or value == str(i + 1):
                topic = t
                break
        if topic is None:
            self.ctx.io.print(f"  没有这个话题：{value}。输入 topics 看话题列表。")
            self.render()
            return {"type": "noop"}
        if topic["id"] in active["asked"]:
            self.ctx.io.print(f"  「{topic['name']}」——你已经问过了，他不再多说。")
            self.render()
            return {"type": "noop"}
        if active["notes"] > 0 and active["used"] >= active["notes"]:
            self.ctx.io.print("  你的注意点用尽了，只能结束这场对话。")
            return self.finish()
        self.ctx.io.print(f"  【{active['npc']}】{topic['reply']}")
        self.ctx.state.apply(topic.get("effect") or {})
        active["asked"].append(topic["id"])
        self.ctx.state.set("dialogueAsked", list(active["asked"]))
        active["used"] += 1
        self.ctx.io.blank()
        self.render()
        return {"type": "noop"}

    def finish(self):
        npc = self.active["npc"]
        on_end = self.active["onEnd"]
        self.ctx.io.print(f"  你与{npc}的对话告一段落。")
        self.active = None
        if on_end:
            self.ctx.engine.goto(on_end)
            return {"type": "scene", "id": on_end}
        return {"type": "noop"}

    def render(self) -> None:
        if not self.active:
            return
        active = self.active
        self.ctx.io.blank()
        self.ctx.io.print(f"  ── 与{active['npc']}对话 ──")
        rows = []
        for i, t in enumerate(self.visible()):
            asked = t["id"] in active["asked"]
            mark = "·" if asked else f"{i + 1}."
            suffix = "（已问过）" if asked else ""
            rows.append(f"    {mark} {t['name']}{suffix}")
        self.ctx.io.print("\n".join(rows) or "    （无话可问）")
        if active["notes"] > 0:
            self.ctx.io.print(f"  注意点余量：{max(0, active['notes'] - active['used'])} / {active['notes']}")
        self.ctx.io.print("  指令: ask <话题编号或名称> 询问 | topics 话题列表 | end 结束")
        self.ctx.io.blank()
