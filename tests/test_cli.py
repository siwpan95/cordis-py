"""CLI 测试：check / scenes / info / version。"""

from pathlib import Path

import pytest

from dse_core.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ENGINE_ROOT = Path(__file__).resolve().parent.parent


def test_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert "dse-core" in capsys.readouterr().out


def test_check_ok(capsys):
    code = main(["check", "--root", str(FIXTURES / "mini")])
    assert code == 0
    assert "通过" in capsys.readouterr().out


def test_check_finds_dangling(tmp_path, capsys):
    (tmp_path / "c.yml").write_text(
        "pack: { id: c, version: 0.1.0 }\nscenes:\n  a: { text: 'x', choices: [{ text: 'go', goto: 'ghost' }] }\n",
        encoding="utf-8",
    )
    (tmp_path / "dse.yml").write_text(
        "- id: scenes\n  config: { packs: [./c.yml] }\n- id: engine\n  config: { entry: a }\n",
        encoding="utf-8",
    )
    code = main(["check", "--root", str(tmp_path)])
    assert code == 1
    err = capsys.readouterr().err
    assert "ghost" in err


def test_check_finds_missing_text(tmp_path, capsys):
    (tmp_path / "c.yml").write_text(
        "pack: { id: c, version: 0.1.0 }\nscenes:\n  a: { choices: [] }\n",
        encoding="utf-8",
    )
    (tmp_path / "dse.yml").write_text(
        "- id: scenes\n  config: { packs: [./c.yml] }\n- id: engine\n  config: { entry: a }\n",
        encoding="utf-8",
    )
    code = main(["check", "--root", str(tmp_path)])
    assert code == 1
    assert "text" in capsys.readouterr().err


def test_scenes_lists_all(capsys):
    code = main(["scenes", "--root", str(ENGINE_ROOT)])
    assert code == 0
    out = capsys.readouterr().out
    assert "wolf-fight" in out
    assert "共 7 个场景" in out


def test_info_reports_endings(capsys):
    code = main(["info", "--root", str(ENGINE_ROOT)])
    assert code == 0
    out = capsys.readouterr().out
    assert "结局: 3" in out


def test_missing_root_fails_cleanly(capsys):
    code = main(["check", "--root", "/nonexistent-dir-xyz"])
    assert code == 1
    assert "加载失败" in capsys.readouterr().err
