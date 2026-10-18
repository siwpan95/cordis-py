"""P2 端到端：存档/读档/成就随档、模式无插件时的响亮失败。"""

import json
from pathlib import Path

from dse_core import play

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SYS_FIXTURE = FIXTURES / "sys"
NOMODE_FIXTURE = FIXTURES / "nomode"


def test_scripted_save_and_load(monkeypatch, capsys):
    # 1 → 赚一笔（gold 15，进 rich 场景解锁成就）→ save t1 → load t1 → quit
    monkeypatch.setenv("DSE_INPUT", "1,save t1,load t1,quit")
    code = play(root=str(SYS_FIXTURE))
    assert code == 0
    out = capsys.readouterr().out
    assert "★ 成就解锁：小富" in out          # scene/enter 触发条件解锁
    assert "已保存到存档位 t1" in out
    assert "已读取存档位 t1" in out

    record = json.loads((SYS_FIXTURE / "saves" / "t1.json").read_text(encoding="utf-8"))
    assert record["scene"] == "rich"
    assert record["state"]["gold"] == 15
    assert record["achievements"] == ["got-rich"]  # 成就随档持久化
    assert record["version"] == 2                  # save-migrate 盖章


def test_load_restores_achievements(monkeypatch, capsys):
    # 先造一个旧档（无 version 字段 → 走迁移链路盖到 v2），再读档
    saves_dir = SYS_FIXTURE / "saves"
    saves_dir.mkdir(parents=True, exist_ok=True)
    (saves_dir / "old.json").write_text(json.dumps({
        "scene": "rich",
        "state": {"name": "测试员", "gold": 99},
        "achievements": ["got-rich"],
    }), encoding="utf-8")

    monkeypatch.setenv("DSE_INPUT", "load old,achievements,quit")
    code = play(root=str(SYS_FIXTURE))
    assert code == 0
    out = capsys.readouterr().out
    assert "存档已从 v1 迁移到 v2" in out       # save-migrate 链路生效
    assert "已读取存档位 old" in out
    assert "[✓] 小富" in out                    # 读档恢复成就解锁


def test_mode_without_plugin_fails_loudly(monkeypatch, capsys):
    """trade 场景但没有 trade 插件：必须响亮失败（exit 1 + 明确诊断），
    而不是 Node 版的静默回退 normal（会把 mode 场景误判成结局）。"""
    monkeypatch.setenv("DSE_INPUT", "quit")
    code = play(root=str(NOMODE_FIXTURE))
    assert code == 1
    captured = capsys.readouterr()
    assert "没有插件接管" in captured.err
    assert "trade" in captured.err
