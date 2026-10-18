"""引擎 SDK —— 编程式入口（宿主程序 / 测试 / 工具链用）。

移植自 dse-core(Node) sdk/index.js。SDK 不改变引擎行为，只是把装配 /
字典 / 图分析 / 注册表收成一个门面::

    from dse_core import create_engine, play, inspect_project

    ctx = create_engine(root="./my-game")   # 装配插件，不进入主循环
    ctx.engine.run()                        # 需要时自行驱动
    ctx.state.get("gold")

    play(root="./my-game")                  # 装配并跑完整局（CLI 用）
    inspect_project("./my-game")            # 只读体检（不启动引擎）
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

from . import graph, loader, manifest, modes
from .loader import load_project
from .plugins.achievements import AchievementsService
from .plugins.combat import CombatService
from .plugins.console_io import ConsoleIO
from .plugins.engine import EngineService
from .plugins.i18n import I18nService
from .plugins.save import SaveService
from .plugins.save_migrate import SaveMigrateService
from .plugins.scenes import SceneService
from .plugins.state import StateService
from .runtime import Context, Service

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "analyze",
    "create_engine",
    "inspect_project",
    "load_dict",
    "load_packs",
    "load_project",
    "play",
    "scene_chars",
    "Context",
    "Service",
    "graph",
    "loader",
    "manifest",
    "modes",
]

# 内置插件表：dse.yml 里写 id 即可；第三方插件写「模块.类名」全路径
# 内核层：scenes / state / io / engine
# 能力层：combat（P1 参考实现）
# 系统层：save / save-migrate / achievements / i18n（P2）
_BUILTIN_PLUGINS = {
    "scenes": SceneService,
    "state": StateService,
    "io": ConsoleIO,
    "engine": EngineService,
    "combat": CombatService,
    "save": SaveService,
    "save-migrate": SaveMigrateService,
    "achievements": AchievementsService,
    "i18n": I18nService,
}


def engine_root() -> Path:
    """引擎自带示例工程目录（随包发布：dse.yml + content/，pip 安装后即可玩）。"""
    return Path(__file__).resolve().parent / "example"


def _resolve_plugin(name: str) -> type[Service]:
    if name in _BUILTIN_PLUGINS:
        return _BUILTIN_PLUGINS[name]
    if "." in name:
        module_path, _, cls_name = name.rpartition(".")
        module = importlib.import_module(module_path)
        cls = getattr(module, cls_name)
        if not (isinstance(cls, type) and issubclass(cls, Service)):
            raise TypeError(f"{name} 不是 dse_core.runtime.Service 的子类")
        return cls
    raise ValueError(f"未知插件: {name}（内置: {sorted(_BUILTIN_PLUGINS)}；第三方用「模块.类名」形式）")


def create_engine(root: str | Path | None = None, *, entry: str | None = None,
                  quiet: bool = True) -> Context:
    """装配引擎（加载 dse.yml 声明的全部插件并 setup），不进入主循环。"""
    root = Path(root) if root else engine_root()
    if entry:
        os.environ["DSE_ENTRY"] = str(entry)
    ctx = Context(root=root, quiet=quiet)
    project = loader.load_yaml(root / "dse.yml")
    if not isinstance(project, list):
        raise ValueError(f"{root / 'dse.yml'} 必须是插件条目列表")
    for item in project:
        if not isinstance(item, dict) or not item.get("id"):
            raise ValueError(f"dse.yml 插件条目缺少 id: {item!r}")
        cls = _resolve_plugin(item.get("name") or item["id"])
        ctx.plugin(cls, item.get("config"))
    ctx.start()
    return ctx


def play(root: str | Path | None = None, *, entry: str | None = None,
         quiet: bool = True) -> int:
    """装配并跑完整局（阻塞到退出/结局），返回进程退出码。"""
    ctx = create_engine(root, entry=entry, quiet=quiet)
    engine = ctx.services["engine"]
    engine.start()
    return engine.exit_code


def load_dict(root: str | Path | None = None) -> dict:
    """离线加载场景字典（CLI 只读命令用，不进主循环、不占 stdin）。"""
    root = Path(root) if root else engine_root()
    project = load_project(root)
    return {
        "root": root,
        "dict": project.dict,
        "ids": project.ids,
        "packFiles": project.pack_files,
        "entry": project.entry,
    }


def load_packs(root: str | Path | None = None) -> list[dict]:
    """列出全部内容包的规范化 manifest（dse packs 用，P2 完整 CLI）。"""
    root = Path(root) if root else engine_root()
    return load_project(root).manifests


def inspect_project(root: str | Path | None = None) -> dict:
    """只读地分析一个内容项目（不启动引擎、不占 stdin）。"""
    root = Path(root) if root else engine_root()
    project = load_project(root)
    report = graph.analyze(project.dict, project.entry)
    return {
        "root": str(root),
        "entry": project.entry,
        "packFiles": project.pack_files,
        "packs": project.manifests,
        "scenes": len(project.ids),
        "endings": len(report["endings"]),
        "endingsReachable": len(report["endingsReachable"]),
        "unreachable": report["unreachable"],
        "dangling": report["dangling"],
    }


# 与 Node 版 SDK 同名的导出
analyze = graph.analyze
scene_chars = loader.scene_chars
