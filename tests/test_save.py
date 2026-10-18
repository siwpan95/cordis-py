"""save / save-migrate 插件测试。"""

import json

import pytest

from dse_core.plugins.save import SaveService
from dse_core.plugins.save_migrate import SaveMigrateService
from dse_core.runtime import Context


def _ctx(root) -> Context:
    return Context(root=root, quiet=True)


# ------------------------------------------------------------ save 服务


def test_slot_file_whitelist(tmp_path):
    ctx = _ctx(tmp_path)
    service = SaveService(ctx, {"dir": "./saves"})
    assert service.slot_file("auto").name == "auto.json"
    assert service.slot_file("my-slot_1.2").name == "my-slot_1.2.json"
    # 路径 traversal / 非法字符 / 超长全部拒绝（白名单是防 traversal 的第一关）
    for bad in ("../evil", "a/b", "", "x" * 65, "slot;rm", "@x", "..\\evil"):
        with pytest.raises(ValueError):
            service.slot_file(bad)


def test_validate_record():
    ctx = _ctx(".")
    service = SaveService(ctx, {})
    assert service.validate_record({"scene": "a", "state": {}}) == []
    assert service.validate_record({"state": {}}) != []          # 缺 scene
    assert service.validate_record({"scene": "a"}) != []          # 缺 state
    assert service.validate_record({"scene": "a", "state": {}, "achievements": [1]}) != []
    assert service.validate_record("not-a-dict") != []


def test_save_load_roundtrip(tmp_path):
    from dse_core.plugins.achievements import AchievementsService
    from dse_core.plugins.engine import EngineService
    from dse_core.plugins.scenes import SceneService
    from dse_core.plugins.state import StateService
    from dse_core.plugins.console_io import ConsoleIO

    ctx = _ctx(tmp_path)
    state = StateService(ctx, {"initial": {"gold": 5}})
    io = ConsoleIO(ctx, {})
    scenes = SceneService(ctx, {})
    scenes.dict = {"mid-scene": {"text": "x"}, "other": {"text": "y"}}  # 预置字典，绕过文件加载
    achievements = AchievementsService(ctx, {"list": [{"id": "a1", "name": "甲", "desc": "d", "when": "gold >= 5"}]})
    engine = EngineService(ctx, {"entry": "start"})
    for svc in (state, io, scenes, achievements, engine):
        ctx.services[svc.name] = svc
    achievements.setup()  # 建表（unlock 依赖 table）
    save = SaveService(ctx, {"dir": "./saves"})
    ctx.services["save"] = save
    save.setup()

    engine.goto("mid-scene")
    state.apply({"gold": +10})
    achievements.unlock("a1")

    record = save.save("slot1")
    assert record["scene"] == "mid-scene"
    assert record["state"]["gold"] == 15
    assert record["achievements"] == ["a1"]
    assert record.get("version") is None  # 未启用 migrator 时不盖章（键不存在）
    assert (tmp_path / "saves" / "slot1.json").is_file()

    # 改状态后读档恢复
    state.apply({"gold": -15})
    achievements.unlocked.clear()
    engine.goto("other")
    assert save.load("slot1") is True
    assert state.get("gold") == 15
    assert "a1" in achievements.unlocked
    assert engine.current == "mid-scene"


def test_load_missing_slot(tmp_path, capsys):
    from dse_core.plugins.console_io import ConsoleIO

    ctx = _ctx(tmp_path)
    ctx.services["io"] = ConsoleIO(ctx, {})
    save = SaveService(ctx, {"dir": "./saves"})
    ctx.services["save"] = save
    # 最小依赖：scenes/engine/achievements 用替身（读档失败路径走不到它们）
    class _Stub:
        pass
    stub = _Stub()
    stub.has = lambda sid: True
    stub.ids = []
    ctx.services["scenes"] = stub
    engine_stub = _Stub()
    engine_stub.entry = "start"
    engine_stub.config = {}
    engine_stub.current = "start"
    engine_stub.goto = lambda sid: None
    ctx.services["engine"] = engine_stub
    ach_stub = _Stub()
    ach_stub.unlocked = set()
    ach_stub.restore = lambda ids: None
    ctx.services["achievements"] = ach_stub
    ctx.services["state"] = _Stub()

    assert save.load("nope") is False
    assert "存档不存在" in capsys.readouterr().out


