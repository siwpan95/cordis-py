"""P6 叙事层测试：extraText 条件段 / onExit / 加权随机 goto。"""

from pathlib import Path

from dse_core import create_engine
from dse_core.graph import analyze, edges_of
from dse_core.loader import load_project
from dse_core.plugins.scenes import find_dangling, validate_scenes

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "narrative"


def make_engine():
    """装配夹具工程，返回引擎服务实例（Context 上的 engine）。"""
    return create_engine(FIXTURE).engine


# ------------------------------------------------------------ extraText 条件段

def test_extra_text_hidden_until_condition_true():
    engine = make_engine()
    scene = engine.ctx.scenes.get("start")
    # flags.met_wolf = False：条件段隐藏，无条件段显示
    engine.ctx.state.data["flags"]["met_wolf"] = False
    text = scene["text"]
    for seg in scene.get("extraText") or []:
        if engine.ctx.state.check(seg.get("if")):
            text += "\n" + seg["text"]
    assert "爪痕" not in text
    assert "无条件追加行" in text


def test_extra_text_shown_when_condition_true():
    engine = make_engine()
    engine.ctx.state.data["flags"]["met_wolf"] = True
    scene = engine.ctx.scenes.get("start")
    text = scene["text"]
    for seg in scene.get("extraText") or []:
        if engine.ctx.state.check(seg.get("if")):
            text += "\n" + seg["text"]
    assert "爪痕" in text


# ------------------------------------------------------------ onExit

def test_on_exit_applied_when_leaving_scene():
    engine = make_engine()
    # 模拟：从 forest 跳回 start —— forest.onExit 应给 gold +10
    engine.current = "forest"
    engine.goto("start")
    assert engine._pending_exit == "forest"

    # 手动兑现 run() 开头的挂账逻辑（不跑完整主循环）
    old_scene = engine.ctx.scenes.get(engine._pending_exit)
    engine._pending_exit = None
    for change in engine.ctx.state.apply(old_scene.get("onExit")):
        pass
    assert engine.ctx.state.get("gold") == 13  # 3 + 10


def test_on_exit_not_applied_without_goto():
    engine = make_engine()
    engine.current = "forest"
    # 未发生跳转 → 无挂账
    assert engine._pending_exit is None


# ------------------------------------------------------------ 加权随机 goto

def test_weighted_goto_deterministic_with_seed():
    # seed=42 固定 → 两次创建引擎抽到的序列一致
    picks_a = []
    engine = make_engine()
    for _ in range(20):
        picks_a.append(engine._pick_weighted([{"to": "lucky", "weight": 1}, {"to": "unlucky", "weight": 3}]))
    engine2 = make_engine()
    picks_b = [engine2._pick_weighted([{"to": "lucky", "weight": 1}, {"to": "unlucky", "weight": 3}]) for _ in range(20)]
    assert picks_a == picks_b
    assert set(picks_a) == {"lucky", "unlucky"}  # 两个分支都出现过


def test_weighted_goto_distribution():
    engine = make_engine()
    options = [{"to": "lucky", "weight": 1}, {"to": "unlucky", "weight": 3}]
    counts = {"lucky": 0, "unlucky": 0}
    for _ in range(4000):
        counts[engine._pick_weighted(options)] += 1
    # 权重 1:3 → 约 25% / 75%，留足统计余量
    assert 800 < counts["lucky"] < 1200
    assert 2800 < counts["unlucky"] < 3200


def test_weighted_goto_rejects_bad_config():
    engine = make_engine()
    for bad in ([], [{"to": "x", "weight": 0}], [{"weight": 1}], [{"to": "x", "weight": -2}]):
        try:
            engine._pick_weighted(bad)
            raise AssertionError(f"应响亮报错: {bad!r}")
        except RuntimeError:
            pass


# ------------------------------------------------------------ 校验器与图分析适配

def test_fixture_passes_validation():
    project = load_project(FIXTURE)
    errors = validate_scenes(project.dict, source="narrative")
    assert errors == []
    assert find_dangling(project.dict) == []


def test_graph_includes_weighted_edges():
    project = load_project(FIXTURE)
    edges = edges_of("start", project.dict["start"])
    targets = {e["to"] for e in edges}
    assert targets == {"forest", "lucky", "unlucky"}

    report = analyze(project.dict, project.entry)
    assert "lucky" in report["reachable"]
    assert "unlucky" in report["reachable"]
    assert report["dangling"] == []


def test_dangling_detects_bad_weighted_branch():
    scenes = {
        "a": {
            "text": "x",
            "choices": [{"text": "go", "goto": [{"to": "nowhere", "weight": 1}]}],
        }
    }
    dangling = find_dangling(scenes)
    assert len(dangling) == 1
    assert "nowhere" in dangling[0] and "加权分支" in dangling[0]


def test_validate_rejects_bad_weight():
    scenes = {
        "a": {
            "text": "x",
            "choices": [{"text": "go", "goto": [{"to": "b", "weight": -1}]}],
        },
        "b": {"text": "y"},
    }
    errors = validate_scenes(scenes)
    assert any("权重必须为正数" in e for e in errors)


def test_validate_rejects_bad_extra_text():
    scenes = {"a": {"text": "x", "extraText": [{"if": "1 > 0"}]}}  # 段缺 text
    errors = validate_scenes(scenes)
    assert any("extraText 第 1 段缺少 text" in e for e in errors)


def test_validate_rejects_bad_on_exit():
    scenes = {"a": {"text": "x", "onExit": ["not-a-dict"]}}
    errors = validate_scenes(scenes)
    assert any("onExit 必须是效果对象" in e for e in errors)
