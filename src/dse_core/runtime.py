"""插件运行时 —— Cordis 的 Python 原生替代。

Node 版靠 Cordis 4.0 提供 DI / Context / 生命周期；Python 生态里显式注册表
比魔法 DI 更地道，故本模块以约 300 行实现同等能力：

- :class:`Service` —— 插件基类。``inject`` 声明依赖的服务名；``setup()`` /
  ``dispose()`` 生命周期。``static inject`` → 类属性 ``inject``。
- :class:`Context` —— 服务容器 + 配置 + 事件。启动时按 inject 依赖拓扑排序
  后依次 setup；循环依赖 / 未知依赖直接报错，不静默。

事件协议（与 Node 版 engine.js 对齐，P5 补齐 Cordis 五分发模式）：

- ``emit(event, *args)``            全部监听器，无返回值（观察）
- ``parallel(event, *args)``        并行扇出：容错收集全部结果，单个失败 warn 后继续
- ``serial(event, *args)``          串行链：收集结果，任一监听器抛错即停并上抛
- ``bail(event, *args)``            逆注册序，首个非 None/False 返回即停
                                    （scene/mode 的 mode 委托用；False = 不接管）
- ``pipeline(event, value, *args)`` 顺序变换文本（text/render 插值装饰用）；
                                    即 Cordis waterfall —— 返回值链而非 next 回调，
                                    天然免疫「重复调 next」类 bug
- ``dispatch_command(line, choices)`` 逆注册序拦截引擎命令，返回 None 表示放行，
                                    全部放行后由引擎回落默认命令

可逆副作用（Cordis ``ctx.effect`` 的 Python 原生对应物）：

- 插件内 ``self.effect(fn)`` —— 立即执行 ``fn``，其返回的 disposer 在本插件
  dispose 时自动逆序回滚。凡自己创建、运行时不管的资源，都包进 ``self.effect``。
- 插件内 ``self.on(event, handler)`` —— ``ctx.on`` 的 effect 版：监听器随本插件
  dispose 自动摘除（热重载 / 重挂不再累积残留监听器）。

fiber 生命周期（对齐 Cordis 4.0 状态机）：

- 每个插件实例维护 fiber 状态：PENDING → LOADING → ACTIVE / FAILED，
  dispose 时 UNLOADING → DISPOSED。``ctx.inspect()`` 返回全部 fiber 快照，
  「插件加载了却没反应」时先看它是不是蹲在 PENDING / FAILED。

配置校验：插件可声明类属性 ``config_schema``（``required`` / ``properties``
子集：type / enum / default），start 时校验，缺键或型错响亮报错并填充默认值。

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
    config_schema: dict = {}  # {"required": [...], "properties": {k: {"type"/"enum"/"default"}}}

    def __init__(self, ctx: "Context", config: dict | None):
        self.ctx = ctx
        self.config = config or {}
        self._disposers: list = []

    def setup(self) -> None:
        """依赖全部就绪后调用一次。"""

    def dispose(self) -> None:
        """引擎收尾时调用（逆序）。disposer 栈由 Context 统一回滚，无需子类操心。"""

    # ------------------------------------------------------------ 可逆副作用

    def effect(self, fn):
        """Cordis ``ctx.effect`` 对应物：立即执行 fn，返回的 disposer 随本插件
        dispose 自动逆序调用。返回 fn 的返回值（通常是 disposer 本身）。"""
        disposer = fn()
        if callable(disposer):
            self._disposers.append(disposer)
        return disposer

    def on(self, event: str, handler):
        """``ctx.on`` 的 effect 版：监听器随本插件 dispose 自动摘除。"""
        return self.ctx.on(event, handler, owner=self)

    def _run_disposers(self) -> None:
        """逆序回滚全部 disposer；单个失败 warn 后继续（清理不阻断退出）。"""
        while self._disposers:
            disposer = self._disposers.pop()
            try:
                disposer()
            except Exception as exc:  # noqa: BLE001
                self.ctx.warn(self.name, f"disposer 回滚失败: {exc}")


class Context:
    """服务容器 + 配置 + 事件总线。"""

    def __init__(self, root: str | Path, quiet: bool = True):
        self.root = Path(root)
        self.quiet = quiet
        self.services: dict[str, Service] = {}
        self._plugins: list[tuple[type[Service], dict]] = []
        self._listeners: dict[str, list] = {}
        self._setups: list[Service] = []
        self.fibers: dict[str, dict] = {}  # name -> {"state", "inject", "error"}
        # P10 isolate：父上下文 + 本隔离域独立的服务名集合（None = 根域）
        self._parent: "Context | None" = None
        self._isolated: frozenset[str] = frozenset()
        self._children: list[Context] = []  # 隔离子域登记（inspect 聚合用）

    # ------------------------------------------------------------ 隔离域（P10）

    def isolate(self, *service_names: str) -> "Context":
        """创建一个服务隔离域（Cordis ``ctx.isolate`` 的 Python 原生对应物）。

        子上下文与父共享事件总线 / fiber 表 / 配置；列出的服务名在子域内
        独立注册（同名不同实例，互不干扰），未列出的服务沿父链解析。
        典型用途：测试隔离（每个用例独立 state）、多会话并存（共享 io、
        各自持有 scenes/state）。
        """
        child = Context(self.root, quiet=self.quiet)
        child._parent = self
        child._isolated = frozenset(service_names)
        self._bus._children.append(child)
        return child

    @property
    def _bus(self) -> "Context":
        # 事件总线所在域（隔离域委托到根域）
        ctx = self
        while ctx._parent is not None:
            ctx = ctx._parent
        return ctx

    def _resolve_service(self, name: str):
        """服务解析：本地命中优先；隔离名单内的服务不向上穿透（响亮报错）。"""
        if name in self.services:
            return self.services[name]
        if self._parent is not None and name not in self._isolated:
            return self._parent._resolve_service(name)
        raise AttributeError(name)

    def _has_service(self, name: str) -> bool:
        """服务是否已就绪（本域或父链；隔离名单内的不向上穿透）。"""
        try:
            self._resolve_service(name)
            return True
        except AttributeError:
            return False

    # ------------------------------------------------------------ 注册与启动

    def plugin(self, cls: type[Service], config: dict | None = None) -> "Context":
        """登记一个插件（setup 前的声明阶段）。"""
        if not cls.name:
            raise ValueError(f"插件 {cls.__name__} 未声明 name")
        self._plugins.append((cls, config or {}))
        return self

    def start(self) -> "Context":
        """按 inject 依赖拓扑排序，依次实例化并 setup（全程维护 fiber 状态）。"""
        declared = {cls.name: (cls, cfg) for cls, cfg in self._plugins}
        self.fibers = {
            name: {"state": "PENDING", "inject": list(cls.inject), "error": None}
            for name, (cls, _cfg) in declared.items()
        }
        done: set[str] = set()
        while len(done) < len(declared):
            ready = [
                name for name in declared
                if name not in done and all(
                    dep in done or (dep not in declared and self._has_service(dep))
                    for dep in declared[name][0].inject
                )
            ]
            if not ready:
                remaining = sorted(set(declared) - done)
                raise RuntimeError(f"插件依赖存在循环或引用了未注册的服务: {remaining}")
            for name in ready:
                cls, cfg = declared[name]
                fiber = self.fibers[name]
                fiber["state"] = "LOADING"
                try:
                    merged = self._validate_config(cls, cfg)
                    instance = cls(self, merged)
                    self.services[name] = instance
                    self._setups.append(instance)
                    instance.setup()
                except Exception as exc:
                    fiber["state"] = "FAILED"
                    fiber["error"] = f"{type(exc).__name__}: {exc}"
                    raise
                fiber["state"] = "ACTIVE"
                done.add(name)
        return self

    def dispose(self) -> None:
        """逆序 dispose 全部插件（引擎 stop 时调用），disposer 栈随之一并回滚。"""
        for instance in reversed(self._setups):
            fiber = self.fibers.get(instance.name)
            if fiber is not None:
                fiber["state"] = "UNLOADING"
            try:
                instance.dispose()
            except Exception as exc:  # noqa: BLE001 — 清理失败不阻断退出流程
                self.warn(instance.name, f"dispose 失败: {exc}")
            instance._run_disposers()
            if fiber is not None:
                fiber["state"] = "DISPOSED"
        self._setups.clear()
        self.services.clear()

    def inspect(self) -> list[dict]:
        """全部 fiber 的快照（name / state / inject / error），供巡检与 doctor。

        根域调用时递归聚合隔离子域的 fiber（子域条目标注 realm 深度）。
        """
        snap = [{"name": name, **fiber} for name, fiber in self.fibers.items()]
        for child in self._children:
            for entry in child.inspect():
                snap.append({**entry, "realm": entry.get("realm", 0) + 1})
        return snap

    # ------------------------------------------------------------ 配置校验

    @staticmethod
    def _validate_config(cls: type[Service], config: dict) -> dict:
        """按插件声明的 config_schema 校验配置；缺 required / 型错响亮报错，
        default 自动填充。schema 是 JSON Schema 的最小实用子集，零依赖。"""
        schema = cls.config_schema
        if not schema:
            return config
        merged = dict(config)
        props = schema.get("properties", {})
        for key, rule in props.items():
            if key not in merged and "default" in rule:
                merged[key] = rule["default"]
        for key in schema.get("required", []):
            if key not in merged:
                raise ValueError(f"插件 {cls.name} 缺少必需配置项: {key}")
        type_map = {
            "str": str, "int": int, "float": (int, float), "bool": bool,
            "list": list, "dict": dict,
        }
        for key, rule in props.items():
            if key not in merged:
                continue
            value = merged[key]
            if "type" in rule and not isinstance(value, type_map[rule["type"]]):
                raise ValueError(
                    f"插件 {cls.name} 配置项 {key} 类型应为 {rule['type']}，"
                    f"实际 {type(value).__name__}: {value!r}"
                )
            if "enum" in rule and value not in rule["enum"]:
                raise ValueError(
                    f"插件 {cls.name} 配置项 {key} 取值须为 {rule['enum']} 之一，"
                    f"实际: {value!r}"
                )
        return merged

    # ------------------------------------------------------------ 事件

    def on(self, event: str, handler, owner: Service | None = None):
        """注册监听器，返回 off 函数；指定 owner 时监听器随该插件 dispose 自动摘除。

        隔离域子上下文的事件总线共享根域（事件是全局的，服务才是隔离的）。
        """
        bus = self._bus
        bus._listeners.setdefault(event, []).append(handler)

        def off() -> None:
            handlers = bus._listeners.get(event, [])
            if handler in handlers:
                handlers.remove(handler)

        if owner is not None:
            owner._disposers.append(off)
        return off

    def emit(self, event: str, *args) -> None:
        for handler in list(self._bus._listeners.get(event, [])):
            handler(*args)

    def parallel(self, event: str, *args) -> list:
        """并行扇出：容错收集全部监听器结果，单个失败 warn 后继续。"""
        results = []
        for handler in list(self._bus._listeners.get(event, [])):
            try:
                results.append(handler(*args))
            except Exception as exc:  # noqa: BLE001 — 扇出语义：单个失败不拖垮全局
                self.warn("parallel", f"监听器 {handler!r} 失败: {exc}")
                results.append(None)
        return results

    def serial(self, event: str, *args) -> list:
        """串行链：按注册序收集结果，任一监听器抛错即停并上抛（中间件语义）。"""
        results = []
        for handler in list(self._bus._listeners.get(event, [])):
            results.append(handler(*args))
        return results

    def bail(self, event: str, *args):
        """逆注册序，首个非 None/False 返回即停（scene/mode 委托）。"""
        for handler in reversed(self._bus._listeners.get(event, [])):
            result = handler(*args)
            if result is not None and result is not False:
                return result
        return None

    def pipeline(self, event: str, value, *args):
        """顺序变换（text/render）：每个监听器接收当前值并返回新值。"""
        for handler in self._bus._listeners.get(event, []):
            value = handler(value, *args)
        return value

    def dispatch_command(self, line: str, choices: list):
        """引擎命令分发：逆注册序拦截；返回 None = 无人处理，回落默认命令。"""
        for handler in reversed(self._bus._listeners.get("engine/command", [])):
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
        # P10：经 _resolve_service 支持隔离域链式解析
        try:
            return self._resolve_service(name)
        except AttributeError:
            raise AttributeError(name) from None
