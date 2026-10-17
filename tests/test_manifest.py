"""manifest.py 测试 —— 移植自 Node tests/unit.mjs 的 manifest 部分。"""

from dse_core.manifest import normalize_manifest, validate_manifest


def test_normalize_defaults_from_file_and_scenes():
    manifest = normalize_manifest({}, "content/starter.yml", {"start": {"mode": "battle"}})
    assert manifest["id"] == "starter"
    assert manifest["entry"] == "start"
    assert manifest["modes"] == ["battle"]
    assert manifest["version"] == "0.0.0"
    assert manifest["scenes"] == 1


def test_normalize_full():
    raw = {
        "id": "starter",
        "name": "启程",
        "version": "0.1.0",
        "entry": "start",
        "requires": {"plugins": ["combat"], "state": ["gold"]},
    }
    manifest = normalize_manifest(raw, "x.yml", {"a": {}, "b": {}})
    assert manifest["requires"]["plugins"] == ["combat"]
    assert manifest["requires"]["state"] == ["gold"]
    assert manifest["scenes"] == 2


def test_validate_ok():
    assert validate_manifest({"id": "starter", "version": "0.1.0", "modes": ["battle"]}) == []


def test_validate_problems():
    problems = validate_manifest({"id": "Bad_Id", "version": "1.0", "modes": ["nope"]})
    assert len(problems) == 3


def test_validate_non_object():
    assert validate_manifest(None) == ["manifest 不是对象"]
