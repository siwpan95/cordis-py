"""插件运行时 —— Cordis 的 Python 原生替代。

Node 版靠 Cordis 4.0 提供 DI / Context / 生命周期；Python 生态里显式注册表
比魔法 DI 更地道，故本模块以约 300 行实现同等能力：

- :class:`Service` —— 插件基类。``inject`` 声明依赖的服务名；``setup()`` /
  ``dispose()`` 生命周期。``static inject`` → 类属性 ``inject``。
- :class:`Context` —— 服务容器 + 配置 + 事件。启动时按 inject 依赖拓扑排序
  后依次 setup；循环依赖 / 未知依赖直接报错，不静默。

事件协议（与 Node 版 engine.js 对齐）：

- ``emit(event, *args)``            全部监听器，无返回值
- ``bail(event, *args)``            逆注册序，首个非 None/False 返回即停
                                    （scene/mode 的 mode 委托用；False = 不接管）
- ``dispatch_command(line, choices)`` 逆注册序拦截引擎命令，返回 None 表示放行，
                                    全部放行后由引擎回落默认命令
- ``pipeline(event, value, *args)`` 顺序变换文本（text/render 插值装饰用）

便捷访问：``ctx.state`` / ``ctx.io`` / ``ctx.engine`` 直接取服务（与 Node 版
``ctx.state`` 写法一致），未知服务名抛 AttributeError。
"""

from __future__ import annotations

import sys
from pathlib import Path


class Service:
    """插件基类。子类声明 ``name`` 与 ``inject``，按需实现 setup()/dispose()。"""

    name: str = ""
    inject: tuple[str, ...] = ()

    def __init__(self, ctx: "Context", config: dict | None):
        self.ctx = ctx
        self.config = config or {}

    def setup(self) -> None:
        """依赖全部就绪后调用一次。"""

    def dispose(self) -> None:
        """引擎收尾时调用（逆序）。"""


class Context:
    """服务容器 + 配置 + 事件总线。"""

    def __init__(self, root: str | Path, quiet: bool = True):
        self.root = Path(root)
        self.quiet = quiet
        self.services: dict[str, Service] = {}
        self._plugins: list[tuple[type[Service], dict]] = []
        self._listeners: dict[str, list] = {}
        self._setups: list[Service] = []

    # ------------------------------------------------------------ 注册与启动

    def plugin(self, cls: type[Service], config: dict | None = None) -> "Context":
        """登记一个插件（setup 前的声明阶段）。"""
        if not cls.name:
            raise ValueError(f"插件 {cls.__name__} 未声明 name")
        self._plugins.append((cls, config or {}))
        return self

    def start(self) -> "Context":
        """按 inject 依赖拓扑排序，依次实例化并 setup。"""
        declared = {cls.name: (cls, cfg) for cls, cfg in self._plugins}
        done: set[str] = set()
        while len(done) < len(declared):
            ready = [
                name for name in declared
                if name not in done and all(dep in done for dep in declared[name][0].inject)
            ]
            if not ready:
                remaining = sorted(set(declared) - done)
                raise RuntimeError(f"插件依赖存在循环或引用了未注册的服务: {remaining}")
            for name in ready:
                cls, cfg = declared[name]
                instance = cls(self, cfg)
                self.services[name] = instance
                self._setups.append(instance)
                instance.setup()
                done.add(name)
        return self

    def dispose(self) -> None:
        """逆序 dispose 全部插件（引擎 stop 时调用）。"""
        for instance in reversed(self._setups):
            try:
                instance.dispose()
            except Exception as exc:  # noqa: BLE001 — 清理失败不阻断退出流程
                self.warn(instance.name, f"dispose 失败: {exc}")
        self._setups.clear()
        self.services.clear()

    # ------------------------------------------------------------ 事件

    def on(self, event: str, handler) -> None:
        self._listeners.setdefault(event, []).append(handler)

    def emit(self, event: str, *args) -> None:
        for handler in list(self._listeners.get(event, [])):
            handler(*args)

    def bail(self, event: str, *args):
        """逆注册序，首个非 None/False 返回即停（scene/mode 委托）。"""
        for handler in reversed(self._listeners.get(event, [])):
            result = handler(*args)
            if result is not None and result is not False:
                return result
        return None

    def pipeline(self, event: str, value, *args):
        """顺序变换（text/render）：每个监听器接收当前值并返回新值。"""
        for handler in self._listeners.get(event, []):
            value = handler(value, *args)
        return value

    def dispatch_command(self, line: str, choices: list):
        """引擎命令分发：逆注册序拦截；返回 None = 无人处理，回落默认命令。"""
        for handler in reversed(self._listeners.get("engine/command", [])):
            result = handler(line, choices)
            if result is not None:
                return result
        return None

    # ------------------------------------------------------------ 日志

    def log(self, level: str, service: str, message: str) -> None:
        if self.quiet and level == "info":
            return
        print(f"[{level}] [{service}] {message}", file=sys.stderr)

    def info(self, service: str, message: str) -> None:
        self.log("info", service, message)

    def warn(self, service: str, message: str) -> None:
        self.log("warn", service, message)

    def error(self, service: str, message: str) -> None:
        self.log("error", service, message)

    # ------------------------------------------------------------ 便捷访问

    def __getattr__(self, name: str) -> Service:
        # ctx.state / ctx.io / ctx.engine —— 与 Node 版一致的写法
        try:
            return self.__dict__["services"][name]
        except KeyError:
            raise AttributeError(name) from None
