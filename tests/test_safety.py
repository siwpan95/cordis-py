"""safety.py 测试 —— AST 白名单求值器（安全模型的核心赌注，重点覆盖）。"""

import pytest

from dse_core.safety import UnsafeExpression, evaluate

SCOPE = {
    "hp": 20,
    "gold": 5,
    "items": {"sword": 1, "potion": 3},
    "flags": {"door_locked": False},
    "name": "旅人",
}


def test_comparison_and_bool():
    assert evaluate("hp >= 10 and gold > 0", SCOPE) is True
    assert evaluate("hp < 10 or gold > 0", SCOPE) is True
    assert evaluate("not flags.door_locked", SCOPE) is True


def test_dotted_path_attribute_access():
    # items.sword 点路径与 Node 版内容写法保持一致
    assert evaluate("items.sword >= 1", SCOPE) is True
    assert evaluate("items.sword == 1 and items.potion == 3", SCOPE) is True


def test_arithmetic():
    assert evaluate("hp - 5", SCOPE) == 15
    assert evaluate("gold * 2 + 1", SCOPE) == 11


def test_subscript_and_literal():
    assert evaluate("items['sword'] == 1", SCOPE) is True
    assert evaluate("name == '旅人'", SCOPE) is True
    assert evaluate("1 in [1, 2]", SCOPE) is True


def test_reject_calls():
    with pytest.raises(UnsafeExpression):
        evaluate("__import__('os')", SCOPE)
    with pytest.raises(UnsafeExpression):
        evaluate("len(items)", SCOPE)


def test_reject_dunder_attribute():
    with pytest.raises(UnsafeExpression):
        evaluate("hp.__class__", SCOPE)
    with pytest.raises(UnsafeExpression):
        evaluate("name.__len__()", SCOPE)


def test_reject_underscore_name():
    with pytest.raises(UnsafeExpression):
        evaluate("_private > 0", SCOPE)


def test_syntax_error_propagates():
    with pytest.raises(Exception):
        evaluate("hp >=", SCOPE)


def test_unknown_name_raises():
    with pytest.raises(Exception):
        evaluate("missing_var > 0", SCOPE)
