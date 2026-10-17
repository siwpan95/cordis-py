"""modes.py 测试 —— 移植自 Node tests/unit.mjs 的模式表部分。"""

from dse_core import modes


def test_builtin_modes():
    assert modes.mode_names() == ["normal", "battle", "trade", "diary", "dialogue"]


def test_mode_edges():
    assert modes.mode_edges("battle") == ["onWin", "onLose", "onFlee"]
    assert modes.mode_edges("normal") == []
    assert modes.mode_edges("unknown-mode") == []


def test_register_mode_extensible():
    spec = modes.register_mode("stealth", {"edges": ["onSneak"], "plugin": "stealth", "desc": "潜行"})
    assert spec["edges"] == ["onSneak"]
    assert modes.is_known_mode("stealth")
    assert modes.mode_edge_table()["stealth"] == ["onSneak"]


def test_special_goto():
    assert modes.is_special_goto("@restart")
    assert modes.is_special_goto("@loop:market")
    assert not modes.is_special_goto("forest")
    assert modes.resolve_goto("@loop:market") == "market"
    assert modes.resolve_goto("forest") == "forest"
    assert modes.resolve_goto(None) == ""
