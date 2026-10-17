"""工程加载器：dse.yml + YAML 内容包 → 场景字典。

移植自 dse-core(Node) lib/dict.mjs。与 Node 版的差异：内容包从 ESM
模块改为 **YAML 数据文件**（pack 元数据 + scenes 字典同文件），因此不
需要 import 任何用户代码。

YAML 内容包结构::

    pack: { id: starter, name: 启程, entry: start }   # 元数据（可选）
    scenes:
      start: { title: ..., text: ..., choices: [...] }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .manifest import normalize_manifest


@dataclass
class LoadedProject:
    """一个已加载的引擎工程（dse.yml + 全部内容包合并结果）。"""

    root: Path
    dict: dict                       # 合并后的场景字典（同 ID 后者覆盖前者）
    ids: list                        # 场景 ID 列表（合并序）
    pack_files: list                 # 内容包相对路径列表（顺序即覆盖优先级）
    entry: str                       # 入口场景 ID
    manifests: list = field(default_factory=list)  # 各内容包的规范化 manifest


def load_yaml(path: str | Path) -> dict:
    """读取 YAML 文件；空文件返回 {}。"""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_plugin_config(manifest, plugin_id: str) -> dict:
    """从 dse.yml 插件清单里取出指定 id 的 config（找不到返回 {}）。"""
    entries = manifest if isinstance(manifest, list) else []
    for item in entries:
        if isinstance(item, dict) and item.get("id") == plugin_id:
            return item.get("config") or {}
    return {}


def load_pack_file(path: str | Path) -> tuple[dict, dict]:
    """读取一个 YAML 内容包 → (manifest_raw, scenes)。"""
    data = load_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"内容包 {path} 顶层必须是对象（pack / scenes 两个键）")
    scenes = data.get("scenes") or {}
    if not isinstance(scenes, dict):
        raise ValueError(f"内容包 {path} 的 scenes 必须是「场景 ID → 场景定义」的对象")
    return data.get("pack") or {}, scenes


def load_project(root: str | Path) -> LoadedProject:
    """加载整个工程：dse.yml + 全部内容包。"""
    root = Path(root)
    manifest = load_yaml(root / "dse.yml")
    if not isinstance(manifest, list):
        raise ValueError(f"{root / 'dse.yml'} 必须是插件条目列表")
    scenes_cfg = read_plugin_config(manifest, "scenes")
    engine_cfg = read_plugin_config(manifest, "engine")
    pack_files = list(scenes_cfg.get("packs") or [])

    merged: dict = {}
    manifests = []
    for rel in pack_files:
        path = (root / rel).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"内容包不存在: {rel}（相对于 {root}）")
        raw, pack_scenes = load_pack_file(path)
        manifests.append(normalize_manifest(raw, rel, pack_scenes))
        merged.update(pack_scenes)  # 同 ID 后者覆盖前者（与 scenes 插件叠加语义一致）

    return LoadedProject(
        root=root,
        dict=merged,
        ids=list(merged.keys()),
        pack_files=pack_files,
        entry=engine_cfg.get("entry") or "start",
        manifests=manifests,
    )


def scene_chars(scene: dict) -> int:
    """场景正文长度（title + text + 各选项文本），与校验器口径一致。"""
    choices = (scene or {}).get("choices") or []
    return (
        len((scene or {}).get("title") or "")
        + len((scene or {}).get("text") or "")
        + sum(len(c.get("text") or "") for c in choices)
    )
