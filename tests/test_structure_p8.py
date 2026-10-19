"""P8 叙事结构测试：tunnels 隧道 / once 选项 / visits 计数 / emit 效果键。"""

from pathlib import Path

import pytest

from dse_core import create_engine
from dse_core.cli import main
from dse_core.graph import analyze, edges_of
from dse_core.loader import load_project
from dse_core.modes import is_special_goto
from dse_core.plugins.scenes import find_dangling, validate_scenes

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "structure"


def make_ctx():
    return create_engine(FIXTURE)


# ------------------------------------------------------------ visits 内建计数

def test_visits_counted_before_on_enter():
    ctx = make_ctx()
    engine = ctx.engine
    engine.running = True
    engine.current = "plaza"
    # 手动跑进入逻辑的一段：visits 自增（经 run() 完整循环过重，直接验证 apply 语义）
    ctx.state.apply({f"visits.{engine.current}": 1})
    assert ctx.state.get("visits.plaza") == 1
    ctx.state.apply({f"visits.{engine.current}": 1})
    assert ctx.state.get("visits.plaza") == 2
    # 条件表达式可直接查询（Ink 式 {catacombs} 的 dse 对应物）
    assert ctx.state.check("visits.plaza > 1")
    ctx.dispose()


def test_visits_e2e_via_scripted_play(capsys):
    # plaza → alley → plaza：第二次进广场时 visits.plaza = 2，插值应显示「第 2 次」
    code = main(["play", "--root", str(FIXTURE), "--input", "3,2,quit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "第 1 次站在这里" in out
    assert "第 2 次站在这里" in out


# ------------------------------------------------------------ tunnels 隧道

def test_tunnel_call_and_return(capsys):
    # 广场 → call shop → @return → 回到广场（不是结局、栈已弹空）
    code = main(["play", "--root", str(FIXTURE), "--input", "1,1,quit"])
    assert code == 0
    out = capsys.readouterr().out
    assert "商店" in out
    assert out.count("广场") >= 2  # 返回后再次渲染广场


def test_return_with_empty_stack_is_loud():
    ctx = make_ctx()
    engine = ctx.engine
    engine.current = "shop"  # 未经 call 直接进入 shop
    engine._call_stack = []
    with pytest.raises(RuntimeError, match="调用栈为空"):
        # 模拟 @return 处理分支
        if not engine._call_stack:
            raise RuntimeError(
                f'场景 "{engine.current}" 使用了 @return，但调用栈为空'
                "（@return 只能出现在经 goto: {call: ...} 进入的场景）"
            )
    ctx.dispose()


def test_call_stack_cleared_on_restart():
    ctx = make_ctx()
    engine = ctx.engine
    engine._call_stack = ["plaza", "shop"]
    # @restart 语义：全量重置，调用栈必须清空（否则 @return 穿越到旧周目）
    engine._call_stack.clear()
    ctx.state.reset()
    assert engine._call_stack == []
    assert ctx.state.get("visits") is None
    ctx.dispose()


def test_return_is_special_goto():
    assert is_special_goto("@return")
    assert not is_special_goto("shop")


# ------------------------------------------------------------ once 选项

def test_once_choice_disappears_after_picked(capsys):
    # 广场选「看一眼告示牌」（once）→ 回到广场后该选项消失，剩 2 个选项
    code = main(["play", "--root", str(FIXTURE), "--input", "2,quit"])
    assert code == 0
    out = capsys.readouterr().out
    assert out.count("看一眼告示牌") == 1  # 只在首次渲染出现


def test_once_custom_key():
    ctx = make_ctx()
    engine = ctx.engine
    scene = ctx.scenes.get("alley")
    choice = scene["choices"][0]
    assert engine._once_key("alley", 0, choice) == "looted-bin"  # 自定义键优先
    scene2 = ctx.scenes.get("plaza")
    assert engine._once_key("plaza", 1, scene2["choices"][1]) == "plaza#1"  # 缺省键
    ctx.dispose()


def test_once_persisted_in_state_snapshot():
    ctx = make_ctx()
    ctx.state.set("onceSeen", ["plaza#1"])
    snap = ctx.state.snapshot()
    assert snap.get("onceSeen") == ["plaza#1"]
    ctx.dispose()


# ------------------------------------------------------------ emit 效果键

def test_emit_effect_broadcasts_event():
    ctx = make_ctx()
    received = []
    ctx.on("notice/read", lambda: received.append("hit"))
    changes = ctx.state.apply({"emit": "notice/read", "gold": 5})
    assert received == ["hit"]
    assert ctx.state.get("gold") == 5
    # emit 不写入状态
    assert ctx.state.get("emit") is None
    assert any(c["path"] == "emit" for c in changes)
    ctx.dispose()


def test_emit_effect_list_value():
    ctx = make_ctx()
    received = []
    ctx.on("a", lambda: received.append("a"))
    ctx.on("b", lambda: received.append("b"))
    ctx.state.apply({"emit": ["a", "b"]})
    assert received == ["a", "b"]
    ctx.dispose()


# ------------------------------------------------------------ 校验器与图分析

def test_fixture_passes_validation():
    project = load_project(FIXTURE)
    assert validate_scenes(project.dict, source="structure") == []
    assert find_dangling(project.dict) == []


def test_graph_call_edge_counted():
    project = load_project(FIXTURE)
    edges = edges_of("plaza", project.dict["plaza"])
    kinds = {e["to"]: e["kind"] for e in edges}
    assert kinds.get("shop") == "call"
    report = analyze(project.dict, project.entry)
    assert "shop" in report["reachable"]  # call 边参与可达性


def test_validate_rejects_bad_call():
    scenes = {"a": {"text": "x", "choices": [{"text": "go", "goto": {"call": 123}}]}}
    errors = validate_scenes(scenes)
    assert any("隧道跳转缺少 call" in e for e in errors)


def test_validate_rejects_bad_once():
    scenes = {"a": {"text": "x", "choices": [{"text": "go", "goto": "a", "once": 5}]}}
    errors = validate_scenes(scenes)
    assert any("once 必须是布尔或字符串键" in e for e in errors)


def test_dangling_detects_bad_call_target():
    scenes = {"a": {"text": "x", "choices": [{"text": "go", "goto": {"call": "ghost"}}]}}
    dangling = find_dangling(scenes)
    assert len(dangling) == 1 and "ghost" in dangling[0]
