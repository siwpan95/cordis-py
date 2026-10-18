"""P4 测试：sound（合成/静音/清理）、scenes.reload、hot-reload（路径白名单+轮询）。"""

import time
from pathlib import Path

import pytest

from dse_core.plugins import sound as sound_mod
from dse_core.plugins.console_io import ConsoleIO
from dse_core.plugins.hot_reload import HotReloadService
from dse_core.plugins.scenes import SceneService
from dse_core.plugins.sound import SoundService, encode_wav, synth
from dse_core.plugins.state import StateService
from dse_core.runtime import Context

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ------------------------------------------------------------ sound 合成


def test_synth_shapes():
    samples = synth({"freq": 440, "ms": 10}, sample_rate=1000)
    assert len(samples) == 10                      # ms → 采样数
    assert all(-1.0 <= s <= 1.0 for s in samples)  # 包络控制在幅值内
    multi = synth({"notes": [440, 880], "ms": 10}, sample_rate=1000)
    assert len(multi) == 20                        # 多音符序列拼接


def test_encode_wav_header():
    wav = encode_wav(synth({"freq": 440, "ms": 10}, sample_rate=1000), sample_rate=1000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    import wave, io
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2 and w.getframerate() == 1000


def test_muted_mode_generates_no_files(tmp_path, monkeypatch):
    """静音模式不生成任何音频文件（Node 版 e2e 同款断言）。"""
    monkeypatch.setenv("DSE_SFX_DIR", str(tmp_path / "sfx"))
    monkeypatch.setenv("DSE_MUTE", "1")
    ctx = Context(root=tmp_path, quiet=True)
    service = SoundService(ctx, {})
    service.setup()
    assert service.play("scene-enter") is True     # 静音也回报成功
    assert service.played == 0
    assert not list((tmp_path / "sfx").glob("*.wav")) if (tmp_path / "sfx").exists() else True


def test_unmuted_play_writes_and_cleans(tmp_path, monkeypatch):
    monkeypatch.setenv("DSE_SFX_DIR", str(tmp_path / "sfx"))
    monkeypatch.delenv("DSE_MUTE", raising=False)
    played: list[Path] = []
    monkeypatch.setattr(sound_mod, "play_file", lambda f: played.append(f))
    ctx = Context(root=tmp_path, quiet=True)
    service = SoundService(ctx, {})
    service.setup()
    assert service.play("battle-crit") is True
    assert len(played) == 1 and played[0].suffix == ".wav"
    assert len(service.files) == 1
    service.dispose()
    assert played[0].exists() is False              # 退出即清理
    assert service.files == []


def test_unknown_sound_key_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("DSE_MUTE", "1")
    ctx = Context(root=tmp_path, quiet=True)
    service = SoundService(ctx, {})
    service.setup()
    assert service.play("no-such-sound") is False


# ------------------------------------------------------------ scenes.reload


def _make_scenes(root: Path, pack_rel: str = "./content/x.yml") -> SceneService:
    ctx = Context(root=root, quiet=True)
    ctx.services["scenes"] = SceneService(ctx, {"packs": [pack_rel]})
    return ctx.services["scenes"]


def test_reload_picks_up_changes(tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    pack = content / "x.yml"
    pack.write_text("pack: { id: x, version: 0.1.0 }\nscenes:\n  a: { text: '旧文' }\n", encoding="utf-8")
    service = _make_scenes(tmp_path)
    service.setup()
    assert service.dict["a"]["text"] == "旧文"

    pack.write_text("pack: { id: x, version: 0.1.0 }\nscenes:\n  a: { text: '新文' }\n", encoding="utf-8")
    assert service.reload("./content/x.yml") is True
    assert service.dict["a"]["text"] == "新文"       # 热更生效


def test_reload_rejects_broken_pack_keeps_old(tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    pack = content / "x.yml"
    pack.write_text("pack: { id: x, version: 0.1.0 }\nscenes:\n  a: { text: '旧文' }\n", encoding="utf-8")
    service = _make_scenes(tmp_path)
    service.setup()

    pack.write_text("pack: { id: x, version: 0.1.0 }\nscenes:\n  a: { text: '坏文', choices: [{ text: 'x', goto: 'ghost' }] }\n", encoding="utf-8")
    assert service.reload("./content/x.yml") is False          # 悬空跳转被拒
    assert service.dict["a"]["text"] == "旧文"                 # 旧字典毫发无损（双缓冲）


def test_reload_skips_unknown_pack(tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    (content / "x.yml").write_text(
        "pack: { id: x, version: 0.1.0 }\nscenes:\n  a: { text: '文' }\n", encoding="utf-8"
    )
    service = _make_scenes(tmp_path)
    service.setup()
    assert service.reload("./content/nope.yml") is False


# ------------------------------------------------------------ hot-reload


def test_hot_reload_rejects_outside_path(tmp_path):
    ctx = Context(root=tmp_path, quiet=True)
    ctx.services["scenes"] = SceneService(ctx, {})
    ctx.services["io"] = ConsoleIO(ctx, {})
    service = HotReloadService(ctx, {"paths": ["../../etc"]})
    with pytest.raises(ValueError, match="越出工程目录"):
        service.setup()


def test_hot_reload_detects_change(tmp_path):
    """轮询线程集成测试：改文件 → 字典更新（等最多 2 秒）。"""
    content = tmp_path / "content"
    content.mkdir()
    pack = content / "x.yml"
    pack.write_text("pack: { id: x, version: 0.1.0 }\nscenes:\n  a: { text: '旧文' }\n", encoding="utf-8")
    ctx = Context(root=tmp_path, quiet=True)
    scenes = SceneService(ctx, {"packs": ["./content/x.yml"]})
    ctx.services["scenes"] = scenes
    ctx.services["io"] = ConsoleIO(ctx, {})
    scenes.setup()

    service = HotReloadService(ctx, {"paths": ["./content"], "debounce": 50})
    service.setup()
    try:
        time.sleep(0.3)  # 越过初始 mtime 快照
        pack.write_text("pack: { id: x, version: 0.1.0 }\nscenes:\n  a: { text: '热更新文' }\n", encoding="utf-8")
        deadline = time.time() + 2
        while time.time() < deadline and scenes.dict["a"]["text"] != "热更新文":
            time.sleep(0.1)
        assert scenes.dict["a"]["text"] == "热更新文"
    finally:
        service.dispose()
