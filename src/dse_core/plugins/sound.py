"""音效插件 —— 订阅事件 → 程序化合成 PCM → 播放（引擎零改动）。

移植自 dse-core(Node) plugins/sound.js。

设计要点：
1. 音效全部程序化合成（无外部音频资源）：波形 + ADSR 包络，避免爆音
2. 纯事件订阅：scene/enter、choice/made、achievement/unlock、battle/*、
   engine/end、hot-reload/applied —— 零侵入
3. 播放不阻塞主循环：Windows 用 winsound SND_ASYNC（stdlib），
   其他平台起子进程（afplay / aplay）；无播放器静默降级
4. 事件 → 音效映射数据驱动，dse.yml 可覆盖/扩充，支持 mute
   （优先级：DSE_MUTE=1 > config.mute）

与 Node 版的差异：Node 靠子进程 PlaySync + unref；Python 版 Windows 走
winsound 异步播放，无需临时播放器进程。WAV 编码用 stdlib wave 模块。
"""

from __future__ import annotations

import io
import math
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from ..runtime import Service

# ------------------------------------------------------------ 合成


WAVES = {
    "sine": lambda p: math.sin(p),
    "square": lambda p: 1.0 if math.sin(p) >= 0 else -1.0,
    "saw": lambda p: 2 * ((p / (2 * math.pi)) % 1) - 1,
    "triangle": lambda p: (2 / math.pi) * math.asin(math.sin(p)),
}


def _envelope(progress: float) -> float:
    """ADSR 包络：attack 5% + 指数衰减 + 尾部淡出，消除爆音。"""
    attack = 0.05
    if progress < attack:
        return progress / attack
    return (1 - (progress - attack) / (1 - attack)) ** 2


def synth(spec: dict, sample_rate: int = 22050) -> list[float]:
    """合成一段采样（支持单频或多音符序列）。"""
    freqs = spec.get("notes") or [spec.get("freq", 440)]
    ms = spec.get("ms", 100)
    shape = WAVES.get(spec.get("wave") or "sine", WAVES["sine"])
    gain = spec.get("gain", 0.3)
    samples: list[float] = []
    for freq in freqs:
        count = max(1, (sample_rate * ms) // 1000)
        for i in range(count):
            phase = 2 * math.pi * freq * (i / sample_rate)
            samples.append(shape(phase) * _envelope(i / count) * gain)
    return samples


def encode_wav(samples: list[float], sample_rate: int = 22050) -> bytes:
    """编码为 16-bit PCM 单声道 WAV（stdlib wave）。"""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"".join(
            int(max(-1.0, min(1.0, s)) * 32767).to_bytes(2, "little", signed=True)
            for s in samples
        ))
    return buffer.getvalue()


# 默认音效库：事件 → 音色（可被 dse.yml 的 config.sounds 覆盖）
PRESETS = {
    "scene-enter": {"freq": 523.25, "ms": 90, "wave": "sine", "gain": 0.22},            # C5
    "choice": {"freq": 659.25, "ms": 55, "wave": "square", "gain": 0.12},               # E5 短促
    "achievement": {"notes": [659.25, 783.99, 1046.5], "ms": 130, "wave": "sine"},      # 上行琶音
    "battle-hit": {"notes": [220, 165], "ms": 90, "wave": "saw", "gain": 0.2},          # 受击下行
    "battle-crit": {"notes": [330, 440, 587], "ms": 70, "wave": "square", "gain": 0.2}, # 暴击
    "battle-win": {"notes": [523.25, 659.25, 783.99, 1046.5], "ms": 120, "wave": "triangle"},
    "battle-lose": {"notes": [392, 349.23, 293.66], "ms": 220, "wave": "triangle"},     # 下行
    "game-over": {"notes": [392, 349.23, 293.66, 261.63], "ms": 260, "wave": "sine"},
    "hot-reload": {"notes": [880, 1174.66], "ms": 70, "wave": "sine", "gain": 0.15},
    "save": {"freq": 783.99, "ms": 100, "wave": "triangle", "gain": 0.18},
}

# 事件 → 音效名（订阅表；battle/end 按胜负分流）
HOOKS = {
    "scene/enter": "scene-enter",
    "choice/made": "choice",
    "achievement/unlock": "achievement",
    "save/applied": "save",
    "battle/hit": "battle-hit",
    "battle/crit": "battle-crit",
    "battle/end": lambda is_win: "battle-win" if is_win else "battle-lose",
    "engine/end": "game-over",
    "hot-reload/applied": "hot-reload",
}


def play_file(file: Path) -> None:
    """播放一个 WAV 文件（不阻塞；无播放器静默降级）。测试可 monkeypatch。"""
    if sys.platform == "win32":
        try:
            import winsound

            winsound.PlaySound(
                str(file),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            return
        except Exception:  # noqa: BLE001 — 无音频设备等：降级到子进程或静默
            pass
    command = {
        "darwin": ["afplay", str(file)],
        "linux": ["aplay", "-q", str(file)],
    }.get(sys.platform)
    if command:
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass  # 无播放器：静默降级，不打断游戏


class SoundService(Service):
    """音效服务（ctx.sound，可选插件）。"""

    name = "sound"
    inject = ()

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        # 静音优先级：环境变量 DSE_MUTE=1 > config.mute
        self.muted = os.environ.get("DSE_MUTE") == "1" or bool(self.config.get("mute"))
        self.sample_rate = int(self.config.get("sampleRate") or 22050)
        self.sounds = {**PRESETS, **(self.config.get("sounds") or {})}
        self.counter = 0
        self.files: list[Path] = []
        self.played = 0
        # DSE_SFX_DIR 供测试/隔离运行指定独立输出目录（避免多进程互相污染）
        env_dir = os.environ.get("DSE_SFX_DIR")
        self.dir = Path(self.config.get("dir") or env_dir or (Path(tempfile.gettempdir()) / "dse-core-sfx"))

    def setup(self) -> None:
        if not self.muted:
            self.dir.mkdir(parents=True, exist_ok=True)
        for event, mapping in HOOKS.items():
            self.ctx.on(event, self._make_handler(mapping))
        if self.muted:
            self.ctx.info("sound", "音效已静音（mute）")
        else:
            self.ctx.info("sound", f"registered {len(self.sounds)} sound effects")

    def _make_handler(self, mapping):
        def handler(*args):
            key = mapping(*args) if callable(mapping) else mapping
            self.play(key)

        return handler

    def play(self, key) -> bool:
        """播放一个音效（静音时不生成任何文件）。"""
        spec = self.sounds.get(key)
        if not spec:
            return False
        if self.muted:
            return True
        try:
            wav = encode_wav(synth(spec, self.sample_rate), self.sample_rate)
            file = self.dir / f"sfx-{self.counter}-{key}.wav"
            self.counter += 1
            file.write_bytes(wav)
            self.files.append(file)
            play_file(file)
            self.played += 1
            return True
        except OSError as exc:
            self.ctx.warn("sound", f'音效播放失败 "{key}": {exc}')
            return False

    def dispose(self) -> None:
        """清理生成的临时音频文件。"""
        for file in self.files:
            try:
                file.unlink()
            except OSError:
                pass
        self.files.clear()
