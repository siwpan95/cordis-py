"""模式注册表（scene.mode 的唯一真源）。

移植自 dse-core(Node) lib/modes.mjs。模式契约收敛为一张可注册的表：
引擎校验器、图遍历、CLI、文档都从这里读；能力插件注册自己接管的 mode
时同时声明流转边，引擎侧零改动。
"""

from __future__ import annotations

SPECIAL_GOTO = frozenset({"@restart", "@return"})
LOOP_PREFIX = "@loop:"


def is_special_goto(target) -> bool:
    """特殊跳转目标（引擎语义，非场景）：@restart / @return / @loop:<id>。

    @return：从 tunnels 隧道（goto: {call: x}）弹栈返回调用点。
    """
    return target in SPECIAL_GOTO or str(target).startswith(LOOP_PREFIX)


def resolve_goto(target) -> str:
    """解出 @loop:<id> 的真实目标；普通目标原样返回。"""
    raw = str(target if target is not None else "")
    if raw.startswith(LOOP_PREFIX):
        return raw[len(LOOP_PREFIX):]
    return raw


# 内置模式契约表：mode -> {edges, plugin, desc}
# edges = 该模式场景上「由插件控制流转」的跳转字段（参与悬空检查与可达性 BFS）
_MODE_REGISTRY: dict[str, dict] = {
    "normal": {"edges": [], "plugin": None, "desc": "引擎默认渲染：选项 + 结局判定"},
    "battle": {"edges": ["onWin", "onLose", "onFlee"], "plugin": "combat", "desc": "回合制战斗"},
    "trade": {"edges": ["onEnd"], "plugin": "trade", "desc": "经营/买卖（天数循环 + 行情）"},
    "diary": {"edges": ["onExit"], "plugin": "diary", "desc": "日记回溯（只读重读已走过的篇目）"},
    "dialogue": {"edges": ["onEnd"], "plugin": "dialogue", "desc": "对话/谈判（话题询问 + 注意点预算）"},
}


def register_mode(mode: str, spec: dict | None = None) -> dict:
    """注册一个自定义模式（能力插件在自己 setup 时调用）。"""
    spec = spec or {}
    prev = _MODE_REGISTRY.get(mode) or {"edges": [], "plugin": spec.get("plugin"), "desc": ""}
    entry = {
        "edges": spec.get("edges", prev["edges"]),
        "plugin": spec.get("plugin", prev["plugin"]),
        "desc": spec.get("desc", prev["desc"]),
    }
    _MODE_REGISTRY[mode] = entry
    return entry


def mode_edges(mode) -> list[str]:
    """模式的流转边字段名（未注册模式返回空数组）。"""
    return list(_MODE_REGISTRY.get(mode, {}).get("edges", []))


def is_known_mode(mode) -> bool:
    """是否已知模式（未知模式会被校验器判为错误：多半是拼写错误）。"""
    return (mode or "normal") in _MODE_REGISTRY


def mode_names() -> list[str]:
    """全部已知模式名。"""
    return list(_MODE_REGISTRY.keys())


def mode_edge_table() -> dict[str, list[str]]:
    """兼容旧调用方：返回 {mode: [edges]} 形状的普通对象。"""
    return {m: list(s["edges"]) for m, s in _MODE_REGISTRY.items() if s["edges"]}


# 与 Node 版 MODE_REGISTRY 同名的内部表（可变；优先用上面的函数）
MODE_REGISTRY = _MODE_REGISTRY
