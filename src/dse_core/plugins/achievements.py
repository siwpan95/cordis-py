"""成就插件 —— 零侵入扩展示例：不改引擎一行代码，只监听事件 + 拦截命令。

移植自 dse-core(Node) plugins/achievements.js。

1. 成就表在 dse.yml 配置里声明（数据驱动，与场景字典同哲学）
2. 监听 scene/enter、choice/made 事件检查解锁条件
3. 拦截 engine/command 提供 achievements 命令
4. 解锁时 emit 'achievement/unlock'，其他插件（音效/弹窗）可自行订阅

注意事件签名：scene/enter 的第一个参数是**场景 ID 字符串**（与 Node 版
emit('scene/enter', current, scene) 一致），成就条件的 when 表达式里
`scene == "wolf-win"` 玩的就是这个。
"""

from __future__ import annotations

from ..runtime import Service


class AchievementsService(Service):
    """成就服务（ctx.achievements，可选插件；save 插件依赖它）。"""

    name = "achievements"
    inject = ("state", "engine", "io")

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.unlocked: set[str] = set()
        self.table: dict[str, dict] = {}

    def setup(self) -> None:
        for item in self.config.get("list") or []:
            self.table[item["id"]] = item
        self.ctx.info("achievements", f"registered {len(self.table)} achievements")
        self.on("scene/enter", self._on_scene_enter)
        self.on("choice/made", self._on_choice_made)
        self.on("engine/command", self._on_command)

    # ------------------------------------------------------------ 事件与命令

    def _on_scene_enter(self, scene_id, scene) -> None:
        self.check(scene_id)

    def _on_choice_made(self, scene_id, choice, effects) -> None:
        self.check(scene_id, choice, effects)

    def _on_command(self, line: str, choices: list):
        if line.strip().lower() not in ("achievements", "成就"):
            return None
        self.show()
        return {"type": "rerender"}

    # ------------------------------------------------------------ 解锁逻辑

    def check(self, scene_id, choice=None, effects=None) -> None:
        """检查所有成就条件；条件上下文包含场景 ID、选项与效果。"""
        for aid, item in self.table.items():
            if aid in self.unlocked:
                continue
            if self.ctx.state.check(item.get("when"), {"scene": scene_id, "choice": choice, "effects": effects}):
                self.unlock(aid)

    def unlock(self, aid: str) -> None:
        item = self.table.get(aid)
        if not item or aid in self.unlocked:
            return
        self.unlocked.add(aid)
        self.ctx.emit("achievement/unlock", aid, item)
        self.ctx.io.print(f"  ★ 成就解锁：{item['name']} —— {item['desc']}")

    def restore(self, ids) -> None:
        """读档恢复解锁集合：只保留仍在成就表中的 id（内容改版兜底）。"""
        if not isinstance(ids, list):
            return
        for aid in ids:
            if isinstance(aid, str) and aid in self.table and aid not in self.unlocked:
                self.unlocked.add(aid)

    def show(self) -> None:
        if not self.table:
            self.ctx.io.print("  （暂无成就）")
            return
        for aid, item in self.table.items():
            mark = "✓" if aid in self.unlocked else " "
            self.ctx.io.print(f"  [{mark}] {item['name']} —— {item['desc']}")
