"""dse-core · 字典场景引擎（Python 版）—— 场景即字典，能力即插件。

快速上手::

    from dse_core import create_engine, play, inspect_project

    play(root="./my-game")                  # 装配并跑完整局
    ctx = create_engine(root="./my-game")   # 只装配，自行驱动主循环
    inspect_project("./my-game")            # 只读体检

Node/Cordis 版（姊妹仓库 dse-core）的移植；内容包为 YAML 数据文件，
条件表达式走 AST 白名单求值（dse_core.safety）。
"""

from .runtime import Context, Service
from .sdk import (
    __version__,
    analyze,
    create_engine,
    inspect_project,
    load_dict,
    load_packs,
    load_project,
    play,
    scene_chars,
)

__all__ = [
    "__version__",
    "Context",
    "Service",
    "analyze",
    "create_engine",
    "inspect_project",
    "load_dict",
    "load_packs",
    "load_project",
    "play",
    "scene_chars",
]
