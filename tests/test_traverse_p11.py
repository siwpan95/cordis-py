"""P11 状态遍历测试：dse traverse / dse coverage。

这一层与 ``test_tools_p7.py`` 的 dse graph 测试是**互补**关系：
graph 测静态拓扑，本文件测「真的把引擎跑起来」之后的动态事实。
两者会不一致的地方（如条件恒假）正是 traverse 存在的理由，故专门覆盖。
"""

import json
from pathlib import Path

from dse_core.sdk import create_engine
from dse_core.traverse import coverage, traverse

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MINI = FIXTURES / "mini"
NARRATIVE = FIXTURES / "narrative"


def _ctx(root):
    return create_engine(root)


# ------------------------------------------------------------ traverse 基本

def test_traverse_reaches_all_endings_of_mini():
    """mini：三个选项里一个条件恒假，两条真路各到一个结局。"""
    ctx = _ctx(MINI)
    try:
        trace = traverse(ctx, entry="start")
        assert trace.errors == []
        assert trace.visited == {"start", "end-rich", "end-quiet"}
        assert trace.endings == {"end-rich", "end-quiet"}
    finally:
        ctx.dispose()


def test_traverse_edges_carry_kind_and_direction():
    """走过边必须记下 (from, to, kind)，kind 区分 choice/mode/call。"""
    ctx = _ctx(MINI)
    try:
        trace = traverse(ctx, entry="start")
        assert ("start", "end-rich", "choice") in trace.edges
        assert ("start", "end-quiet", "choice") in trace.edges
    finally:
        ctx.dispose()


def test_traverse_is_silent():
    """遍历不该把剧情刷到 stdout（render 的副作用要被吞掉）。"""
    import io
    import contextlib

    buf = io.StringIO()
    ctx = _ctx(MINI)
    try:
        with contextlib.redirect_stdout(buf):
            traverse(ctx, entry="start")
    finally:
        ctx.dispose()
    assert buf.getvalue() == ""


def test_traverse_restores_state_after_run():
    """遍历会反复 reset/restore 状态，结束后不得污染调用方。"""
    ctx = _ctx(MINI)
    try:
        state = ctx.services["state"]
        before = state.snapshot()
        traverse(ctx, entry="start")
        assert state.snapshot() == before
    finally:
        ctx.dispose()


# ------------------------------------------------------------ 动态 vs 静态

def test_traverse_catches_dead_end_from_always_false_condition(tmp_path):
    """静态图合法但动态走不通 —— traverse 必须报错，这才是它相对 dse check 的增量。

    内容：唯一选项带 ``if: 'gold >= 10'``，而初始 gold=0。
    dse check / graph 只会看到一条合法的 start -> shop 边；
    traverse 跑起来发现条件恒假 → 玩家卡死在 start。
    """
    content = tmp_path / "content"
    content.mkdir()
    (tmp_path / "dse.yml").write_text(
        "- { id: scenes, name: scenes, config: { packs: [content/pack.yml] } }\n"
        "- { id: state, name: state, config: { initial: { gold: 0 } } }\n"
        "- { id: io, name: io }\n"
        "- { id: engine, name: engine, config: { entry: start } }\n",
        encoding="utf-8",
    )
    (content / "pack.yml").write_text(
        "pack: { id: t, name: 测, version: 0.1.0, entry: start }\n"
        "scenes:\n"
        "  start:\n"
        "    text: 起点\n"
        "    choices:\n"
        "      - { text: 买剑, if: 'gold >= 10', goto: shop }\n"
        "  shop:\n"
        "    text: 商店\n",
        encoding="utf-8",
    )
    ctx = create_engine(tmp_path)
    try:
        trace = traverse(ctx, entry="start")
        assert len(trace.errors) == 1
        assert trace.errors[0]["scene"] == "start"
        assert "无可用去向" in trace.errors[0]["error"]
        assert "shop" not in trace.visited
    finally:
        ctx.dispose()


