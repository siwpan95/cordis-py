"""引擎端到端测试：脚本输入（DSE_INPUT）无交互跑完整条线路。

战斗用例确定性设计：假人 2 血 / 0 攻，玩家 20 血 / 10 攻 —— 一次攻击必杀，
敌人无反击机会，与随机波动无关。
"""

from pathlib import Path

from dse_core import play

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_scripted_normal_line(monkeypatch, capsys):
    monkeypatch.setenv("DSE_INPUT", "1")  # 拿钱走人 → 结局 → 输入用尽 → quit
    code = play(root=str(FIXTURES / "mini"))
    assert code == 0
    out = capsys.readouterr().out
    assert "你有 5 金币，HP 10。" in out      # 插值
    assert "你带着 10 金币离开了。" in out     # 效果执行 + 插值
    assert "游戏已退出，感谢游玩！" in out


def test_scripted_restart_resets_state(monkeypatch, capsys):
    # 1 → 富足结局；1 → @restart 全量重置；2 → 静默结局（无选项 → （完））
    monkeypatch.setenv("DSE_INPUT", "1,1,2")
    code = play(root=str(FIXTURES / "mini"))
    assert code == 0
    out = capsys.readouterr().out
    assert out.count("你有 5 金币，HP 10。") == 2  # 重置后回到 initial
    assert "（完）" in out


def test_scripted_hidden_choice_filtered(monkeypatch, capsys):
    # gold=5，'gold > 100' 的选项必须被过滤掉，编号不受影响
    monkeypatch.setenv("DSE_INPUT", "2")
    code = play(root=str(FIXTURES / "mini"))
    assert code == 0
    out = capsys.readouterr().out
    assert "（不可见的路）" not in out
    assert "静默" in out


def test_scripted_battle_win(monkeypatch, capsys):
    monkeypatch.setenv("DSE_INPUT", "1,a")  # 开打 → 攻击（一击必杀）
    code = play(root=str(FIXTURES / "battle"))
    assert code == 0
    out = capsys.readouterr().out
    assert "⚔ 第 1 回合" in out        # 战斗面板
    assert "造成" in out and "点伤害" in out
    assert "你击败了木桩假人！" in out
    assert "战利品：gold 0 → 7" in out  # 掉落结算
    assert "（完）" in out               # win 场景无选项 → 结局


def test_battle_blocks_non_battle_commands(monkeypatch, capsys):
    # 战斗中输入非法指令 → 明确拒绝，不静默吞掉
    monkeypatch.setenv("DSE_INPUT", "1,xyz,a")
    code = play(root=str(FIXTURES / "battle"))
    assert code == 0
    out = capsys.readouterr().out
    assert "战斗中不可用：xyz" in out


def test_stats_command(monkeypatch, capsys):
    monkeypatch.setenv("DSE_INPUT", "stats,quit")
    code = play(root=str(FIXTURES / "mini"))
    assert code == 0
    out = capsys.readouterr().out
    assert "测试员 | HP 10 | ATK None | 金币 5" in out