def test_save_with_migrator_stamps_version(tmp_path):
    from dse_core.plugins.achievements import AchievementsService
    from dse_core.plugins.engine import EngineService
    from dse_core.plugins.scenes import SceneService
    from dse_core.plugins.state import StateService
    from dse_core.plugins.console_io import ConsoleIO

    ctx = _ctx(tmp_path)
    for cls, cfg in (
        (StateService, {"initial": {"gold": 1}}),
        (ConsoleIO, {}),
        (SceneService, {}),
        (AchievementsService, {}),
        (EngineService, {"entry": "start"}),
    ):
        svc = cls(ctx, cfg)
        ctx.services[svc.name] = svc
    migrate = SaveMigrateService(ctx, {"version": 3})
    ctx.services["save-migrate"] = migrate
    save = SaveService(ctx, {"dir": "./saves"})
    ctx.services["save"] = save
    save.setup()

    record = save.save("v3")
    assert record["version"] == 3
    raw = json.loads((tmp_path / "saves" / "v3.json").read_text(encoding="utf-8"))
    assert raw["version"] == 3


# ------------------------------------------------------------ save-migrate 服务


def test_needs_migration():
    ctx = _ctx(".")
    service = SaveMigrateService(ctx, {"version": 2})
    assert service.needs_migration({}) is True             # 无版本按 v1
    assert service.needs_migration({"version": 1}) is True
    assert service.needs_migration({"version": 2}) is False
    assert service.needs_migration({"version": 5}) is False


def test_migrate_chain():
    ctx = _ctx(".")
    service = SaveMigrateService(ctx, {"version": 3})
    service.migrations = {
        2: lambda r: {**r, "state": {**r.get("state", {}), "renamed": True}},
        3: lambda r: {**r, "state": {**r.get("state", {}), "v3": True}},
    }
    result = service.migrate({"version": 1, "state": {"gold": 1}})
    assert result["from"] == 1
    assert result["to"] == 3
    assert result["steps"] == [2, 3]
    assert result["record"]["state"]["renamed"] is True
    assert result["record"]["state"]["v3"] is True
    assert result["record"]["state"]["gold"] == 1  # 原字段不丢


def test_migrate_step_failure_keeps_previous():
    ctx = _ctx(".")
    service = SaveMigrateService(ctx, {"version": 3})

    def boom(record):
        raise RuntimeError("炸了")

    service.migrations = {2: boom}
    result = service.migrate({"version": 1, "state": {"gold": 9}})
    assert result["steps"] == []           # 失败步不计入
    assert result["record"]["state"]["gold"] == 9  # 保留迁移前状态
    assert result["to"] == 3               # 仍盖当前版本


def test_setup_loads_migrations_from_module(tmp_path, monkeypatch):
    module_dir = tmp_path / "mig"
    module_dir.mkdir()
    (module_dir / "mymig.py").write_text(
        "def migrate(record):\n    return {**record, 'migrated': True}\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(module_dir))
    ctx = _ctx(tmp_path)
    service = SaveMigrateService(ctx, {"version": 2, "migrations": {2: "mymig"}})
    service.setup()
    assert 2 in service.migrations
    result = service.migrate({"version": 1})
    assert result["record"]["migrated"] is True


def test_setup_skips_bad_migration_module(tmp_path):
    ctx = _ctx(tmp_path)
    service = SaveMigrateService(ctx, {"version": 2, "migrations": {2: "no.such.module"}})
    service.setup()  # 不炸，只告警
    assert service.migrations == {}
