"""telemetry 埋点插件（P9，系统层）—— 玩家选择数据的采集端。

对标 2026 叙事分析工作流「选择埋点 → 路径可视化 → 迭代闭环」的采集层：
订阅引擎事件，JSONL 追加落盘；``dse analyze`` 命令消费产出路径分布报告。

采集事件（每行一个 JSON）：

- ``session/start``   会话开启（entry、引擎版本）
- ``scene/enter``     进入场景（scene、visits 计数）
- ``choice/made``     做出选择（scene、选项文本、once 键）
- ``engine/end``      到达结局（scene）
- ``session/stop``    会话结束（退出码）

安全与边界：

- 文件路径白名单：只允许写工程目录内（与 loader 同口径），拒绝越界路径。
- 追加模式打开 / 每行 fsync 前 flush —— 崩溃最多丢一行。
- 失败降级为 warn，绝不影响游戏主流程（埋点是旁观者）。
- 隐私：不落任何玩家输入原文之外的数据；文件留在玩家本机，由作者收集。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ..runtime import Service


class TelemetryService(Service):
    """埋点采集服务（ctx.telemetry）。"""

    name = "telemetry"
    inject = ()
    config_schema = {
        "properties": {
            "file": {"type": "str", "default": "telemetry.jsonl"},
        }
    }

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self._path: Path | None = None
        self._enabled = False

    def setup(self) -> None:
        self._enabled = False  # 重入安全：先复位，再按条件启用
        self._path = None
        # 环境变量优先：DSE_TELEMETRY=0 可一键关闭（玩家侧隐私开关）
        if os.environ.get("DSE_TELEMETRY", "1") in ("0", "false", "off"):
            self.ctx.info("telemetry", "disabled by DSE_TELEMETRY")
            return
        path = (self.ctx.root / self.config["file"]).resolve()
        root = self.ctx.root.resolve()
        if root not in path.parents and path != root:
            self.ctx.warn("telemetry", f"埋点文件必须在工程目录内，已禁用: {path}")
            return
        self._path = path
        self._enabled = True
        self.on("scene/enter", self._on_scene_enter)
        self.on("choice/made", self._on_choice_made)
        self.on("engine/end", self._on_engine_end)
        self.on("engine/stop", lambda: self._write("session/stop", {}))
        self._write("session/start", {"entry": self.config.get("entry")})

    def _write(self, kind: str, data: dict) -> None:
        if not self._enabled or self._path is None:
            return
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": kind,
            **data,
        }
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            self.ctx.warn("telemetry", f"落盘失败（已跳过）: {exc}")

    def _on_scene_enter(self, scene_id: str, scene: dict) -> None:
        visits = None
        try:
            visits = self.ctx.state.get(f"visits.{scene_id}")
        except Exception:  # noqa: BLE001 — 旁观者绝不影响主流程
            pass
        self._write("scene/enter", {"scene": scene_id, "visits": visits})

    def _on_choice_made(self, scene_id: str, choice: dict, effects: list) -> None:
        self._write("choice/made", {
            "scene": scene_id,
            "choice": str(choice.get("text", ""))[:80],
            "once": choice.get("once") or None,
        })

    def _on_engine_end(self, scene_id: str, scene: dict) -> None:
        self._write("engine/end", {"scene": scene_id})
