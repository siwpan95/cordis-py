"""存档/读档插件 —— 「不改引擎代码，用事件扩展引擎能力」的示范。

移植自 dse-core(Node) plugins/save.js（含 save-migrate 集成，比内容仓库
vendored 的旧版多版本盖章与迁移）。

安全约束（全检报告 #6）：
- slot 白名单 /^[\\w.\\-]{1,64}$/ —— 防路径遍历
- resolve 后断言仍在存档目录内 —— 双保险
- 写入走 temp + os.replace —— 原子落盘，避免存档截断
- 读档做结构校验 + scenes.has() 兜底 —— 坏档与内容改版都不让游戏崩
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from ..runtime import Service

_SLOT_PATTERN = re.compile(r"^[\w.\-]{1,64}$")


class SaveService(Service):
    """存档服务（ctx.save，可选插件）。"""

    name = "save"
    # scenes 用于读档时校验场景是否仍存在；achievements 用于解锁列表随档持久化
    inject = ("state", "engine", "io", "scenes", "achievements")

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        # 目录基准用 ctx 根（锚定项目根），而非 cwd：从任意目录跑都读写同一份存档。
        # DSE_SAVE_DIR 可覆盖——安装态内容项目（root 在 site-packages 里）用它把存档
        # 导到用户数据目录，避免写安装目录。
        env_dir = os.environ.get("DSE_SAVE_DIR")
        self.dir = (
            Path(env_dir) if env_dir else self.ctx.root / (self.config.get("dir") or "./saves")
        ).resolve()

    def setup(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.on("engine/command", self.handle)
        self.ctx.info("save", f"存档目录 {self.dir}")

    # ------------------------------------------------------------ 命令

    def handle(self, line: str, choices: list):
        parts = line.split()
        command = parts[0].lower() if parts else ""
        rest = parts[1:]
        if command in ("save", "存"):
            slot = rest[0] if rest else "auto"
            try:
                self.save(slot)
                self.ctx.io.print(f"  已保存到存档位 {slot}")
            except (OSError, ValueError) as exc:
                self.ctx.io.print(f"  保存失败：{exc}")
            return {"type": "rerender"}
        if command in ("load", "读"):
            slot = rest[0] if rest else "auto"
            ok = self.load(slot)
            return {"type": "scene", "id": self.ctx.engine.current} if ok else {"type": "rerender"}
        if command in ("slots", "档"):
            try:
                slots = self.list()
                self.ctx.io.print(f"  存档位: {', '.join(slots)}" if slots else "  （暂无存档）")
            except OSError as exc:
                self.ctx.io.print(f"  读取存档列表失败：{exc}")
            return {"type": "rerender"}
        return None  # 放行给后续监听器

    # ------------------------------------------------------------ 存取

    def slot_file(self, slot: str) -> Path:
        """存档位 → 文件路径；白名单与越界双重校验。"""
        if not isinstance(slot, str) or not _SLOT_PATTERN.match(slot):
            raise ValueError("存档位名称非法（只允许字母、数字、点、下划线、连字符，长度 1-64）")
        file = (self.dir / f"{slot}.json").resolve()
        if file != self.dir and self.dir not in file.parents:
            raise ValueError("存档路径越界")
        return file

    def migrator(self):
        """取存档迁移服务（可选插件）；未启用时返回 None，行为与迁移机制引入前一致。

        刻意不写进 inject —— 否则内容仓库若不注册 save-migrate，本插件会因
        依赖未满足而永不启动，等于存档功能凭空消失。可选增强就用可选方式取。
        """
        service = self.ctx.services.get("save-migrate")
        return service if service is not None and hasattr(service, "migrate") else None

    def save(self, slot: str) -> dict:
        file = self.slot_file(slot)
        record = {
            "slot": slot,
            "scene": self.ctx.engine.current,
            "state": self.ctx.state.snapshot(),
            "savedAt": datetime.now(timezone.utc).isoformat(),
            # 成就解锁随档持久化（审计 F10）
            "achievements": sorted(self.ctx.achievements.unlocked),
        }
        migrator = self.migrator()
        if migrator:
            record["version"] = migrator.version
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = file.parent / (file.name + ".tmp")
        try:
            tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, file)  # 原子替换：避免写一半中断导致存档截断
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        self.ctx.emit("save/applied", slot, record)
        return record

    def load(self, slot: str) -> bool:
        """读档：白名单 + 结构校验 + 版本迁移 + 场景存在性兜底，任何失败只提示不崩溃。"""
        try:
            file = self.slot_file(slot)
            record = json.loads(file.read_text(encoding="utf-8"))

            problems = self.validate_record(record)
            if problems:
                raise ValueError(f"存档格式不合法：{'；'.join(problems)}")

            # 存档版本迁移：未启用 save-migrate 时恒等通过，行为与引入前一致
            migrator = self.migrator()
            if migrator and migrator.needs_migration(record):
                result = migrator.migrate(record)
                record = result["record"]
                self.ctx.io.print(f"  存档已从 v{result['from']} 迁移到 v{result['to']}")

            if not self.ctx.scenes.has(record["scene"]):
                # 内容改版后存档指向的场景可能已删除：回退入口场景，不让游戏死掉
                fallback = (
                    self.ctx.engine.entry
                    or self.ctx.engine.config.get("entry")
                    or (self.ctx.scenes.ids[0] if self.ctx.scenes.ids else None)
                )
                self.ctx.io.print(f'  存档场景 "{record["scene"]}" 已不存在，改为从 "{fallback}" 开始')
                record["scene"] = fallback

            self.ctx.state.restore(record["state"])
            # 读档恢复成就解锁（内容改版后无效 id 由 achievements.restore 过滤）
            self.ctx.achievements.restore(record.get("achievements"))
            self.ctx.engine.goto(record["scene"])
            self.ctx.io.print(f"  已读取存档位 {slot}（场景: {record['scene']}）")
            return True
        except FileNotFoundError:
            self.ctx.io.print(f"  读取存档 {slot} 失败: 存档不存在")
            return False
        except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
            self.ctx.io.print(f"  读取存档 {slot} 失败: {exc}")
            return False

    def validate_record(self, record) -> list[str]:
        """存档记录结构校验，返回问题列表（空 = 合法）。"""
        if not isinstance(record, dict):
            return ["存档内容不是对象"]
        problems: list[str] = []
        if not isinstance(record.get("scene"), str) or not record["scene"]:
            problems.append("缺少 scene 字段")
        if not isinstance(record.get("state"), dict):
            problems.append("state 字段不是对象")
        # 成就字段可选（旧档无），但一旦出现必须是字符串数组
        achievements = record.get("achievements")
        if achievements is not None and (
            not isinstance(achievements, list)
            or not all(isinstance(x, str) for x in achievements)
        ):
            problems.append("achievements 字段不是字符串数组")
        return problems

    def list(self) -> list[str]:
        """列出全部存档位（排序）。"""
        if not self.dir.is_dir():
            return []
        slots = [f.stem for f in self.dir.glob("*.json")]
        return sorted(s for s in slots if _SLOT_PATTERN.match(s))
