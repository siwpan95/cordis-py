"""P2 CLI 测试：packs / saves / doctor / new。"""

import json
from pathlib import Path

from dse_core.cli import main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYS_FIXTURE = FIXTURES / "sys"
NOMODE_FIXTURE = FIXTURES / "nomode"


def test_packs_lists_manifest(capsys):
    code = main(["packs", "--root", str(SYS_FIXTURE)])
    assert code == 0
    out = capsys.readouterr().out
    assert "sys" in out
    assert "系统层演示" in out


def test_saves_lists_slots(capsys):
    saves_dir = SYS_FIXTURE / "saves"
    saves_dir.mkdir(parents=True, exist_ok=True)
    (saves_dir / "manual.json").write_text(
        json.dumps({"scene": "rich", "savedAt": "2026-10-18T00:00:00Z"}), encoding="utf-8"
    )
    code = main(["saves", "--root", str(SYS_FIXTURE)])
    assert code == 0
    out = capsys.readouterr().out
    assert "manual" in out and "rich" in out


def test_saves_empty_dir(capsys):
    # mini 夹具没配 save 插件 → 存档目录不存在，给出明确提示而非报错
    code = main(["saves", "--root", str(FIXTURES / "mini")])
    assert code == 0
    assert "存档目录不存在" in capsys.readouterr().out


def test_doctor_detects_missing_plugin(capsys):
    code = main(["doctor", "--root", str(NOMODE_FIXTURE)])
    assert code == 1
    err = capsys.readouterr().err
    assert "trade" in err
    assert "未安装" in err


def test_doctor_healthy_project(capsys):
    code = main(["doctor", "--root", str(SYS_FIXTURE)])
    assert code == 0
    out = capsys.readouterr().out
    assert "健康" in out


def test_new_generates_and_registers(tmp_path, capsys):
    (tmp_path / "dse.yml").write_text(
        "- id: scenes\n  config:\n    packs:\n      - ./content/existing.yml\n"
        "- id: engine\n  config: { entry: start }\n",
        encoding="utf-8",
    )
    code = main(["new", "my-pack", "--template", "hub", "--root", str(tmp_path)])
    assert code == 0
    pack_file = tmp_path / "content" / "my-pack.yml"
    assert pack_file.is_file()
    assert "id: my-pack" in pack_file.read_text(encoding="utf-8")
    # 挂进 dse.yml 的 scenes.packs（文本级插入，保留其余格式）
    assert "./content/my-pack.yml" in (tmp_path / "dse.yml").read_text(encoding="utf-8")
    # 原条目不受影响
    assert "./content/existing.yml" in (tmp_path / "dse.yml").read_text(encoding="utf-8")


def test_new_rejects_bad_name(tmp_path, capsys):
    (tmp_path / "dse.yml").write_text("- id: scenes\n  config: { packs: [] }\n", encoding="utf-8")
    code = main(["new", "Bad-Name", "--root", str(tmp_path)])
    assert code == 1
    assert "非法" in capsys.readouterr().err
