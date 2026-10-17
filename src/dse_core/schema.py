"""场景字典 JSON Schema 校验。

schema/scene.schema.json 从 Node 版原样复制；运行时结构校验口径与 Node 的
plugins/scenes.js validate() 对齐（schema 管结构，validate 管引擎语义，
两者互补）。
"""

from __future__ import annotations

import json
from importlib import resources

from jsonschema import Draft7Validator

_SCHEMA: dict | None = None


def scene_schema() -> dict:
    """加载随包发布的 scene.schema.json（懒加载 + 缓存）。"""
    global _SCHEMA
    if _SCHEMA is None:
        traversable = resources.files("dse_core").joinpath("schema/scene.schema.json")
        with traversable.open(encoding="utf-8") as f:
            _SCHEMA = json.load(f)
    return _SCHEMA


def validator() -> Draft7Validator:
    return Draft7Validator(scene_schema())


def validate_pack(pack: dict, source: str = "<inline>") -> list[str]:
    """按 Schema 校验场景字典，返回人类可读的错误列表（空 = 通过）。"""
    errors: list[str] = []
    for error in validator().iter_errors(pack):
        path = "/".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"  - {source} {path}: {error.message}")
    return errors
