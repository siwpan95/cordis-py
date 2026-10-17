"""条件表达式 AST 白名单求值器。

Node 版用 ``new Function`` 求值条件表达式（非沙箱：内容包即可执行代码）。
Python 版内容包是**数据**，表达式统一走本模块 —— 只允许
比较 / 布尔 / 算术 / 字面量 / 下标 / 属性读取，禁调用、禁下划线名称与属性。

表达式语法为 Python 子集::

    'hp >= 10 and gold > 0'        'items.sword >= 1'  或  'items["sword"] >= 1'
    'not flags.door_locked'

命名空间约定：状态顶层键作为局部名，嵌套 dict 递归转 SimpleNamespace，
因此 ``items.sword`` 这类点路径写法与 Node 版内容保持一致。
求值失败（语法错误/不安全/运行期异常）抛异常，由调用方兜底为 False。
"""

from __future__ import annotations

import ast


class UnsafeExpression(ValueError):
    """表达式包含白名单外的语法。"""


_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
    ast.Name, ast.Load,
    ast.Constant,
    ast.Attribute,
    ast.Subscript, ast.Slice,
    ast.List, ast.Tuple, ast.Dict, ast.Set,
    ast.IfExp,
)


class _Namespace:
    """只读视图：同时支持点路径（items.sword）与下标（items['sword']）访问。"""

    __slots__ = ("_data",)

    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name: str):
        try:
            return _wrap(self._data[name])
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, key):
        return _wrap(self._data[key])

    def __contains__(self, key) -> bool:
        return key in self._data


def _wrap(value):
    if isinstance(value, dict):
        return _Namespace(value)
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


def build_namespace(data):
    """嵌套 dict -> _Namespace（供 items.sword / items['sword'] 两种写法）。"""
    return _wrap(data)


def _check(tree: ast.Expression) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpression(f"不允许的语法: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise UnsafeExpression(f"不允许的名称: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise UnsafeExpression(f"不允许的属性: {node.attr}")


def evaluate(expr, scope: dict):
    """求值表达式。scope 的键成为局部名（值经 build_namespace 转换）。

    任何失败都抛异常：UnsafeExpression / SyntaxError / NameError / ...
    """
    tree = ast.parse(str(expr), mode="eval")
    _check(tree)
    namespace = {}
    for key, value in scope.items():
        if isinstance(key, str) and not key.startswith("_"):
            namespace[key] = build_namespace(value)
    return eval(  # noqa: S307 — 输入已过 AST 白名单，builtins 已清空
        compile(tree, "<dse-condition>", "eval"),
        {"__builtins__": {}},
        namespace,
    )