def test_dangling_goto_is_rejected_at_load_time(tmp_path):
    """悬空跳转在**装载阶段**就被 SceneService 拦下（双缓冲校验），
    根本到不了 traverse —— 这比让 traverse 报错更早、更省事。

    保留本测试是为了钉住这条防线：如果哪天装载校验被削弱，
    traverse 会退回成「唯一的防线」，行为就会变。
    """
    content = tmp_path / "content"
    content.mkdir()
    (tmp_path / "dse.yml").write_text(
        "- { id: scenes, name: scenes, config: { packs: [content/pack.yml] } }\n"
        "- { id: state, name: state, config: { initial: {} } }\n"
        "- { id: io, name: io }\n"
        "- { id: engine, name: engine, config: { entry: start } }\n",
        encoding="utf-8",
    )
    (content / "pack.yml").write_text(
        "pack: { id: t, name: 测, version: 0.1.0, entry: start }\n"
        "scenes:\n"
        "  start:\n"
        "    text: 起点\n"
        "    choices:\n"
        "      - { text: 去幽灵场景, goto: nowhere }\n",
        encoding="utf-8",
    )
    import pytest

    with pytest.raises(ValueError, match="未定义的场景跳转"):
        create_engine(tmp_path)


# ------------------------------------------------------------ 循环与截断

def test_traverse_terminates_on_looping_content(tmp_path):
    """@loop / 自环内容必须靠 max_revisit 收敛，不能无限递归。"""
    content = tmp_path / "content"
    content.mkdir()
    (tmp_path / "dse.yml").write_text(
        "- { id: scenes, name: scenes, config: { packs: [content/pack.yml] } }\n"
        "- { id: state, name: state, config: { initial: {} } }\n"
        "- { id: io, name: io }\n"
        "- { id: engine, name: engine, config: { entry: start } }\n",
        encoding="utf-8",
    )
    (content / "pack.yml").write_text(
        "pack: { id: t, name: 测, version: 0.1.0, entry: start }\n"
        "scenes:\n"
        "  start:\n"
        "    text: 起点\n"
        "    choices:\n"
        "      - { text: 再走一遍, goto: start }\n"
        "      - { text: 结束, goto: done }\n"
        "  done:\n"
        "    text: 完\n",
        encoding="utf-8",
    )
    ctx = create_engine(tmp_path)
    try:
        trace = traverse(ctx, entry="start", max_revisit=2)
        assert trace.truncated, "自环内容应当记录截断，而不是无限跑"
        assert "done" in trace.endings
    finally:
        ctx.dispose()


# ------------------------------------------------------------ coverage 门

def test_coverage_passes_when_all_endings_traversed():
    ctx = _ctx(MINI)
    try:
        trace = traverse(ctx, entry="start")
        report = coverage(ctx.services["scenes"], trace)
        assert report.ok
        assert report.missing == []
        assert all("T" in report.sources[e] for e in report.endings)
    finally:
        ctx.dispose()


def test_coverage_flags_unreachable_ending(tmp_path):
    """孤儿结局（没有任何路径可达）必须被覆盖门判失败。"""
    content = tmp_path / "content"
    content.mkdir()
    (tmp_path / "dse.yml").write_text(
        "- { id: scenes, name: scenes, config: { packs: [content/pack.yml] } }\n"
        "- { id: state, name: state, config: { initial: {} } }\n"
        "- { id: io, name: io }\n"
        "- { id: engine, name: engine, config: { entry: start } }\n",
        encoding="utf-8",
    )
    (content / "pack.yml").write_text(
        "pack: { id: t, name: 测, version: 0.1.0, entry: start }\n"
        "scenes:\n"
        "  start:\n"
        "    text: 起点\n"
        "    choices:\n"
        "      - { text: 走, goto: a }\n"
        "  a:\n"
        "    text: A\n"
        "  orphan:\n"
        "    text: 没人能到这里\n",
        encoding="utf-8",
    )
    ctx = create_engine(tmp_path)
    try:
        trace = traverse(ctx, entry="start")
        report = coverage(ctx.services["scenes"], trace)
        assert not report.ok
        assert report.missing == ["orphan"]
    finally:
        ctx.dispose()


