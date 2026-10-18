"""P3 能力层插件测试：trade / diary / dialogue（确定性设计，无随机）。"""

from pathlib import Path

import pytest

from dse_core import play
from dse_core.plugins.diary import DiaryService
from dse_core.plugins.scenes import SceneService
from dse_core.plugins.state import StateService
from dse_core.plugins.console_io import ConsoleIO
from dse_core.runtime import Context

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ------------------------------------------------------------ trade（e2e，确定性）


def test_trade_full_cycle(monkeypatch, capsys):
    """进货 → 过夜 → 出货 → 收市结算：确定性行情，逐金可算。"""
    # day1: buy tea（进价 8，gold 20→12，stock 1）→ next → day2: sell tea（卖 10，+10）→ next → 收市
    monkeypatch.setenv("DSE_INPUT", "buy tea,next,sell tea,next")
    code = play(root=str(FIXTURES / "trade"))
    assert code == 0
    out = capsys.readouterr().out
    assert "进货：茶 ×1（-8 金）" in out
    assert "第 2 天，开市。" in out
    assert "出货：茶 ×1 @ 10 金（+10 金）" in out
    assert "收市" in out and "多出 2 金" in out   # 20 → 22，净赚 2
    assert "净赚 2 金" in out                      # 结算写入 tradeProfit 并插值


def test_trade_rejects_unknown_goods(monkeypatch, capsys):
    monkeypatch.setenv("DSE_INPUT", "buy wine,quit")
    code = play(root=str(FIXTURES / "trade"))
    assert code == 0
    out = capsys.readouterr().out
    assert "没有这种货：wine" in out
    assert "茶(tea)" in out                          # 附可交易列表


def test_trade_insufficient_gold(monkeypatch, capsys):
    monkeypatch.setenv("DSE_INPUT", "buy tea 99,quit")
    code = play(root=str(FIXTURES / "trade"))
    assert code == 0
    assert "金币不够" in capsys.readouterr().out


# ------------------------------------------------------------ dialogue（e2e）


def test_dialogue_ask_dedup_and_effect(monkeypatch, capsys):
    monkeypatch.setenv("DSE_INPUT", "ask 1,ask 1,ask 2,end")
    code = play(root=str(FIXTURES / "dialogue"))
    assert code == 0
    out = capsys.readouterr().out
    assert "【老者】今天天气不错。" in out
    assert "你已经问过了" in out                       # 重复问被挡
    assert "【老者】往事如烟。" in out
    assert "问过天气了吗：True" in out                 # topic.effect 生效


def test_dialogue_notes_budget_forces_end(monkeypatch, capsys):
    """notes=2：问满两个后第三个话题触发「注意点用尽」强制结束。"""
    monkeypatch.setenv("DSE_INPUT", "ask 1,ask 2,ask 3")
    code = play(root=str(FIXTURES / "dialogue"))
    assert code == 0
    out = capsys.readouterr().out
    assert "注意点用尽了" in out
    assert "对话告一段落" in out


# ------------------------------------------------------------ diary（e2e + 单元）


def test_diary_read_and_back(monkeypatch, capsys):
    """进厅中（记已读）→ 夜读 → 编号重读（只读）→ back 回厅中。"""
    monkeypatch.setenv("DSE_INPUT", "1,1,back")
    code = play(root=str(FIXTURES / "diary"))
    assert code == 0
    out = capsys.readouterr().out
    assert "可重读的篇目" in out
    assert "── 厅中 ──" in out                         # 重读渲染 title + text


def test_read_entry_does_not_mutate_state(tmp_path, capsys):
    """核心约束：重读只读渲染，绝不执行 onEnter / 不碰状态。"""
    ctx = Context(root=tmp_path, quiet=True)
    state = StateService(ctx, {"initial": {"gold": 5}})
    ctx.services["state"] = state
    scenes = SceneService(ctx, {})
    scenes.dict = {
        "hall": {"title": "厅中", "text": "你有 {gold} 金。", "onEnter": {"gold": -1}},
        "diary-scene": {"mode": "diary", "diary": {"onExit": "hall"}},
    }
    ctx.services["scenes"] = scenes
    ctx.services["io"] = ConsoleIO(ctx, {})
    service = DiaryService(ctx, {})
    ctx.services["diary"] = service

    service._on_scene_mode("diary-scene", scenes.dict["diary-scene"], "diary")
    service.mark_read("hall")
    before = state.snapshot()

    service.read_entry("hall")   # 重读：只渲染
    assert state.snapshot() == before                 # 状态毫发无损
    # 对照：正规进入场景才会执行 onEnter
    from dse_core.plugins.engine import EngineService

    engine = EngineService(ctx, {"entry": "hall"})
    ctx.services["engine"] = engine
    state.apply(scenes.dict["hall"]["onEnter"])
    assert state.get("gold") == 4                     # 进入才扣钱，重读不扣


def test_diary_entries_filter_deleted_scenes(tmp_path):
    """内容改版删掉的场景自动从可重读列表剔除。"""
    ctx = Context(root=tmp_path, quiet=True)
    state = StateService(ctx, {"initial": {}})
    ctx.services["state"] = state
    scenes = SceneService(ctx, {})
    scenes.dict = {"alive": {"text": "x"}}
    ctx.services["scenes"] = scenes
    ctx.services["io"] = ConsoleIO(ctx, {})
    service = DiaryService(ctx, {})
    ctx.services["diary"] = service
    state.set("diaryRead", ["alive", "deleted"])
    assert service.entries() == ["alive"]
