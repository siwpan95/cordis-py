"""战斗数值系统插件 —— 回合制战斗 + 数值公式（引擎零改动）。

移植自 dse-core(Node) plugins/combat.js。接入方式：场景字典声明
``mode: 'battle'`` + ``battle: {enemy, onWin, onLose, onFlee}``；
引擎 bail 'scene/mode' 时本插件返回 True 宣告接管，之后该场景的输入全部
由本插件处理（engine/command 逆序拦截），战斗结束流转对应分支。

数值设计（可在 dse.yml 覆盖 formula 参数）::

    伤害 = max(1, round((atk * 随机波动 - def * 减伤系数) * 暴击倍率 * 姿态系数))
    姿态：attack 正常受击；defend 本回合减伤 defendCut；flee 成功率 fleeChance

事件：battle/start、battle/hit、battle/crit、battle/end（音效插件订阅发声）。
"""

from __future__ import annotations

import math
import random

from ..runtime import Service

DEFAULT_FORMULA = {
    "variance": 0.2,      # 伤害随机波动 ±20%
    "defenseFactor": 0.5,  # 每点防御抵消的伤害
    "critMult": 1.8,      # 暴击倍率
    "defendCut": 0.5,     # 防御姿态减伤 50%
    "fleeChance": 0.45,   # 逃跑成功率
}

# 战斗中放行给引擎处理的全局命令（stats / quit 等）
_GLOBAL_COMMANDS = {"help", "?", "stats", "status", "quit", "exit"}


def _round_half_up(x: float) -> int:
    """JS Math.round 语义（半数趋近 +∞）；Python round 是半数趋偶，需换算。"""
    return math.floor(x + 0.5)


