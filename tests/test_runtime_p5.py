"""P5 内核层测试：effect 原语 / fiber 状态机 / 事件五模式 / 配置校验。"""

import pytest

from dse_core.runtime import Context, Service


class Recorder(Service):
    name = "recorder"
    log: list = []

    def setup(self):
        self.effect(lambda: self.log.append("disposed") or (lambda: self.log.append("rolled-back"))())


def make_ctx(*plugins) -> Context:
    ctx = Context(root=".", quiet=True)
    for cls, cfg in plugins:
        ctx.plugin(cls, cfg)
    return ctx


# ------------------------------------------------------------ effect 原语

def test_effect_disposer_rolls_back_on_dispose():
    Recorder.log = []

    class Plugin(Service):
        name = "p-effect"

        def setup(self):
            self.effect(lambda: lambda: Recorder.log.append("cleanup-a"))
            self.effect(lambda: lambda: Recorder.log.append("cleanup-b"))

    ctx = make_ctx((Plugin, None)).start()
    assert Recorder.log == []
    ctx.dispose()
    assert Recorder.log == ["cleanup-b", "cleanup-a"]  # 逆序回滚


def test_effect_non_callable_return_ignored():
    class Plugin(Service):
        name = "p-effect-none"

        def setup(self):
            self.effect(lambda: 42)  # 非 callable 返回不登记

    ctx = make_ctx((Plugin, None)).start()
    ctx.dispose()  # 不炸即通过


def test_failing_disposer_does_not_block_others():
    Recorder.log = []

    class Plugin(Service):
        name = "p-effect-fail"

        def setup(self):
            self.effect(lambda: lambda: Recorder.log.append("ok"))
            def boom():
                raise RuntimeError("boom")
            self.effect(lambda: boom)

    ctx = make_ctx((Plugin, None)).start()
    ctx.dispose()
    assert Recorder.log == ["ok"]  # 炸的那个 warn 后继续


def test_service_on_auto_removed_on_dispose():
    class Plugin(Service):
        name = "p-on"

        def setup(self):
            self.on("evt", lambda: None)

    ctx = make_ctx((Plugin, None)).start()
    assert len(ctx._listeners["evt"]) == 1
    ctx.dispose()
    assert ctx._listeners["evt"] == []


def test_ctx_on_returns_off():
    ctx = make_ctx()
    off = ctx.on("evt", lambda: None)
    assert len(ctx._listeners["evt"]) == 1
    off()
    assert ctx._listeners["evt"] == []
    off()  # 幂等


# ------------------------------------------------------------ fiber 状态机

def test_fiber_states_happy_path():
    class Plugin(Service):
        name = "p-fiber"

    ctx = make_ctx((Plugin, None))
    ctx.start()
    assert ctx.fibers["p-fiber"]["state"] == "ACTIVE"
    assert ctx.fibers["p-fiber"]["inject"] == []
    assert ctx.fibers["p-fiber"]["error"] is None
    ctx.dispose()
    assert ctx.fibers["p-fiber"]["state"] == "DISPOSED"


def test_fiber_failed_on_setup_error():
    class Bad(Service):
        name = "p-bad"

        def setup(self):
            raise RuntimeError("init boom")

    ctx = make_ctx((Bad, None))
    with pytest.raises(RuntimeError, match="init boom"):
        ctx.start()
    fiber = ctx.fibers["p-bad"]
    assert fiber["state"] == "FAILED"
    assert "init boom" in fiber["error"]


def test_fiber_pending_then_active_with_dependency():
    order = []

    class Base(Service):
        name = "p-base"

        def setup(self):
            order.append("base")

    class Dep(Service):
        name = "p-dep"
        inject = ("p-base",)

        def setup(self):
            order.append("dep")

    ctx = make_ctx((Dep, None), (Base, None))  # 声明顺序颠倒，拓扑应摆正
    ctx.start()
    assert order == ["base", "dep"]
    assert ctx.fibers["p-dep"]["inject"] == ["p-base"]


def test_inspect_snapshot():
    class Plugin(Service):
        name = "p-inspect"
        inject = ()

    ctx = make_ctx((Plugin, None)).start()
    snap = ctx.inspect()
    assert snap == [{"name": "p-inspect", "state": "ACTIVE", "inject": [], "error": None}]
    ctx.dispose()


# ------------------------------------------------------------ 事件五模式

def test_parallel_collects_and_tolerates_failure():
    ctx = make_ctx()
    ctx.on("evt", lambda x: x + 1)

    def boom(x):
        raise ValueError("nope")

    ctx.on("evt", boom)
    ctx.on("evt", lambda x: x * 2)
    assert ctx.parallel("evt", 5) == [6, None, 10]


def test_serial_stops_on_error():
    ctx = make_ctx()
    ctx.on("evt", lambda: "a")

    def boom():
        raise ValueError("stop here")

    ctx.on("evt", boom)
    ctx.on("evt", lambda: "never")
    with pytest.raises(ValueError, match="stop here"):
        ctx.serial("evt")


def test_serial_collects_in_order():
    ctx = make_ctx()
    ctx.on("evt", lambda x: x + "1")
    ctx.on("evt", lambda x: x + "2")
    assert ctx.serial("evt", "x") == ["x1", "x2"]


# ------------------------------------------------------------ 配置校验

def test_config_schema_required_missing():
    class Plugin(Service):
        name = "p-cfg"
        config_schema = {"required": ["token"]}

    ctx = make_ctx((Plugin, {}))
    with pytest.raises(ValueError, match="缺少必需配置项: token"):
        ctx.start()


def test_config_schema_type_mismatch():
    class Plugin(Service):
        name = "p-cfg2"
        config_schema = {"properties": {"port": {"type": "int"}}}

    ctx = make_ctx((Plugin, {"port": "8080"}))
    with pytest.raises(ValueError, match="类型应为 int"):
        ctx.start()


def test_config_schema_enum():
    class Plugin(Service):
        name = "p-cfg3"
        config_schema = {"properties": {"level": {"enum": ["a", "b"]}}}

    ctx = make_ctx((Plugin, {"level": "z"}))
    with pytest.raises(ValueError, match="取值须为"):
        ctx.start()


def test_config_schema_default_filled():
    class Plugin(Service):
        name = "p-cfg4"
        config_schema = {"properties": {"retries": {"type": "int", "default": 3}}}

    ctx = make_ctx((Plugin, {})).start()
    assert ctx.services["p-cfg4"].config["retries"] == 3
    ctx.dispose()


def test_config_schema_pass_when_valid():
    class Plugin(Service):
        name = "p-cfg5"
        config_schema = {
            "required": ["mode"],
            "properties": {"mode": {"enum": ["x"]}, "n": {"type": "int", "default": 1}},
        }

    ctx = make_ctx((Plugin, {"mode": "x"})).start()
    assert ctx.services["p-cfg5"].config == {"mode": "x", "n": 1}
    ctx.dispose()