def test_coverage_accepts_e2e_source():
    """--e2e 声明的结局算有来源（E），即便 traverse 走不到。"""
    ctx = _ctx(MINI)
    try:
        trace = traverse(ctx, entry="start")
        # 假装 end-quiet 只有 e2e 覆盖：把 T 来源抹掉
        trace.endings.discard("end-quiet")
        report = coverage(ctx.services["scenes"], trace, e2e_endings=["end-quiet"])
        assert report.ok
        assert report.sources["end-quiet"] == ["E"]
    finally:
        ctx.dispose()


# ------------------------------------------------------------ CLI 契约

def test_cli_traverse_json_contract(capsys):
    from dse_core.cli import main

    code = main(["traverse", "--root", str(MINI), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"visited", "edges", "endings", "errors", "paths", "truncated"}
    assert "end-rich" in payload["endings"]


def test_cli_coverage_exit_code_one_on_missing(tmp_path, capsys):
    """门禁契约：有结局缺来源 → 退出码 1（CI 靠这个拦）。"""
    content = tmp_path / "content"
    content.mkdir()
    (tmp_path / "dse.yml").write_text(
        "- { id: scenes, name: scenes, config: { packs: [content/pack.yml] } }\n"
        "- { id: state, name: state, config: { initial: {} } }\n"
        "- { id: io, name: io }\n"
        "- { id: engine, name: engine, config: { entry: start } }\n",
        encoding="utf-8",
    )
    (content / "pack.yml").write_text(
        "pack: { id: t, name: 测, version: 0.1.0, entry: start }\n"
        "scenes:\n"
        "  start:\n"
        "    text: 起点\n"
        "    choices:\n"
        "      - { text: 走, goto: a }\n"
        "  a:\n"
        "    text: A\n"
        "  orphan:\n"
        "    text: 孤儿结局\n",
        encoding="utf-8",
    )
    from dse_core.cli import main

    assert main(["coverage", "--root", str(tmp_path)]) == 1
    # --e2e 豁免后转为 0
    assert main(["coverage", "--root", str(tmp_path), "--e2e", "orphan"]) == 0


def test_cli_traverse_exit_code_one_on_error(tmp_path):
    """traverse 发现无可用去向 → 退出码 1。"""
    content = tmp_path / "content"
    content.mkdir()
    (tmp_path / "dse.yml").write_text(
        "- { id: scenes, name: scenes, config: { packs: [content/pack.yml] } }\n"
        "- { id: state, name: state, config: { initial: { gold: 0 } } }\n"
        "- { id: io, name: io }\n"
        "- { id: engine, name: engine, config: { entry: start } }\n",
        encoding="utf-8",
    )
    (content / "pack.yml").write_text(
        "pack: { id: t, name: 测, version: 0.1.0, entry: start }\n"
        "scenes:\n"
        "  start:\n"
        "    text: 起点\n"
        "    choices:\n"
        "      - { text: 买, if: 'gold >= 10', goto: shop }\n"
        "  shop:\n"
        "    text: 商店\n",
        encoding="utf-8",
    )
    from dse_core.cli import main

    assert main(["traverse", "--root", str(tmp_path)]) == 1


# ------------------------------------------------------------ 真实内容回归

def test_traverse_on_example_project():
    """包内示例工程（正式内容）必须零错误、结局全覆盖 —— 这是发布前的门禁。"""
    ctx = create_engine()
    try:
        trace = traverse(ctx, entry="start", seed=42)
        assert trace.errors == []
        report = coverage(ctx.services["scenes"], trace)
        assert report.ok, f"示例工程有结局缺来源: {report.missing}"
    finally:
        ctx.dispose()
