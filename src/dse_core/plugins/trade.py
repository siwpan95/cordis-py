"""经营数值系统插件 —— 天数循环 + 库存买卖 + 确定性行情日程（引擎零改动）。

移植自 dse-core(Node) plugins/trade.js。

接入方式：场景声明 ``mode: 'trade'`` + ``trade: {name, days, onEnd}``；
引擎 bail 'scene/mode' 时本插件返回 True 接管，经营结束流转 onEnd。

设计原则：**确定性优先**（对照 combat 的随机性）——每日行情由 dse.yml 的
schedule 表写死（行=商品，列=第 N 天卖出价），策略可计算、e2e 可精确复现。

状态：state.gold（资金）/ state.stock（库存）/ state.tradeDay（天数，
存档可恢复）/ state.tradeBaseGold（开市基线）/ state.tradeProfit（收市净赚）
命令：buy <商品> [数量] | sell <商品> [数量] | next 下一天 | info 行情
"""

from __future__ import annotations

import math

from ..runtime import Service
from .commands import is_global_command

# 商品表默认值（可被 dse.yml 覆盖）
DEFAULT_GOODS = {
    "tea": {"name": "茶", "buy": 8},
    "salt": {"name": "盐", "buy": 4},
    "cloth": {"name": "布", "buy": 2},
}

