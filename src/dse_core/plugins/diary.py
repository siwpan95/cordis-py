"""日记回溯插件 —— 只读重读已走过的篇目（引擎零改动）。

移植自 dse-core(Node) plugins/diary.js。

接入方式：场景声明 ``mode: 'diary'`` + ``diary: {onExit}``；引擎 bail
'scene/mode' 时本插件返回 True 接管。

⚠️ 核心约束：**只读**。重读绝不走 engine.goto、不执行 onEnter —— 否则每重读
一次就重放一次副作用（扣金币、叠加道具），与「rerender 重放 onEnter」是同一类
bug。本插件只取场景对象渲染 title + text，不触碰任何状态。

状态：state.diaryRead（已读篇目 ID 数组，有序去重；存档可恢复）
命令：<编号> 重读该篇 | back 返回 | help 帮助
"""

from __future__ import annotations

from ..runtime import Service
from .commands import is_global_command


class DiaryService(Service):
    """日记回溯服务（ctx.diary，可选插件）。"""

    name = "diary"
    inject = ("state", "engine", "io", "scenes")

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.active: dict | None = None

    def setup(self) -> None:
        self.ctx.on("scene/mode", self._on_scene_mode)
        self.ctx.on("scene/enter", self._on_scene_enter)
        self.ctx.on("engine/command", self._on_command)
        self.ctx.on("scene/rendered", self._on_scene_rendered)
        self.ctx.on("scene/leave", self._on_scene_leave)
        self.ctx.info("diary", "loaded")

    # ------------------------------------------------------------ 事件钩子

    def _on_scene_mode(self, scene_id, scene, mode):
        if mode != "diary":
            return None
        self.active = {"id": scene_id, "onExit": (scene.get("diary") or {}).get("onExit")}
        return True

    def _on_scene_enter(self, scene_id, scene) -> None:
        # 进入任何场景都记一笔，供回溯列表展示；diary 场景自身除外（目录里不该有目录）
        if (scene or {}).get("mode") == "diary":
            return
        self.mark_read(scene_id)

    def _on_command(self, line, choices):
        if not self.active:
            return None
        return self.handle(line)

    def _on_scene_rendered(self, *_args) -> None:
        if self.active:
            self.render()

    def _on_scene_leave(self, *_args) -> None:
        self.active = None

    # ------------------------------------------------------------ 已读列表

    def mark_read(self, scene_id) -> None:
        if not scene_id:
            return
        read = self.read_list()
        if scene_id not in read:
            self.ctx.state.set("diaryRead", [*read, scene_id])

    def read_list(self) -> list:
        """已读 ID 列表（防御：存档里可能是 null 或非数组）。"""
        value = self.ctx.state.get("diaryRead")
        return list(value) if isinstance(value, list) else []

    def entries(self) -> list:
        """可重读的篇目：已读 ∩ 字典中仍存在（内容改版删掉的自动剔除）。"""
        return [sid for sid in self.read_list() if self.ctx.scenes.has(sid)]

    # ------------------------------------------------------------ 命令

    def handle(self, line: str):
        raw = str(line or "").strip()
        if not raw:
            self.render()
            return {"type": "noop"}
        read = self.entries()
        try:
            number = int(raw)
        except ValueError:
            number = None
        if number is not None and 1 <= number <= len(read):
            self.read_entry(read[number - 1])
            self.render()
            return {"type": "noop"}
        cmd = raw.lower()
        if cmd in ("back", "b", "q", "返回", "退出"):
            return self.exit()
        if cmd in ("help", "?"):
            self.ctx.io.print("  札记指令: 输入编号重读该篇 | back 返回 | help 帮助")
            self.render()
            return {"type": "noop"}
        if is_global_command(raw):
            return None
        self.ctx.io.print(f"  札记中不可用：{raw}（指令: 编号 重读 | back 返回 | help 帮助）")
        self.render()
        return {"type": "noop"}

    def read_entry(self, scene_id: str) -> None:
        """重读一篇：只读渲染 title + text。刻意不走 engine.goto。"""
        try:
            scene = self.ctx.scenes.get(scene_id)
        except KeyError:
            return
        title = self.ctx.state.interpolate(scene.get("title") or scene_id)
        text = self.ctx.state.interpolate(scene.get("text") or "")
        self.ctx.io.blank()
        self.ctx.io.print(f"  ── {title} ──")
        # 正文整体缩进两格，与列表层级区分开
        for line in str(text).split("\n"):
            self.ctx.io.print(f"  {line}")
        self.ctx.io.blank()

    def exit(self):
        """退出回溯：回到场景声明的 diary.onExit（走正规流转）。"""
        on_exit = (self.active or {}).get("onExit")
        self.active = None
        if on_exit:
            self.ctx.engine.goto(on_exit)
            return {"type": "scene", "id": on_exit}
        return {"type": "rerender"}  # 未声明 onExit：就地重绘（刷新目录页）

    def render(self) -> None:
        if not self.active:
            return
        read = self.entries()
        self.ctx.io.blank()
        # 标题刻意不与场景 title 同名：引擎已渲染过一次场景标题，重名会像重复渲染
        self.ctx.io.print("  ── 可重读的篇目 ──")
        if not read:
            self.ctx.io.print("  （还没有可重读的篇目。）")
        else:
            for i, scene_id in enumerate(read):
                try:
                    scene = self.ctx.scenes.get(scene_id)
                    title = self.ctx.state.interpolate(scene.get("title") or scene_id)
                except KeyError:
                    title = scene_id
                self.ctx.io.print(f"    [{i + 1}] {title}")
        self.ctx.io.blank()
        self.ctx.io.print("  指令: 编号 重读该篇 | back 返回 | help 帮助")
        self.ctx.io.blank()
