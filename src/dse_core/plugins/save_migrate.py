"""存档版本迁移（骨架）—— 内容改版时旧档不失效。

移植自 dse-core(Node) plugins/save-migrate.js。

问题：内容包会演进（场景改名、状态字段重命名），玩家手里的存档是旧结构。
做法：存档记录带 version；读档时按版本链逐级升级到当前版本，再交给引擎。

配置（dse.yml）::

    - id: save-migrate
      config:
        version: 2
        migrations:
          2: my_game.migrations   # 模块导出 migrate(record) -> record

骨架阶段不内置任何迁移，只提供机制与诊断；需要迁移时把函数挂进来即可，
引擎与 save 插件无需改动。
"""

from __future__ import annotations

import importlib

from ..runtime import Service


class SaveMigrateService(Service):
    """存档迁移服务（ctx['save-migrate']，可选插件）。"""

    name = "save-migrate"
    inject = ("state", "io")

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.version = int(self.config.get("version") or 1)
        self.migrations: dict[int, object] = {}

    def setup(self) -> None:
        for version, path in (self.config.get("migrations") or {}).items():
            try:
                module = importlib.import_module(str(path))
                fn = getattr(module, "migrate", None)
                if not callable(fn):
                    raise ValueError(f"模块 {path} 未导出 migrate 函数")
                self.migrations[int(version)] = fn
            except (ImportError, ValueError) as exc:
                self.ctx.warn("save-migrate", f"迁移 {version} 载入失败: {exc}")
        self.ctx.info("save-migrate", f"save version={self.version}, migrations={len(self.migrations)}")

    def stamp(self, record: dict) -> dict:
        """归档版本（写入存档时用）。"""
        return {**record, "version": self.version}

    def migrate(self, record: dict) -> dict:
        """把存档升级到当前版本，返回 {record, from, to, steps}。"""
        current = dict(record)
        frm = int(current.get("version") or 1)
        steps: list[int] = []
        for v in sorted(self.migrations):
            if v <= frm:
                continue
            before = current
            try:
                current = self.migrations[v](current) or current
            except Exception as exc:  # noqa: BLE001 — 单步失败保留迁移前状态，不连锁崩
                self.ctx.warn("save-migrate", f"迁移到 v{v} 失败: {exc}（保留迁移前状态）")
                current = before
                break
            steps.append(v)
            current["version"] = v
        if current.get("version") != self.version:
            current["version"] = self.version
        return {"record": current, "from": frm, "to": current["version"], "steps": steps}

    def needs_migration(self, record: dict) -> bool:
        """是否需要迁移（诊断/测试用）。"""
        return int(record.get("version") or 1) < self.version