# 默认 5 天行情（行=商品，列=第 1..5 天卖出价）
DEFAULT_SCHEDULE = [
    [12, 10, 15, 12, 11],   # 茶：第 3 天茶会涨价
    [5, 7, 5, 6, 5],        # 盐：第 2 天雨天涨价
    [3, 3, 2, 4, 6],        # 布：第 5 天集市涨价
]


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class TradeService(Service):
    """经营服务（ctx.trade，可选插件）。"""

    name = "trade"
    inject = ("state", "engine", "io")

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.goods = self.config.get("goods") or DEFAULT_GOODS
        self.schedule = self.config.get("schedule") or DEFAULT_SCHEDULE
        self.ids = list(self.goods.keys())
        self.active: dict | None = None

    def setup(self) -> None:
        self.ctx.on("scene/mode", self._on_scene_mode)
        self.ctx.on("engine/command", self._on_command)
        self.ctx.on("scene/rendered", self._on_scene_rendered)
        self.ctx.on("scene/leave", self._on_scene_leave)
        self.ctx.info("trade", f"loaded {len(self.ids)} goods over {len(self.schedule[0]) if self.schedule else 0} days")

    # ------------------------------------------------------------ 事件钩子

    def _on_scene_mode(self, scene_id, scene, mode):
        if mode != "trade":
            return None
        self.begin(scene.get("trade") or {})
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

    # ------------------------------------------------------------ 开市与行情

    def begin(self, trade: dict) -> None:
        state = self.ctx.state
        if state.get("tradeDay") is None:
            state.set("tradeDay", 1)
            # 开市基线：进铺资金，收市结算净赚
            state.set("tradeBaseGold", state.get("gold") or 0)
        if state.get("stock") is None:
            state.set("stock", {})
        for gid in self.ids:
            if state.get(f"stock.{gid}") is None:
                state.set(f"stock.{gid}", 0)
        # 场所名参数化：场景 trade.name 声明，缺省 config.place，再缺省「东市」
        self.active = {
            "days": trade.get("days") or 5,
            "onEnd": trade.get("onEnd"),
            "name": trade.get("name") or self.config.get("place") or "东市",
        }

    @property
    def day(self) -> int:
        return self.ctx.state.get("tradeDay") or 1

    def price_of(self, gid: str, day: int | None = None):
        day = day if day is not None else self.day
        if gid not in self.ids:
            return None
        row = self.schedule[self.ids.index(gid)] or []
        return row[day - 1] if 0 < day <= len(row) else 0

    # ------------------------------------------------------------ 命令

    def handle(self, line: str):
        parts = line.strip().lower().split()
        cmd = parts[0] if parts else ""
        args = parts[1:]
        if cmd in ("buy", "b", "进货"):
            return self.do_buy(args)
        if cmd in ("sell", "s", "出货"):
            return self.do_sell(args)
        if cmd in ("next", "n", "过", "下一天"):
            return self.next_day()
        if cmd in ("info", "i", "行情"):
            self.render()
            return {"type": "noop"}
        if cmd in ("help", "?"):
            self.ctx.io.print("  经营指令: buy <商品> [数量] 进货 | sell <商品> [数量] 出货（默认全部）| next 下一天 | info 行情 | quit 退出")
            self.render()
            return {"type": "noop"}
        if is_global_command(line):
            return None
        self.ctx.io.print(f"  经营中不可用：{line.strip() or '(空)'}（指令: buy 进货 | sell 出货 | next 下一天 | info 行情 | help 帮助）")
        self.render()
        return {"type": "noop"}

    def do_buy(self, args: list[str]):
        gid = self.normalize_id(args[0] if args else None)
        if not gid:
            return self.bad_goods(args[0] if args else None)
        n = self.parse_count(args[1] if len(args) > 1 else None, 1)
        if n <= 0:
            self.ctx.io.print("  数量至少为 1。")
            self.render()
            return {"type": "noop"}
        goods = self.goods[gid]
        cost = goods["buy"] * n
        gold = self.ctx.state.get("gold") or 0
        # 防御纵深：非有限数一律不进状态机（gold < NaN 恒为 false，拦不住）
        if not _finite(cost) or not _finite(gold):
            self.ctx.io.print("  金额异常，交易已取消（未扣款）。")
            self.render()
            return {"type": "noop"}
        if gold < cost:
            self.ctx.io.print(f"  金币不够：{goods['name']} 进价 {goods['buy']}，{n} 件需 {cost} 金，你只有 {gold} 金。")
            self.render()
            return {"type": "noop"}
        self.ctx.state.apply({"gold": -cost, f"stock.{gid}": +n})
        self.ctx.io.print(f"  进货：{goods['name']} ×{n}（-{cost} 金），库存 {self.ctx.state.get(f'stock.{gid}')}。")
        self.render()
        return {"type": "noop"}

    def do_sell(self, args: list[str]):
        gid = self.normalize_id(args[0] if args else None)
        if not gid:
            return self.bad_goods(args[0] if args else None)
        goods = self.goods[gid]
        stock = self.ctx.state.get(f"stock.{gid}") or 0
        if stock <= 0:
            self.ctx.io.print(f"  没有库存：{goods['name']} 一件都没有，先 buy 进货吧。")
            self.render()
            return {"type": "noop"}
        n = self.parse_count(args[1] if len(args) > 1 else None, stock)
        if n <= 0:  # 负数数量会变成「反向交易」
            self.ctx.io.print("  数量至少为 1。")
            self.render()
            return {"type": "noop"}
        if n > stock:
            self.ctx.io.print(f"  库存不够：{goods['name']} 只有 {stock} 件。")
            self.render()
            return {"type": "noop"}
        price = self.price_of(gid)
        earn = (price or 0) * n
        if not _finite(price) or not _finite(earn):
            self.ctx.io.print("  金额异常，出货已取消。")
            self.render()
            return {"type": "noop"}
        self.ctx.state.apply({"gold": +earn, f"stock.{gid}": -n})
        self.ctx.io.print(f"  出货：{goods['name']} ×{n} @ {price} 金（+{earn} 金），库存 {self.ctx.state.get(f'stock.{gid}')}。")
        self.render()
        return {"type": "noop"}

    def next_day(self):
        days, on_end = self.active["days"], self.active["onEnd"]
        current = self.day
        state = self.ctx.state
        if current >= days:
            base = state.get("tradeBaseGold") or 0
            gold = state.get("gold") or 0
            state.set("tradeProfit", gold - base)
            self.ctx.io.print(f"  第 {days} 天收市。你带着 {gold} 金走出{self.active['name']}，比进铺时多出 {gold - base} 金。")
            state.set("tradeDay", None)
            self.active = None
            if on_end:
                self.ctx.engine.goto(on_end)
                return {"type": "scene", "id": on_end}
            return {"type": "noop"}
        state.set("tradeDay", current + 1)
        self.ctx.io.print(f"  第 {self.day} 天，开市。")
        self.render()
        return {"type": "noop"}

    # ------------------------------------------------------------ 工具与渲染

    def normalize_id(self, value):
        """商品 ID 归一：支持中文名 / 前缀缩写。"""
        if not value:
            return None
        if value in self.goods:
            return value
        for gid, g in self.goods.items():
            if g.get("name") == value:
                return gid
        for gid in self.ids:
            if gid.startswith(value):
                return gid
        return None

    @staticmethod
    def parse_count(text, fallback: int) -> int:
        if text is None:
            return fallback
        try:
            n = float(text)
        except (TypeError, ValueError):
            return fallback
        return math.floor(n) if math.isfinite(n) else fallback

    def bad_goods(self, value):
        listing = " / ".join(f"{self.goods[gid]['name']}({gid})" for gid in self.ids)
        self.ctx.io.print(f"  没有这种货：{value or '(空)'}。可交易：{listing}")
        self.render()
        return {"type": "noop"}

    def render(self) -> None:
        if not self.active:
            return
        state = self.ctx.state
        self.ctx.io.blank()
        self.ctx.io.print(f"  ── {self.active['name']} · 第 {self.day} 天 ──")
        self.ctx.io.print("  今日行情（卖出价）：")
        for gid in self.ids:
            g = self.goods[gid]
            price = self.price_of(gid)
            stock = state.get(f"stock.{gid}") or 0
            self.ctx.io.print(
                f"    {str(g['name']).ljust(4, '　')} 进 {str(g['buy']).rjust(2)} 金"
                f" | 今日卖 {str(price).rjust(2)} 金{self.trend_text(gid)} | 库存 {stock}"
            )
        self.ctx.io.blank()
        self.ctx.io.print(f"  资金 {state.get('gold')} 金")
        self.ctx.io.blank()
        self.ctx.io.print("  指令: buy <商品> [数量] 进货 | sell <商品> [数量] 出货 | next 下一天 | info 行情")
        self.ctx.io.blank()

    def trend_text(self, gid: str) -> str:
        """明天涨跌提示（对比明日价），最后一天显示「最后一天」。"""
        if self.day >= self.active["days"]:
            return "（最后一天）"
        today = self.price_of(gid, self.day)
        tomorrow = self.price_of(gid, self.day + 1)
        if (tomorrow or 0) > (today or 0):
            return " ↑ 明日看涨"
        if (tomorrow or 0) < (today or 0):
            return " ↓ 明日看跌"
        return " → 明日持平"
