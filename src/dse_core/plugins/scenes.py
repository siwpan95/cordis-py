"""场景字典服务：把「场景」抽象为一个字典（dict[str, Scene]）。

移植自 dse-core(Node) plugins/scenes.js。

与 Node 版的安全差异：内容包是 YAML 数据文件（loader.load_pack_file），
**不需要 import 用户代码** —— 安全模型从「只运行可信内容」升级为
「数据 + AST 白名单求值」。validate() 只用于发现字段拼写错误等开发期问题。

双缓冲重建：先在临时字典上全量校验，通过后才原子替换 self.dict ——
保证「校验失败 = 旧字典毫发无损」。
"""

from __future__ import annotations

from pathlib import Path

from ..loader import load_pack_file
from ..runtime import Service
from ..schema import validate_pack


def validate_scenes(pack: dict, source: str = "<inline>") -> list[str]:
    """校验字典结构（引擎语义层），返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    for scene_id, scene in pack.items():
        at = f"{source}#{scene_id}"
        if not isinstance(scene, dict):
            errors.append(f"  - {at}: 场景必须是对象")
            continue
        if not isinstance(scene.get("text"), str):
            errors.append(f"  - {at}: 缺少 text 字段")
        choices = scene.get("choices")
        if choices is not None and not isinstance(choices, list):
            errors.append(f"  - {at}: choices 必须是数组")
        for i, choice in enumerate(choices or []):
            if not isinstance(choice, dict) or not isinstance(choice.get("text"), str):
                errors.append(f"  - {at}: 第 {i + 1} 个选项缺少 text")
    return errors


def find_dangling(scenes: dict) -> list[str]:
    """检查悬空 goto 引用与缺失 goto，返回错误列表（空 = 通过）。

    '@' 开头的特殊目标（如 @restart）免检。选项缺失 goto 也在此拦截：
    运行时引擎对无 goto 的选项不流转、重进当前场景 → onEnter 副作用重复执行。
    """
    dangling: list[str] = []
    for scene_id, scene in scenes.items():
        for i, choice in enumerate((scene or {}).get("choices") or []):
            target = choice.get("goto")
            if target is None:
                dangling.append(f"  - #{scene_id} 第 {i + 1} 个选项缺少 goto（选中后无法流转，会重放 onEnter）")
                continue
            if not str(target).startswith("@") and target not in scenes:
                dangling.append(f'  - #{scene_id} 第 {i + 1} 个选项 -> "{target}"')
    return dangling


class SceneService(Service):
    """场景字典服务（ctx.scenes）。"""

    name = "scenes"
    inject = ()

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.dict: dict[str, dict] = {}
        self.packs: list[str] = []
        self.loaded: dict[str, dict] = {}

    def setup(self) -> None:
        for rel in self.config.get("packs") or []:
            self.load(rel)
        self.rebuild()
        self.ctx.info("scenes", f"loaded {self.size} scenes from {len(self.packs)} pack(s)")

    def load(self, rel: str) -> dict:
        """加载一个内容包（同 ID 场景后者覆盖前者）。"""
        pack = self.import_pack(rel)
        self.loaded[rel] = pack
        if rel not in self.packs:
            self.packs.append(rel)
        return pack

    def import_pack(self, rel: str) -> dict:
        """读取并校验一个内容包文件；路径白名单：只加载工程内的包。"""
        path = self._resolve_inside(rel)
        _, scenes = load_pack_file(path)
        errors = validate_pack(scenes, source=rel) + validate_scenes(scenes, rel)
        if errors:
            raise ValueError(f"场景包 {rel} 校验失败:\n" + "\n".join(errors))
        return scenes

    def _resolve_inside(self, rel: str) -> Path:
        root = self.ctx.root.resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"内容包路径越出工程目录: {rel}")
        if not path.is_file():
            raise FileNotFoundError(f"内容包不存在: {rel}")
        return path

    def rebuild(self) -> bool:
        """按 packs 顺序重建场景字典（双缓冲：校验不过则旧字典毫发无损）。"""
        nxt: dict[str, dict] = {}
        for rel in self.packs:
            nxt.update(self.loaded.get(rel) or {})
        dangling = find_dangling(nxt)
        if dangling:
            raise ValueError("存在未定义的场景跳转:\n" + "\n".join(dangling))
        self.dict = nxt
        return True

    def reload(self, rel: str) -> bool:
        """热重载一个内容包：重新读取并重建字典（双缓冲，失败保留旧内容）。

        与 Node 版 scenes.js reload() 对应：先整体校验，通过才原子替换；
        任何一步失败都回滚内容缓存，保证「校验失败 = 旧字典毫发无损」。
        """
        if rel not in self.loaded:
            self.ctx.warn("scenes", f"reload skipped: 内容包 {rel} 不在配置中")
            return False
        previous = self.loaded[rel]
        try:
            pack = self.import_pack(rel)
        except (OSError, ValueError) as exc:
            self.ctx.error("scenes", f"reload rejected: {exc}（保留旧内容）")
            return False
        self.loaded[rel] = pack
        try:
            self.rebuild()
            return True
        except ValueError as exc:
            self.loaded[rel] = previous  # 回滚缓存，与字典保持一致
            self.ctx.error("scenes", f"reload rejected: {exc}（保留旧内容）")
            return False

    def get(self, scene_id: str) -> dict:
        scene = self.dict.get(scene_id)
        if scene is None:
            raise KeyError(f'场景 "{scene_id}" 不存在（共 {self.size} 个场景，用 dse scenes 查看）')
        return scene

    def has(self, scene_id: str) -> bool:
        return scene_id in self.dict

    @property
    def size(self) -> int:
        return len(self.dict)

    @property
    def ids(self) -> list[str]:
        return list(self.dict.keys())
