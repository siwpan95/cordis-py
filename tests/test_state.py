"""state.py 测试 —— 移植自 Node tests/unit.mjs 的状态/效果/条件部分。"""

from dse_core.plugins.state import StateService
from dse_core.runtime import Context


def _make_state(initial: dict) -> StateService:
    ctx = Context(root=".", quiet=True)
    return StateService(ctx, {"initial": initial})


def test_apply_numeric_add():
    state = _make_state({"hp": 20, "gold": 5})
    changes = state.apply({"hp": -5, "gold": +1})
    assert state.get("hp") == 15
    assert state.get("gold") == 6
    assert changes[0] == {"path": "hp", "from": 20, "to": 15}


def test_apply_assign_non_numeric():
    state = _make_state({"name": "旅人"})
    state.apply({"name": "勇者"})
    assert state.get("name") == "勇者"


def test_apply_bool_is_assignment_not_arithmetic():
    state = _make_state({"flags": {}})
    state.apply({"flags.met": True})
    assert state.get("flags.met") is True


def test_apply_dot_path_counter():
    state = _make_state({})
    state.apply({"items.sword": +1})
    assert state.get("items.sword") == 1
    state.apply({"items.sword": +2})
    assert state.get("items.sword") == 3


def test_proto_pollution_rejected():
    state = _make_state({})
    assert state.set("__proto__.x", 1) is False
    assert state.get("__proto__.x") is None
    state.apply({"constructor.prototype.y": 1, "prototype.z": 2})
    assert state.get("constructor.prototype.y") is None


def test_interpolate():
    state = _make_state({"name": "旅人", "gold": 7})
    assert state.interpolate("你好，{name}！你有 {gold} 金币。") == "你好，旅人！你有 7 金币。"
    assert state.interpolate("缺失的 {nope} 保留原样") == "缺失的 {nope} 保留原样"


def test_check():
    state = _make_state({"hp": 20, "gold": 0, "items": {"sword": 1}})
    assert state.check("hp >= 10") is True
    assert state.check("gold > 0") is False
    assert state.check("items.sword >= 1") is True
    assert state.check(None) is True
    assert state.check("") is True


def test_check_bad_expression_falls_back_false():
    state = _make_state({"hp": 20})
    assert state.check("hp >>>=") is False
    assert state.check("missing_var > 0") is False


def test_reset_full():
    state = _make_state({"gold": 20})
    state.apply({"gold": -10})
    state.reset()
    assert state.get("gold") == 20


def test_reset_keep_prefix():
    state = _make_state({"gold": 20, "clues": {"loop": {"seen": 0}}})
    state.set("clues.loop.seen", 1)
    state.apply({"gold": -10})
    state.reset(keep=["clues.loop"])
    assert state.get("gold") == 20          # 消耗态复原
    assert state.get("clues.loop.seen") == 1  # 知识跨轮保留


def test_snapshot_restore():
    state = _make_state({"gold": 20})
    snap = state.snapshot()
    state.apply({"gold": -10})
    state.restore(snap)
    assert state.get("gold") == 20
    # 快照是深层拷贝，互不影响
    snap["gold"] = 999
    assert state.get("gold") == 20
