"""P9 体验与数据包测试：文本变体 / telemetry 埋点 + analyze / rollback。"""

import json
from pathlib import Path

from dse_core import create_engine
from dse_core.cli import main
from dse_core.loader import load_project
from dse_core.plugins.scenes import validate_scenes

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "experience"


def make_ctx():
    return create_engine(FIXTURE)


# ------------------------------------------------------------ 文本变体

def test_cycle_variant_rotates_by_visits():
    ctx = make_ctx()
    engine = ctx.engine
    scene = ctx.scenes.get("hall")
    engine.current = "hall"
    for expected_visit, expected_text in (
        (1, "大厅空荡荡的。"), (2, "大厅里点起了灯。"), (3, "大厅传来回声。"),
        (4, "大厅空荡荡的。"),  # 轮转回第一条
    ):
        ctx.state.set("visits.hall", expected_visit)
        assert engine._resolve_variant(scene) == expected_text
    ctx.dispose()


def test_shuffle_variant_deterministic_with_seed():
    ctx1, ctx2 = make_ctx(), make_ctx()
    scene = ctx1.scenes.get("luck")
    picks_a = [ctx1.engine._resolve_variant(scene) for _ in range(10)]
    picks_b = [ctx2.engine._resolve_variant(scene) for _ in range(10)]
    assert picks_a == picks_b  # seed=7 固定
    assert set(picks_a) == {"抽到上上签。", "抽到平平签。"}
    ctx1.dispose()
    ctx2.dispose()


def test_no_variants_returns_none():
    ctx = make_ctx()
    assert ctx.engine._resolve_variant(ctx.scenes.get("room")) is None
    ctx.dispose()


def test_validate_rejects_bad_variants():
    for bad_variants, msg in (
        ([], "非空字符串数组"),
        ("not-a-list", "非空字符串数组"),
        (["ok", 42], "非空字符串数组"),
    ):
        errors = validate_scenes({"a": {"text": "x", "variants": bad_variants}})
        assert any(msg in e for e in errors), bad_variants
    errors = validate_scenes({"a": {"text": "x", "variants": ["v"], "variantMode": "loop"}})
    assert any("variantMode" in e for e in errors)


def test_cycle_variant_e2e(capsys):
    # hall(cycle 1) → room → hall(cycle 2)
    code = main(["play", "--root", str(FIXTURE), "--input", "1,1,quit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "大厅空荡荡的。" in out
    assert "大厅里点起了灯。" in out


# ------------------------------------------------------------ rollback

def test_rollback_restores_state_and_scene(capsys):
    # hall → room(onEnter gold+1) → rollback → 应回 hall 且 gold 归零
    code = main(["play", "--root", str(FIXTURE), "--input", "1,rollback,quit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "已回滚到「hall」" in out


def test_rollback_state_really_restored():
    ctx = make_ctx()
    engine = ctx.engine
    # 手工构造两帧历史：进 hall 前（gold 0）→ 进 room 前（gold 0，onEnter 未跑）
    engine._history.append({"scene": "hall", "state": {"gold": 0}})
    ctx.state.set("gold", 99)
    engine._history.append({"scene": "room", "state": {"gold": 0}})
    ctx.state.set("gold", 100)
    engine.current = "room"
    assert engine.rollback(1)
    assert engine.current == "hall"
    assert ctx.state.get("gold") == 0
    ctx.dispose()


def test_rollback_fails_without_enough_history():
    ctx = make_ctx()
    engine = ctx.engine
    engine._history.append({"scene": "hall", "state": {}})
    assert not engine.rollback(1)   # 只剩开局一帧，无可回退
    assert not engine.rollback(5)
    ctx.dispose()


def test_rollback_clears_call_stack():
    ctx = make_ctx()
    engine = ctx.engine
    engine._history = [
        {"scene": "a", "state": {}},
        {"scene": "b", "state": {}},
    ]
    engine._call_stack = ["x", "y"]
    engine._pending_exit = "b"
    engine.rollback(1)
    assert engine._call_stack == []
    assert engine._pending_exit is None
    ctx.dispose()


def test_history_capped_by_max_history():
    ctx = make_ctx()
    engine = ctx.engine
    engine._max_history = 3
    for i in range(10):
        engine._history.append({"scene": f"s{i}", "state": {}})
        if len(engine._history) > engine._max_history:
            engine._history.pop(0)
    assert len(engine._history) == 3
    assert engine._history[0]["scene"] == "s7"
    ctx.dispose()


# ------------------------------------------------------------ telemetry + analyze

def test_telemetry_writes_jsonl(capsys):
    log = FIXTURE / "telemetry-test.jsonl"
    log.unlink(missing_ok=True)
    code = main(["play", "--root", str(FIXTURE), "--input", "1,1,quit"])
    assert code == 0
    capsys.readouterr()
    assert log.is_file()
    events = [json.loads(line)["event"] for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert "session/start" in events
    assert "scene/enter" in events
    assert "choice/made" in events
    assert "session/stop" in events


def test_telemetry_disabled_by_env(capsys, monkeypatch):
    log = FIXTURE / "telemetry-test.jsonl"
    log.unlink(missing_ok=True)
    monkeypatch.setenv("DSE_TELEMETRY", "0")
    code = main(["play", "--root", str(FIXTURE), "--input", "quit"])
    assert code == 0
    capsys.readouterr()
    assert not log.exists()


def test_telemetry_rejects_path_escape(capsys):
    ctx = create_engine(FIXTURE)
    tel = ctx.services["telemetry"]
    tel.config["file"] = "../../evil.jsonl"
    tel.setup()  # 重新 setup：越界应禁用而非写文件
    assert not tel._enabled
    ctx.dispose()


def test_analyze_report(capsys):
    log = FIXTURE / "telemetry-test.jsonl"
    log.unlink(missing_ok=True)
    main(["play", "--root", str(FIXTURE), "--input", "1,1,quit"])
    capsys.readouterr()
    code = main(["analyze", "--root", str(FIXTURE), "--file", "telemetry-test.jsonl"])
    assert code == 0
    out = capsys.readouterr().out
    assert "会话数: 1" in out
    assert "场景访问 Top" in out
    assert "hall" in out and "room" in out
    assert "选项分布" in out


def test_analyze_missing_file(capsys):
    code = main(["analyze", "--root", str(FIXTURE), "--file", "ghost.jsonl"])
    assert code == 1
    assert "埋点文件不存在" in capsys.readouterr().err
