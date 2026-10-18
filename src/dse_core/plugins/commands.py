"""全局命令名单 —— 能力插件（combat/trade/diary/dialogue）接管输入时，
这些命令放行给后续监听器（save/achievements/i18n/引擎默认），其余输入
明确拒绝（不静默吞掉）。

与 Node 版 plugins/lib/global-commands.js 的 isGlobalCommand 对应。
"""

from __future__ import annotations

GLOBAL_COMMANDS = frozenset({
    "help", "?",
    "stats", "status",
    "quit", "exit",
    "save", "存", "load", "读", "slots", "档",
    "achievements", "成就",
    "lang", "语言",
})


def is_global_command(line: str) -> bool:
    """整串命令（首词）是否全局命令。"""
    parts = str(line).strip().split()
    return bool(parts) and parts[0].lower() in GLOBAL_COMMANDS
