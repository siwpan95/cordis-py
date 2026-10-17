"""玩家状态服务：属性 / 背包 / 标志位 + 效果执行 + 条件求值。

移植自 dse-core(Node) plugins/state.js。

效果语义（一个普通 dict）::

    {hp: -5}               数值   → 加减（仅当原值也是数值）
    {'name': '勇者'}        字符串 → 赋值
    {'flags.metKing': True} 点路径 → 深层赋值
    {'items.sword': +1}    点路径 + 数值 → 深层计数

条件语义：字符串表达式，AST 白名单求值（safety.py），异常兜底为 False。
注意 Python 的 bool 是 int 的子类，布尔值按「赋值」处理（与 Node 的
typeof 判别一致），不当成数值加减。
"""

from __future__ import annotations

import copy
import re

from ..runtime import Service
from ..safety import evaluate

_UNSAFE_KEYS = {"__proto__", "constructor", "prototype"}
_INTERP_RE = re.compile(r"\{([\w.]+)\}")


def _has_unsafe_key(path) -> bool:
    return any(key in _UNSAFE_KEYS for key in str(path).split("."))


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class StateService(Service):
    """玩家状态服务（ctx.state）。"""

    name = "state"
    inject = ()

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.data = copy.deepcopy(self.config.get("initial") or {})

    # ------------------------------------------------------------ 读写

    def get(self, path):
        """读取点路径，如 'items.sword'；缺失或危险路径返回 None。"""
        if _has_unsafe_key(path):
            return None
        obj = self.data
        for key in str(path).split("."):
            if not isinstance(obj, dict) or key not in obj:
                return None
            obj = obj[key]
        return obj

    def set(self, path, value) -> bool:
        """写入点路径（自动创建中间对象）；危险路径被拒绝并返回 False。"""
        if _has_unsafe_key(path):
            self.ctx.warn("state", f"拒绝写入危险路径（原型污染防护）: {path}")
            return False
        keys = str(path).split(".")
        obj = self.data
        for key in keys[:-1]:
            child = obj.get(key)
            if not isinstance(child, dict):
                child = {}
                obj[key] = child
            obj = child
        obj[keys[-1]] = value
        return True

    # ------------------------------------------------------------ 效果与条件

    def apply(self, effects) -> list[dict]:
        """执行一个效果对象，返回变更记录 [{path, from, to}]。"""
        changes: list[dict] = []
        if not effects:
            return changes
        for path, value in effects.items():
            current = self.get(path)
            if _is_number(value) and _is_number(current):
                to = current + value
            elif _is_number(value) and current is None:
                to = value
            else:
                to = value
            if not self.set(path, to):
                continue  # 被原型污染防护拒绝
            changes.append({"path": path, "from": current, "to": to})
        return changes

    def check(self, expr, extra: dict | None = None) -> bool:
        """求值条件表达式；无条件时恒真；异常按 False 处理并告警。"""
        if expr is None or expr == "":
            return True
        scope = dict(self.data)
        if extra:
            scope.update(extra)
        try:
            return bool(evaluate(expr, scope))
        except Exception as exc:  # noqa: BLE001 — 与 Node 版一致：异常兜底 False
            self.ctx.warn("state", f'条件求值失败 "{expr}": {exc}')
            return False

    def interpolate(self, text) -> str:
        """用状态值插值文本：'你好，{name}！'（缺失保留原样）。"""

        def replace(match: re.Match) -> str:
            value = self.get(match.group(1))
            return match.group(0) if value is None else str(value)

        return _INTERP_RE.sub(replace, str(text))

    # ------------------------------------------------------------ 重置与存档

    def reset(self, keep: list[str] | None = None) -> None:
        """重置状态为 initial 快照。

        keep：点路径前缀数组。重置后旧状态中命中前缀的子树被回填（递归合并），
        用于时间循环的「知识跨轮保留」（@loop: 语义）；缺省 = 全量重置。
        """
        keep = keep or []
        old = self.data
        self.data = copy.deepcopy(self.config.get("initial") or {})
        if not keep:
            return
        kept: list[tuple[str, object]] = []

        def collect(obj: dict, base: str = "") -> None:
            for key, value in obj.items():
                path = f"{base}.{key}" if base else key
                if any(path == p or path.startswith(p + ".") for p in keep):
                    kept.append((path, value))
                elif isinstance(value, dict):
                    collect(value, path)

        collect(old)
        for path, value in kept:
            self.set(path, copy.deepcopy(value))

    def snapshot(self) -> dict:
        """深层快照（存档用）。"""
        return copy.deepcopy(self.data)

    def restore(self, data: dict) -> None:
        """从快照恢复（读档用）。"""
        self.data = copy.deepcopy(data)
