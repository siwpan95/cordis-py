"""内容包元数据（manifest）：规范化 / 校验。

移植自 dse-core(Node) lib/registry.mjs 的纯逻辑部分（ESM 动态 import
由 loader 接管，这里只保留 manifest 语义）。

内容包约定（YAML，一个文件 = 一个包）::

    pack:                        # 元数据（可选，缺省从文件推导）
      id: starter
      name: 启程
      version: 0.1.0
      entry: start               # 本包推荐入口（缺省取第一个场景）
      modes: [battle]            # 用到了哪些 scene.mode
      requires:
        plugins: [combat]        # 需要哪些能力插件接管
        state: [gold]            # 需要 state.initial 预声明哪些顶层字段
    scenes:                      # 场景字典本体
      start: { ... }
"""

from __future__ import annotations

import re
from pathlib import Path

from .modes import mode_names

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


def strip_ext(file: str) -> str:
    """取文件名去扩展名（manifest id 的缺省值）。"""
    return Path(file).stem


def normalize_manifest(raw: dict | None, file: str, scenes: dict | None = None) -> dict:
    """补齐 manifest 缺省字段（id 取文件名，entry 取首个场景，modes 自动探测）。"""
    raw = raw or {}
    scenes = scenes or {}
    ids = list(scenes.keys())
    fallback_id = str(raw.get("id") or strip_ext(file))
    modes = set(raw.get("modes") or [])
    for scene in scenes.values():
        if isinstance(scene, dict) and scene.get("mode"):
            modes.add(scene["mode"])
    return {
        "id": fallback_id,
        "name": raw.get("name") or fallback_id,
        "version": raw.get("version") or "0.0.0",
        "entry": raw.get("entry") or (ids[0] if ids else None),
        "description": raw.get("description") or "",
        "author": raw.get("author") or "",
        "modes": sorted(modes),
        "requires": {
            "plugins": list((raw.get("requires") or {}).get("plugins") or []),
            "state": list((raw.get("requires") or {}).get("state") or []),
        },
        "scenes": len(ids),
    }


def validate_manifest(manifest) -> list[str]:
    """校验 manifest，返回问题列表（空列表 = 合法）。"""
    if not isinstance(manifest, dict):
        return ["manifest 不是对象"]
    problems: list[str] = []
    if not _ID_RE.match(str(manifest.get("id") or "")):
        problems.append(f'id "{manifest.get("id")}" 不符合命名规范（小写字母开头，仅 a-z 0-9 _ -）')
    if manifest.get("version") is not None and not _SEMVER_RE.match(str(manifest["version"])):
        problems.append(f'version "{manifest["version"]}" 不是语义化版本')
    known = mode_names()
    for mode in manifest.get("modes") or []:
        if mode not in known:
            problems.append(f'引用了未注册的模式 "{mode}"')
    return problems
