"""P10 运行时深水区测试：isolate 隔离域 / reload_many 批量热更 / i18n-extract。"""

from pathlib import Path

import pytest

from dse_core.cli import main
from dse_core.loader import load_yaml
from dse_core.runtime import Context, Service

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini"


class Counter(Service):
    name = "counter"
    inject = ()

    def setup(self):
        self.n = 0


class Dependent(Service):
    name = "dependent"
    inject = ("counter",)

    def setup(self):
        self.via = self.ctx.counter  # 隔离域链式解析的探针


def make_ctx():
    ctx = Context(root=".", quiet=True)
    ctx.plugin(Counter)
    return ctx.start()


# ------------------------------------------------------------ isolate

def test_isolate_independent_service_instance():
    root = make_ctx()
    child = root.isolate("counter")
    child.plugin(Counter)
    child.start()
    assert child.counter is not root.counter          # 同名不同实例
    child.counter.n = 99
    assert root.counter.n == 0                        # 互不干扰
    root.dispose()


def test_isolate_non_isolated_service_falls_through():
    root = make_ctx()

    class Extra(Service):
        name = "extra"

    root.plugin(Extra)
    # root 已 start 过，补挂 extra：重建一个含两插件的根
    root2 = Context(root=".", quiet=True)
    root2.plugin(Counter)
    root2.plugin(Extra)
    root2.start()
    child = root2.isolate("counter")
    child.plugin(Counter)
    child.start()
    assert child.extra is root2.extra                 # 未隔离服务沿父链解析
    assert child.counter is not root2.counter
    root2.dispose()


def test_isolate_isolated_service_not_started_loud():
    root = make_ctx()
    child = root.isolate("counter")
    with pytest.raises(AttributeError):
        _ = child.counter  # 隔离名单内但子域未注册 → 不穿透父域，响亮报错
    root.dispose()


def test_isolate_inject_resolves_via_realm():
    root = make_ctx()
    child = root.isolate("counter")
    child.plugin(Counter)
    child.plugin(Dependent)
    child.start()
    assert child.services["dependent"].via is child.counter  # inject 解析到子域实例
    root.dispose()


def test_isolate_shared_event_bus():
    root = make_ctx()
    child = root.isolate("counter")
    hits = []
    child.on("evt", lambda: hits.append("child-registered"))
    root.emit("evt")  # 子域注册、根域触发 —— 事件全局共享
    assert hits == ["child-registered"]
    root.dispose()


def test_inspect_aggregates_children():
    root = make_ctx()
    child = root.isolate("counter")
    child.plugin(Counter)
    child.start()
    snap = root.inspect()
    realm_entries = [e for e in snap if e.get("realm")]
    assert len(realm_entries) == 1 and realm_entries[0]["name"] == "counter"
    root.dispose()


# ------------------------------------------------------------ reload_many 批量热更

def test_reload_many_single_rebuild(tmp_path):
    # 两包工程：同时变更，reload_many 一次 rebuild 生效
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "a.yml").write_text(
        "scenes:\n  a1:\n    text: A\n    choices:\n      - { text: go, goto: b1 }\n",
        encoding="utf-8")
    (tmp_path / "content" / "b.yml").write_text(
        "scenes:\n  b1:\n    text: B\n", encoding="utf-8")
    (tmp_path / "dse.yml").write_text(
        "- id: scenes\n  config:\n    packs: [./content/a.yml, ./content/b.yml]\n",
        encoding="utf-8")
    from dse_core import create_engine
    ctx = create_engine(tmp_path)
    scenes_svc = ctx.scenes
    assert "a1" in scenes_svc.dict and "b1" in scenes_svc.dict

    # 同时改两包：a 加场景 a2 指向 b 新增的 b2
    (tmp_path / "content" / "a.yml").write_text(
        "scenes:\n  a1:\n    text: A\n    choices:\n      - { text: go, goto: b2 }\n  a2:\n    text: A2\n",
        encoding="utf-8")
    (tmp_path / "content" / "b.yml").write_text(
        "scenes:\n  b1:\n    text: B\n  b2:\n    text: B2\n", encoding="utf-8")
    results = scenes_svc.reload_many(["./content/a.yml", "./content/b.yml"])
    assert results == {"./content/a.yml": True, "./content/b.yml": True}
    assert "b2" in scenes_svc.dict
    ctx.dispose()