class CombatService(Service):
    """战斗服务（ctx.combat，可选插件）。"""

    name = "combat"
    inject = ("state", "engine", "io")

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.formula = {**DEFAULT_FORMULA, **(self.config.get("formula") or {})}
        self.enemies = self.config.get("enemies") or {}
        self.weapons = self.config.get("weapons") or {}
        self.active: dict | None = None
        self.last_roll: dict | None = None

    def setup(self) -> None:
        self.ctx.on("scene/mode", self._on_scene_mode)
        self.ctx.on("engine/command", self._on_command)
        self.ctx.on("scene/rendered", self._on_scene_rendered)
        self.ctx.on("scene/leave", self._on_scene_leave)
        self.ctx.info("combat", f"loaded {len(self.enemies)} enemies")

    # ------------------------------------------------------------ 事件钩子

    def _on_scene_mode(self, scene_id, scene, mode):
        if mode != "battle":
            return None
        return self.begin(scene.get("battle") or {})

    def _on_command(self, line, choices):
        if not self.active:
            return None
        return self.handle(line)

    def _on_scene_rendered(self, *_args) -> None:
        if self.active:
            self.render()

    def _on_scene_leave(self, *_args) -> None:
        self.active = None

    # ------------------------------------------------------------ 开战与数值

    def begin(self, battle: dict):
        """开战：初始化战斗状态。

        返回 True = 已接管；{redirect} = 缺敌人但有 onWin，请求立即正规
        流转；None = 缺敌人且无 onWin，回退 normal 渲染。
        """
        enemy_id = battle.get("enemy") or "dummy"
        enemy = self.enemies.get(enemy_id)
        if not enemy:
            if battle.get("onWin"):
                self.ctx.io.print(f'  （战斗配置错误：未定义敌人 "{enemy_id}"，直接进入后续场景）')
                return {"redirect": battle["onWin"]}
            self.ctx.io.print(f'  （战斗配置错误：未定义敌人 "{enemy_id}" 且无 onWin 回退）')
            return None
        self.active = {
            "id": enemy_id,
            "battle": battle,
            "enemy": enemy,
            "hp": enemy["hp"],
            "maxHp": enemy["hp"],
            "turn": 1,
            "defending": False,
        }
        # 界面由 'scene/rendered' 统一渲染（保证「场景文本 → 战斗面板」的顺序）
        self.ctx.emit("battle/start", enemy_id, enemy)
        return True

    def player_stats(self) -> dict:
        """玩家战斗属性：基础属性 + 背包武器加成。"""
        state = self.ctx.state
        atk = state.get("atk")
        if atk is None:
            atk = 1
        bonus: list[str] = []
        for item_id, count in (state.get("items") or {}).items():
            weapon = self.weapons.get(item_id)
            if not weapon or not (isinstance(count, (int, float)) and not isinstance(count, bool) and count > 0):
                continue
            atk += (weapon.get("atk") or 0) * count
            bonus.append(f"{weapon.get('name') or item_id}+{(weapon.get('atk') or 0) * count}")
        crit = state.get("crit")
        return {
            "atk": atk,
            "bonus": bonus,
            "def": state.get("def") or 0,
            "crit": crit if crit is not None else 0.05,
        }

    def roll_damage(self, attacker: dict, defender: dict) -> dict:
        """伤害结算：返回 {dmg, crit}。"""
        f = self.formula
        variance = 1 + (random.random() * 2 - 1) * f["variance"]
        crit = random.random() < (attacker.get("crit") or 0)
        raw = (attacker.get("atk") or 1) * variance - (defender.get("def") or 0) * f["defenseFactor"]
        base = max(1, _round_half_up(raw))
        dmg = max(1, _round_half_up(base * (f["critMult"] if crit else 1)))
        return {"dmg": dmg, "crit": crit}

    # ------------------------------------------------------------ 输入处理

    def handle(self, line: str) -> dict | None:
        """处理战斗中的输入命令；返回 None = 放行给引擎。"""
        command = line.strip().lower()
        if command in ("a", "1", "攻击"):
            return self.player_turn("attack")
        if command in ("d", "2", "防御"):
            return self.player_turn("defend")
        if command in ("r", "3", "逃跑"):
            return self.player_turn("flee")
        if command in ("help", "?"):
            self.ctx.io.print("  战斗指令: a 攻击 | d 防御（减伤 50%）| r 逃跑 | help 帮助 | quit 退出")
            self.render()
            return {"type": "noop"}
        if command in _GLOBAL_COMMANDS:
            return None  # 全局命令放行（stats / quit 等由引擎处理）
        # 其余输入维持拦截，但明确拒绝（不静默吞掉）
        self.ctx.io.print(f"  战斗中不可用：{line.strip() or '(空)'}（战斗指令: a 攻击 | d 防御 | r 逃跑 | help 帮助 | quit 退出）")
        self.render()
        return {"type": "noop"}

    def player_turn(self, action: str) -> dict:
        battle = self.active["battle"]
        enemy = self.active["enemy"]
        me = self.player_stats()

        # 1. 玩家行动
        if action == "flee":
            if random.random() < self.formula["fleeChance"]:
                self.ctx.io.print("  你成功脱身，逃之夭夭。")
                self.active = None
                if battle.get("onFlee"):
                    self.ctx.engine.goto(battle["onFlee"])
                    return {"type": "scene", "id": battle["onFlee"]}
                return {"type": "noop"}
            self.ctx.io.print("  逃跑失败！敌人挡住了退路。")
        elif action == "defend":
            self.active["defending"] = True
            self.ctx.io.print("  你举盾防御，本回合受到的伤害将大幅减少。")
        else:
            roll = self.roll_damage(me, enemy)
            self.active["hp"] = max(0, self.active["hp"] - roll["dmg"])
            self.last_roll = {"side": "player", "dmg": roll["dmg"], "crit": roll["crit"]}
            self.ctx.emit("battle/crit" if roll["crit"] else "battle/hit", "player", roll["dmg"], roll["crit"])
            self.ctx.io.print(
                f"  暴击！你对{enemy['name']}造成 {roll['dmg']} 点伤害！" if roll["crit"]
                else f"  你对{enemy['name']}造成 {roll['dmg']} 点伤害。"
            )
            self.active["defending"] = False

        # 2. 胜负判定
        if self.active["hp"] <= 0:
            return self.finish(True, battle)

        # 3. 敌人反击
        incoming = self.roll_damage(enemy, me)
        cut = self.formula["defendCut"] if self.active["defending"] else 1
        taken = max(1, _round_half_up(incoming["dmg"] * cut))
        self.ctx.state.apply({"hp": -taken})
        self.last_roll = {"side": "enemy", "dmg": taken, "crit": incoming["crit"]}
        self.ctx.emit("battle/crit" if incoming["crit"] else "battle/hit", "enemy", taken, incoming["crit"])
        self.ctx.io.print(
            f"  {enemy['name']}暴击！你受到 {taken} 点伤害！" if incoming["crit"]
            else f"  {enemy['name']}反击，你受到 {taken} 点伤害。"
        )
        self.active["defending"] = False

        # 4. 玩家阵亡判定
        if (self.ctx.state.get("hp") or 0) <= 0:
            return self.finish(False, battle)

        self.active["turn"] += 1
        self.render()
        return {"type": "noop"}

    def finish(self, is_win: bool, battle: dict) -> dict:
        """战斗结束：结算掉落 + 跳转分支。"""
        enemy = self.active["enemy"]
        self.ctx.emit("battle/end", is_win, enemy)
        if is_win and enemy.get("drops"):
            for change in self.ctx.state.apply(enemy["drops"]):
                frm = change["from"] if change["from"] is not None else "无"
                self.ctx.io.print(f"  战利品：{change['path']} {frm} → {change['to']}")
        self.ctx.io.print(f"  你击败了{enemy['name']}！" if is_win else f"  你被{enemy['name']}击倒了...")
        self.active = None
        target = battle.get("onWin") if is_win else battle.get("onLose")
        if target:
            self.ctx.engine.goto(target)
            return {"type": "scene", "id": target}
        return {"type": "noop"}

    # ------------------------------------------------------------ 界面

    def render(self) -> None:
        """渲染战斗界面（血条 + 玩家状态）。"""
        if not self.active:
            return
        enemy = self.active["enemy"]
        hp, max_hp, turn = self.active["hp"], self.active["maxHp"], self.active["turn"]

        def bar(current: float, max_value: float, width: int = 20) -> str:
            filled = max(0, min(width, _round_half_up(current / max_value * width))) if max_value else 0
            return "█" * filled + "░" * (width - filled)

        me = self.player_stats()
        my_hp = self.ctx.state.get("hp")
        my_max_hp = self.ctx.state.get("maxHp")
        if my_max_hp is None:
            my_max_hp = my_hp
        bonus = f" (ATK {me['atk']} 含{'，'.join(me['bonus'])})" if me["bonus"] else ""
        name = self.ctx.state.get("name")
        self.ctx.io.blank()
        self.ctx.io.print(f"  ⚔ 第 {turn} 回合")
        self.ctx.io.print(f"  {str(enemy['name']).ljust(8, '　')} {bar(hp, max_hp)} {hp}/{max_hp}")
        self.ctx.io.print(f"  {str(name).ljust(8, '　')} {bar(my_hp, my_max_hp)} {my_hp}/{my_max_hp}{bonus}")
        self.ctx.io.blank()
        self.ctx.io.print("  指令: [a] 攻击   [d] 防御   [r] 逃跑   [help] 帮助")
        self.ctx.io.blank()
