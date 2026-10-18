"""achievements / i18n 插件测试。"""

from dse_core.plugins.achievements import AchievementsService
from dse_core.plugins.i18n import I18nService
from dse_core.plugins.state import StateService
from dse_core.runtime import Context


def _ctx(root=".") -> Context:
    return Context(root=root, quiet=True)


# ------------------------------------------------------------ achievements


def _make_achievements() -> AchievementsService:
    ctx = _ctx()
    state = StateService(ctx, {"initial": {}})
    ctx.services["state"] = state
    from dse_core.plugins.console_io import ConsoleIO

    ctx.services["io"] = ConsoleIO(ctx, {})
    service = AchievementsService(ctx, {
        "list": [
            {"id": "wolf", "name": "屠狼者", "desc": "战胜独眼狼", "when": 'scene == "wolf-win"'},
            {"id": "rich", "name": "小富", "desc": "金币满十五", "when": "gold >= 15"},
        ]
    })
    ctx.services["achievements"] = service
    return service


def test_unlock_on_scene_enter():
    service = _make_achievements()
    service.setup()
    service._on_scene_enter("wolf-win", {})
    assert "wolf" in service.unlocked
    assert "rich" not in service.unlocked


def test_unlock_via_state_condition():
    service = _make_achievements()
    service.setup()
    service.ctx.state.set("gold", 20)
    service.check("anywhere")
    assert "rich" in service.unlocked


def test_unlock_is_idempotent(capsys):
    service = _make_achievements()
    service.setup()
    service.unlock("wolf")
    out1 = capsys.readouterr().out
    service.unlock("wolf")  # 第二次不重复解锁、不重复打印
    out2 = capsys.readouterr().out
    assert "屠狼者" in out1
    assert out2 == ""


def test_restore_filters_unknown_ids():
    service = _make_achievements()
    service.setup()
    service.restore(["wolf", "ghost-id"])
    assert service.unlocked == {"wolf"}


def test_command_intercept(capsys):
    service = _make_achievements()
    service.setup()
    result = service._on_command("achievements", [])
    assert result == {"type": "rerender"}
    assert "屠狼者" in capsys.readouterr().out
    # 非成就命令放行
    assert service._on_command("stats", []) is None


# ------------------------------------------------------------ i18n


def _make_i18n(tables=None, default="zh-CN") -> I18nService:
    ctx = _ctx()
    state = StateService(ctx, {"initial": {}})
    ctx.services["state"] = state
    from dse_core.plugins.console_io import ConsoleIO

    ctx.services["io"] = ConsoleIO(ctx, {})
    service = I18nService(ctx, {"locales": tables or {}, "defaultLocale": default})
    ctx.services["i18n"] = service
    return service


def test_translate_hit_and_miss():
    service = _make_i18n({"zh-CN": {"greet": "你好"}, "en-US": {"greet": "Hello"}})
    service.setup()
    assert service.translate("@greet@，世界") == "你好，世界"
    # 未命中原样保留并计入 misses
    assert service.translate("@missing@") == "@missing@"
    assert service.missing() == ["missing"]


def test_translate_noop_for_plain_text():
    service = _make_i18n({"zh-CN": {"greet": "你好"}})
    service.setup()
    assert service.translate("普通文本") == "普通文本"
    assert service.translate(123) == 123


def test_locale_priority(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    state = type("S", (), {"data": {"locale": "en-US"}})()
    state.get = lambda p: state.data.get(p)
    ctx.services["state"] = state
    service = I18nService(ctx, {"locales": {"zh-CN": {"g": "你好"}, "en-US": {"g": "Hello"}}})
    ctx.services["i18n"] = service
    assert service.locale() == "en-US"           # state.locale 优先
    monkeypatch.setenv("DSE_LOCALE", "zh-CN")
    assert service.locale() == "en-US"           # 仍以 state 为准
    state.data.pop("locale")
    assert service.locale() == "zh-CN"           # 回落环境变量
    monkeypatch.delenv("DSE_LOCALE")
    assert service.locale() == "zh-CN"           # 回落配置默认（恰好也是 zh-CN）


def test_lookup_falls_back_to_default_locale():
    service = _make_i18n({"zh-CN": {"g": "你好"}, "en-US": {"other": "x"}})
    service.setup()
    assert service.lookup("g", locale="en-US") == "你好"  # en-US 缺表 → 回落默认
    assert service.lookup("nope") is None


def test_lang_command(capsys):
    service = _make_i18n({"zh-CN": {"g": "你好"}, "en-US": {"g": "Hello"}})
    service.setup()
    # 查看
    assert service.handle("lang", []) == {"type": "rerender"}
    assert "当前语言" in capsys.readouterr().out
    # 切换
    result = service.handle("lang en-US", [])
    assert result == {"type": "rerender"}
    assert service.ctx.state.get("locale") == "en-US"
    # 未知语言
    assert service.handle("lang fr-FR", []) == {"type": "rerender"}
    assert "没有语言包" in capsys.readouterr().out
    # 非 lang 命令放行
    assert service.handle("stats", []) is None
