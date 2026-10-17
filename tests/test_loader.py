"""loader / scenes 服务测试 —— 工程加载、双缓冲重建、悬空与结构校验。"""

from pathlib import Path

import pytest

from dse_core.loader import load_pack_file, load_project, scene_chars
from dse_core.plugins.scenes import SceneService, find_dangling, validate_scenes
from dse_core.runtime import Context
from dse_core.schema import validate_pack

ENGINE_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_load_engine_project():
    project = load_project(ENGINE_ROOT)
    assert project.entry == "start"
    assert "wolf-fight" in project.dict
    assert project.dict["wolf-fight"]["mode"] == "battle"
    assert project.dict["wolf-fight"]["battle"]["onWin"] == "forest-win"
    assert len(project.manifests) == 1
    assert project.manifests[0]["id"] == "starter"


def test_later_pack_overrides_same_id(tmp_path):
    (tmp_path / "a.yml").write_text(
        "pack: { id: a, version: 0.1.0 }\nscenes:\n  s: { text: 'A 版' }\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yml").write_text(
        "pack: { id: b, version: 0.1.0 }\nscenes:\n  s: { text: 'B 版' }\n",
        encoding="utf-8",
    )
    (tmp_path / "dse.yml").write_text(
        "- id: scenes\n  config:\n    packs: [./a.yml, ./b.yml]\n"
        "- id: engine\n  config: { entry: s }\n",
        encoding="utf-8",
    )
    project = load_project(tmp_path)
    assert project.dict["s"]["text"] == "B 版"


def test_load_pack_file_rejects_bad_shape(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_pack_file(bad)


def test_scene_service_rebuild():
    ctx = Context(root=ENGINE_ROOT, quiet=True)
    service = SceneService(ctx, {"packs": ["./content/starter.yml"]})
    service.setup()
    assert service.size == 7
    assert service.has("start")
    assert service.ids[0] == "start"
    with pytest.raises(KeyError):
        service.get("no-such-scene")


def test_rebuild_double_buffer_keeps_old_dict():
    ctx = Context(root=ENGINE_ROOT, quiet=True)
    service = SceneService(ctx, {"packs": ["./content/starter.yml"]})
    service.setup()
    # 注入一个带悬空跳转的包 → rebuild 必须炸，且旧字典毫发无损
    service.loaded["./content/bad.yml"] = {"broken": {"text": "x", "choices": [{"text": "y", "goto": "nowhere"}]}}
    service.packs.append("./content/bad.yml")
    before = dict(service.dict)
    with pytest.raises(ValueError, match="未定义的场景跳转"):
        service.rebuild()
    assert service.dict == before


def test_path_whitelist_rejects_outside(tmp_path):
    ctx = Context(root=ENGINE_ROOT, quiet=True)
    service = SceneService(ctx, {"packs": []})
    with pytest.raises(ValueError, match="越出工程目录"):
        service.import_pack("../../etc/passwd")


def test_find_dangling():
    problems = find_dangling({"a": {"choices": [{"text": "x", "goto": "b"}]}})
    assert problems and '"b"' in problems[0]
    assert find_dangling({"a": {"choices": [{"text": "x"}]}})
    assert find_dangling({"a": {"choices": [{"text": "x", "goto": "@restart"}]}}) == []


def test_validate_scenes():
    errors = validate_scenes({"a": {"choices": []}}, "t.yml")
    assert any("text" in e for e in errors)
    errors = validate_scenes({"a": {"text": "ok", "choices": [{"text": "c"}]}}, "t.yml")
    assert errors == []


def test_schema_validate_pack():
    good = {"start": {"title": "t", "text": "x", "choices": [{"text": "c", "goto": "end"}]}, "end": {"text": "e"}}
    assert validate_pack(good) == []
    bad = {"start": {"choices": "not-a-list"}}
    assert validate_pack(bad, "t.yml")


def test_scene_chars():
    scene = {"title": "ab", "text": "cde", "choices": [{"text": "fg"}]}
    assert scene_chars(scene) == 7
