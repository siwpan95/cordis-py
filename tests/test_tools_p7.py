"""P7 工具链测试：dse graph / dse test / dse export-html。"""

import json
import re
from pathlib import Path

from dse_core import graph
from dse_core.cli import main
from dse_core.export_html import find_unsupported, py_expr_to_js, render_html
from dse_core.loader import load_project

NARRATIVE = Path(__file__).resolve().parent / "fixtures" / "narrative"
MINI = Path(__file__).resolve().parent / "fixtures" / "mini"


# ------------------------------------------------------------ dse graph

def test_graph_mermaid_output():
    project = load_project(NARRATIVE)
    out = graph.to_mermaid(project.dict, project.entry)
    assert out.startswith("flowchart LR")
    assert "n_lucky((" in out  # 结局双圈（id 已 sanitize）
    assert "-->" in out
    # 加权分支两条边都在
    assert len(re.findall(r"n_start --> n_(lucky|unlucky)", out)) == 2


def test_graph_dot_output():
    project = load_project(NARRATIVE)
    out = graph.to_dot(project.dict, project.entry)
    assert out.startswith("digraph scenes {")
    assert "doublecircle" in out
    assert '"start" -> "lucky"' in out


def test_graph_cli_stdout(capsys):
    code = main(["graph", "--root", str(NARRATIVE)])
    assert code == 0
    assert "flowchart LR" in capsys.readouterr().out


def test_graph_cli_write_file(tmp_path, capsys):
    out_file = tmp_path / "map.dot"
    code = main(["graph", "--root", str(NARRATIVE), "--format", "dot", "-o", str(out_file)])
    assert code == 0
    assert "digraph scenes" in out_file.read_text(encoding="utf-8")


# ------------------------------------------------------------ dse test

def test_test_command_pass(capsys):
    code = main([
        "test", "--root", str(MINI),
        "--script", "1,quit",
        "--expect-scene", "end-rich",
        "--expect", "gold >= 10",
    ])
    assert code == 0
    assert "✓ 通过" in capsys.readouterr().out


def test_test_command_scene_mismatch(capsys):
    code = main([
        "test", "--root", str(MINI),
        "--script", "2,quit",
        "--expect-scene", "end-rich",
    ])
    assert code == 1
    assert "最终场景应为 end-rich" in capsys.readouterr().err


def test_test_command_state_assert_fails(capsys):
    code = main(["test", "--root", str(MINI), "--script", "2,quit", "--expect", "gold > 100"])
    assert code == 1
    assert "状态断言失败" in capsys.readouterr().err


def test_test_command_seed_reproducible(capsys):
    # 加权随机夹具：固定 seed 后两次断言同一结局都通过
    for _ in range(2):
        code = main([
            "test", "--root", str(NARRATIVE),
            "--script", "2", "--seed", "42",
            "--expect-scene", "unlucky",
        ])
        assert code == 0
    capsys.readouterr()


# ------------------------------------------------------------ dse export-html

def test_py_expr_to_js_translation():
    assert py_expr_to_js("flags.met_wolf and gold >= 10") == "flags.met_wolf && gold >= 10"
    assert py_expr_to_js("not flags.dead or hp > 0") == "!flags.dead || hp > 0"
    assert py_expr_to_js("items['sword'] == True") == "items['sword'] == true"
    try:
        py_expr_to_js("gold // 2 > 1")
        raise AssertionError("整除应响亮报错")
    except ValueError:
        pass


def test_find_unsupported_warns_mode_scenes():
    scenes = {
        "fight": {"text": "x", "mode": "battle", "battle": {"enemy": "wolf"}},
        "bad": {"text": "y", "choices": [{"text": "c", "if": "a // 2 > 1", "goto": "fight"}]},
    }
    warnings = find_unsupported(scenes)
    assert any("mode=battle" in w for w in warnings)
    assert any("整除" in w for w in warnings)


def test_render_html_embeds_data():
    scenes = {"start": {"text": "你好 {name}", "choices": []}}
    html = render_html(scenes, "start", {"name": "旅人"}, title="测试")
    assert "<title>测试</title>" in html
    payload = json.loads(re.search(r"const GAME = (\{.*?\});\n", html, re.S).group(1))
    assert payload["entry"] == "start"
    assert payload["initial"] == {"name": "旅人"}
    assert payload["scenes"]["start"]["text"] == "你好 {name}"


def test_export_html_cli(tmp_path, capsys):
    out_file = tmp_path / "game.html"
    code = main(["export-html", "--root", str(NARRATIVE), "-o", str(out_file), "--title", "叙事演示"])
    assert code == 0
    html = out_file.read_text(encoding="utf-8")
    assert "<title>叙事演示</title>" in html
    assert "掷命运硬币" in html  # 场景数据已内嵌
    assert "旅人" in html       # initial state 已内嵌
    out = capsys.readouterr().out
    assert "4 场景" in out and "警告 0 条" in out
