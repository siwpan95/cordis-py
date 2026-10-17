"""graph.py 测试 —— 移植自 Node tests/unit.mjs 的图分析部分。"""

from dse_core import graph

DICT = {
    "start": {
        "title": "s",
        "text": "t",
        "choices": [
            {"text": "a", "goto": "mid"},
            {"text": "b", "if": "gold > 0", "goto": "end-a"},
        ],
    },
    "mid": {"text": "m", "choices": [{"text": "c", "goto": "@restart"}]},
    "end-a": {"text": "e"},
    "orphan": {"text": "o", "choices": [{"text": "x", "goto": "nowhere"}]},
    "duel": {
        "text": "d",
        "mode": "battle",
        "battle": {"enemy": "wolf", "onWin": "end-a", "onLose": "mid"},
    },
}


def test_is_ending():
    assert graph.is_ending(DICT["end-a"])
    assert graph.is_ending({"choices": [{"goto": "@restart"}]})
    assert not graph.is_ending(DICT["start"])
    assert not graph.is_ending({"mode": "battle", "choices": []})


def test_edges_of_choice_and_mode():
    edges = graph.edges_of("duel", DICT["duel"])
    mode_edges = [e for e in edges if e["kind"] == "mode"]
    assert {e["to"] for e in mode_edges} == {"end-a", "mid"}


def test_reachable_from():
    result = graph.reachable_from(DICT, "start")
    assert result["reachable"] == {"start", "mid", "end-a"}
    assert result["order"][0] == "start"
    assert result["depth"]["mid"] == 1


def test_analyze():
    report = graph.analyze(DICT, "start")
    assert report["scenes"] == 5
    assert "orphan" in report["unreachable"]
    assert "duel" in report["unreachable"]
    assert any(d["to"] == "nowhere" for d in report["dangling"])
    # mid 的唯一选项是 @restart → 也是结局（isEnding 语义：全部选项皆特殊目标）
    assert report["endings"] == ["mid", "end-a"]
    assert report["endingsReachable"] == ["mid", "end-a"]
    assert report["reachableCount"] == 3


def test_shortest_path():
    assert graph.shortest_path(DICT, "start", "mid") == ["start", "mid"]
    assert graph.shortest_path(DICT, "start", "orphan") is None


def test_loop_dangling():
    scenes = {"a": {"choices": [{"text": "x", "goto": "@loop:missing"}]}}
    report = graph.analyze(scenes, "a")
    assert any(d["kind"] == "loop" for d in report["dangling"])