def test_reload_many_rollback_on_combined_dangling(tmp_path):
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "a.yml").write_text(
        "scenes:\n  a1:\n    text: A\n    choices:\n      - { text: go, goto: b1 }\n",
        encoding="utf-8")
    (tmp_path / "content" / "b.yml").write_text(
        "scenes:\n  b1:\n    text: B\n", encoding="utf-8")
    (tmp_path / "dse.yml").write_text(
        "- id: scenes\n  config:\n    packs: [./content/a.yml, ./content/b.yml]\n",
        encoding="utf-8")
    from dse_core import create_engine
    ctx = create_engine(tmp_path)
    scenes_svc = ctx.scenes

    # a 改成指向幽灵场景 → 单包校验过但组合悬空 → 整体回滚
    (tmp_path / "content" / "a.yml").write_text(
        "scenes:\n  a1:\n    text: A\n    choices:\n      - { text: go, goto: ghost }\n",
        encoding="utf-8")
    results = scenes_svc.reload_many(["./content/a.yml"])
    assert results["./content/a.yml"] is False
    # 旧内容毫发无损
    assert scenes_svc.dict["a1"]["choices"][0]["goto"] == "b1"
    ctx.dispose()


def test_reload_many_unknown_pack_skipped(tmp_path):
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "a.yml").write_text("scenes:\n  a1:\n    text: A\n", encoding="utf-8")
    (tmp_path / "dse.yml").write_text(
        "- id: scenes\n  config:\n    packs: [./content/a.yml]\n", encoding="utf-8")
    from dse_core import create_engine
    ctx = create_engine(tmp_path)
    results = ctx.scenes.reload_many(["./content/ghost.yml"])
    assert results["./content/ghost.yml"] is False
    ctx.dispose()


# ------------------------------------------------------------ i18n-extract

def test_i18n_extract_generates_table(tmp_path, capsys):
    code = main(["i18n-extract", "--root", str(FIXTURE), "--locale", "en-US"])
    assert code == 0
    out = capsys.readouterr().out
    assert "已提取" in out
    table_file = FIXTURE / "i18n" / "en-US.yml"
    assert table_file.is_file()
    table = load_yaml(table_file)
    assert table["start.text"] == "你有 {gold} 金币，HP {hp}。"
    assert "end-rich.title" in table
    table_file.unlink()
    table_file.parent.rmdir()


def test_i18n_extract_preserves_translations(tmp_path, capsys):
    i18n_dir = FIXTURE / "i18n"
    i18n_dir.mkdir(exist_ok=True)
    table_file = i18n_dir / "en-US.yml"
    # 预置一份「已翻译」的表
    table_file.write_text("start.text: 'You have {gold} gold.'\nold.key: 'Orphan'\n", encoding="utf-8")
    code = main(["i18n-extract", "--root", str(FIXTURE), "--locale", "en-US"])
    assert code == 0
    capsys.readouterr()
    text = table_file.read_text(encoding="utf-8")
    table = load_yaml(table_file)
    assert table["start.text"] == "You have {gold} gold."  # 已译值不被原文覆盖
    assert "old.key" in text and "已下线的 key" in text     # 孤儿进注释块不丢
    table_file.unlink()
    table_file.parent.rmdir()


def test_i18n_extract_skips_keyed_text(tmp_path, capsys):
    # 已用 @key@ 接管的内容不重复提取
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "k.yml").write_text(
        "scenes:\n  s1:\n    text: '@s1.text@'\n    choices:\n      - { text: 写死的, goto: s2 }\n  s2:\n    text: 目标\n",
        encoding="utf-8")
    (tmp_path / "dse.yml").write_text(
        "- id: scenes\n  config:\n    packs: [./content/k.yml]\n- id: state\n- id: io\n- id: engine\n  config: { entry: s1 }\n",
        encoding="utf-8")
    code = main(["i18n-extract", "--root", str(tmp_path), "--locale", "fr"])
    assert code == 0
    capsys.readouterr()
    table = load_yaml(tmp_path / "i18n" / "fr.yml")
    assert "s1.text" not in table          # @key@ 已接管 → 跳过
    assert table["s1.choices.0"] == "写死的"
