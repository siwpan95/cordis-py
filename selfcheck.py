#!/usr/bin/env python3
"""dse-core (cordis-py) — 无头自检入口。

只用标准库 + 本项目自身模块（PyYAML / jsonschema 为项目声明依赖）。
``src/`` 采用 src-layout，故把仓库的 ``src`` 目录加入 sys.path 后 import，
不依赖任何 pip install。

验证点：
  1. 条件表达式 AST 白名单（safety）：合法表达式求值正确，调用/下划线属性被拒。
  2. 状态服务（state）：数值加减 / 点路径计数 / 布尔赋值 / emit 不写状态 /
     原型污染拒绝 / 条件求值 / 文本插值 / 快照往返 / reset(keep) 跨轮保留。
  3. 场景图静态分析（graph + loader）：可达性 / 结局 / 悬空边 / 最短路径。
  4. 内容包 manifest 规范化与校验（manifest + modes）。
  5. 脚本化端到端驱动（DSE_INPUT）：真跑引擎走场景、验状态推进与结局。

用法：python selfcheck.py   （成功退出 0，失败打印 FAIL 并退出 1）
"""

import contextlib
import io
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, "src")
sys.path.insert(0, _SRC)  # src-layout：不依赖 pip install

_FAILS = []


def check(name, fn):
    try:
        detail = fn()
        if detail is False:
            raise AssertionError("检查返回 False")
        print(f"  [ok] {name}" + (f" — {detail}" if isinstance(detail, str) else ""))
    except Exception as exc:  # noqa: BLE001 - 自检需要兜住一切失败
        _FAILS.append(f"{name}: {type(exc).__name__}: {exc}")
        print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")


# ═══════════════════════════════════════════════════════════════
#  0. 确认测的是仓库内源码
# ═══════════════════════════════════════════════════════════════
def check_imports_local_package():
    import dse_core

    pkg_dir = os.path.dirname(os.path.abspath(dse_core.__file__))
    expected = os.path.normcase(os.path.join(_SRC, "dse_core"))
    if os.path.normcase(pkg_dir) != expected:
        raise AssertionError(f"导入的 dse_core 不在本仓库 src 下：{pkg_dir}")
    return f"dse_core {dse_core.__version__} @ {pkg_dir}"


# ═══════════════════════════════════════════════════════════════
#  1. 条件表达式 AST 白名单
# ═══════════════════════════════════════════════════════════════
def check_expression_safety():
    from dse_core.safety import UnsafeExpression, evaluate

    scope = {
        "gold": 20,
        "hp": 12,
        "atk": 3,
        "items": {"sword": 2, "token": 1},
        "flags": {"door_locked": False, "met_wolf": True},
    }

    # 合法表达式：比较 / 布尔 / 算术 / 下标 / 属性路径
    cases = {
        "gold >= 10 and hp > 0": True,
        "gold < 10 or hp < 5": False,
        "not flags.door_locked": True,
        "items.sword >= 2": True,
        "items['sword'] + items['token'] == 3": True,
        "hp + atk * 2 == 18": True,
        "flags.met_wolf and not flags.door_locked": True,
        "'sword' in items": True,
        "10 if hp > 5 else 0": 10,
    }
    for expr, want in cases.items():
        got = evaluate(expr, scope)
        if got != want:
            raise AssertionError(f'{expr!r} 应为 {want!r}，实际 {got!r}')

    # 未定义名字：响亮报错（由调用方兜底 False），而不是静默 None
    try:
        evaluate("nonexistent > 1", scope)
    except NameError:
        pass
    else:
        raise AssertionError("未定义名字应抛 NameError")

    # 白名单外的语法必须被拒：函数调用 / 下划线属性 / 推导式 / lambda / import
    unsafe = [
        "open('x')",
        "__import__('os').system('echo hi')",
        "gold.__class__",
        "[x for x in range(3)]",
        "lambda: 1",
        "eval('1+1')",
        "items.get('sword')",
    ]
    for expr in unsafe:
        try:
            evaluate(expr, scope)
        except UnsafeExpression:
            continue
        except Exception as exc:  # 语法错误等也算拒绝，但不是白名单拦截
            raise AssertionError(f"{expr!r} 抛了非 UnsafeExpression：{type(exc).__name__}") from exc
        raise AssertionError(f"{expr!r} 未被白名单拦截")

    return f"{len(cases)} 条合法表达式求值正确，{len(unsafe)} 条越权语法全部拦截"


# ═══════════════════════════════════════════════════════════════
#  2. 状态服务：效果语义 / 条件 / 插值 / 快照往返
# ═══════════════════════════════════════════════════════════════
def check_state_service():
    from dse_core.plugins.state import StateService
    from dse_core.runtime import Context

    ctx = Context(root=_ROOT, quiet=True)
    ctx.plugin(StateService, {
        "initial": {
            "name": "旅人",
            "hp": 20,
            "gold": 20,
            "items": {},
            "flags": {"loop": {}},
            "clues": {"loop": {"seen": True}},
        },
    })
    ctx.start()
    st = ctx.services["state"]
    assert st is not None

    # 数值加减（仅当原值也是数值）
    changes = st.apply({"gold": +10})
    if st.get("gold") != 30:
        raise AssertionError(f"gold 应加到 30，实际 {st.get('gold')}")
    if not changes or changes[0]["from"] != 20 or changes[0]["to"] != 30:
        raise AssertionError(f"apply 变更记录不正确：{changes}")

    # 点路径计数：items 为空时自动建中间层；跨多次 apply 累加
    st.apply({"items.sword": +1})
    st.apply({"items.sword": +1})
    st.apply({"items.token": +1})
    if st.get("items.sword") != 2 or st.get("items.token") != 1:
        raise AssertionError(f"点路径计数错误：{st.get('items')}")

    # 布尔 / 字符串按赋值处理（bool 是 int 子类，不能被当成数值加）
    st.apply({"flags.met_wolf": True, "name": "勇者"})
    if st.get("flags.met_wolf") is not True:
        raise AssertionError("布尔效果应赋值为 True")
    if st.get("name") != "勇者":
        raise AssertionError("字符串效果应赋值")

    # emit 只广播事件，不写入状态
    seen = []
    ctx.on("notice/read", lambda: seen.append(1))
    before = st.snapshot()
    st.apply({"emit": "notice/read"})
    if seen != [1]:
        raise AssertionError("emit 未广播事件")
    if st.snapshot() != before:
        raise AssertionError("emit 不应改动状态")

    # 原型污染防护（预期会在 stderr 打一条 warn，这里静音以便自检输出干净）
    with contextlib.redirect_stderr(io.StringIO()):
        denied = st.set("__proto__.polluted", 1)
    if denied is not False:
        raise AssertionError("危险路径写入应被拒绝")
    if st.get("__proto__") is not None:
        raise AssertionError("危险路径读取应返回 None")

    # 条件求值：无条件恒真；非法表达式兜底 False（同样静音预期的 warn）
    if st.check(None) is not True or st.check("") is not True:
        raise AssertionError("无条件应恒真")
    if st.check("hp >= 10 and gold > 0") is not True:
        raise AssertionError("合法条件求值错误")
    with contextlib.redirect_stderr(io.StringIO()):
        bad_condition = st.check("totally_undefined > 1")
    if bad_condition is not False:
        raise AssertionError("条件求值异常应兜底 False")

    # 文本插值：命中替换，缺失原样保留
    if st.interpolate("你好，{name}！HP={hp}") != "你好，勇者！HP=20":
        raise AssertionError(f"插值错误：{st.interpolate('你好，{name}！HP={hp}')!r}")
    if st.interpolate("{not_there}") != "{not_there}":
        raise AssertionError("缺失键应原样保留")

    # 快照 / 恢复往返（深层拷贝：改原状态不影响快照）
    snap = st.snapshot()
    st.apply({"gold": +5})
    if st.get("gold") == snap["gold"]:
        raise AssertionError("gold 未变化，测试前置失效")
    st.restore(snap)
    if st.get("gold") != snap["gold"] or st.get("items.sword") != 2:
        raise AssertionError("restore 后状态与快照不一致")

    # reset(keep=...) 时间循环语义：保持域跨轮保留，其余回 initial
    st.apply({"clues.loop.round": +1, "hp": -7})
    st.reset(keep=["clues.loop"])
    if st.get("hp") != 20:
        raise AssertionError("reset 后 hp 应回 initial 的 20")
    if st.get("clues.loop.seen") is not True or st.get("clues.loop.round") != 1:
        raise AssertionError("reset(keep) 未保留 clues.loop 域")
    if st.get("gold") != 20:
        raise AssertionError("reset(keep) 应重置非保留域")

    return "效果语义/emit/防污染/条件/插值/快照往返/reset(keep) 全部符合契约"


# ═══════════════════════════════════════════════════════════════
#  3. 场景图静态分析
# ═══════════════════════════════════════════════════════════════
def check_graph_analysis():
    from dse_core import graph, loader
    from dse_core.sdk import engine_root

    project = loader.load_project(engine_root())
    report = graph.analyze(project.dict, project.entry)

    if report["scenes"] != len(project.ids):
        raise AssertionError("scenes 计数与场景字典不一致")
    if report["dangling"]:
        raise AssertionError(f"示例内容不应有悬空边：{report['dangling']}")
    if report["unreachable"]:
        raise AssertionError(f"示例内容不应有不可达场景：{report['unreachable']}")
    expected_endings = {"forest-lose", "end-hero", "inn-wait"}
    if set(report["endings"]) != expected_endings:
        raise AssertionError(f"结局识别错误：{report['endings']}")

    # battle 模式场景不是结局（有插件接管流转）
    if graph.is_ending(project.dict["wolf-fight"]):
        raise AssertionError("battle 场景不应被判为结局")

    # 最短路径必须真实存在于图中
    path = graph.shortest_path(project.dict, project.entry, "end-hero")
    if path != ["start", "forest", "wolf-fight", "forest-win", "end-hero"]:
        raise AssertionError(f"到 end-hero 的最短路径错误：{path}")
    for a, b in zip(path, path[1:]):
        targets = {e["to"] for e in graph.edges_of(a, project.dict[a])}
        if b not in targets:
            raise AssertionError(f"路径边不存在：{a} -> {b}")
    if graph.shortest_path(project.dict, project.entry, "no-such-scene") is not None:
        raise AssertionError("不存在目标的 shortest_path 应返回 None")

    # 悬空边：普通目标缺失 / @loop 目标缺失 / 非法 @ 目标，三路都要报
    synthetic = {
        "a": {"choices": [{"goto": "@loop:nope"}, {"goto": "@bogus"}, {"goto": "missing"}]},
        "b": {"choices": [{"goto": "a"}]},
    }
    synthetic_report = graph.analyze(synthetic, "a")
    kinds = {d["kind"] for d in synthetic_report["dangling"]}
    if not {"choice", "loop", "special"} <= kinds:
        raise AssertionError(f"悬空边识别不全：{kinds}")
    if synthetic_report["unreachable"] != ["b"]:
        raise AssertionError(f"不可达识别错误：{synthetic_report['unreachable']}")

    return f"{report['scenes']} 场景全可达、{len(report['endings'])} 个结局、最短路径与悬空边判定正确"


# ═══════════════════════════════════════════════════════════════
#  4. 内容包 manifest 与模式注册表
# ═══════════════════════════════════════════════════════════════
def check_manifest_and_modes():
    from dse_core import loader, modes
    from dse_core.manifest import normalize_manifest, validate_manifest
    from dse_core.sdk import engine_root

    project = loader.load_project(engine_root())
    if len(project.manifests) != 1:
        raise AssertionError(f"示例应只含 1 个内容包，实际 {len(project.manifests)}")
    m = project.manifests[0]
    if m["id"] != "starter" or m["entry"] != "start":
        raise AssertionError(f"manifest 规范化错误：{m}")
    if m["modes"] != ["battle"]:
        raise AssertionError(f"modes 自动探测错误：{m['modes']}")
    if m["requires"]["plugins"] != ["combat"]:
        raise AssertionError(f"requires.plugins 错误：{m['requires']}")
    if validate_manifest(m):
        raise AssertionError(f"示例 manifest 不应有问题：{validate_manifest(m)}")

    # 缺省值推导：id 取文件名、entry 取首个场景、modes 从场景自动探测
    auto = normalize_manifest(None, "my_pack.yml", {"s1": {}, "s2": {"mode": "trade"}})
    if auto["id"] != "my_pack" or auto["entry"] != "s1" or auto["version"] != "0.0.0":
        raise AssertionError(f"manifest 缺省推导错误：{auto}")
    if auto["modes"] != ["trade"]:
        raise AssertionError(f"mode 自动探测错误：{auto['modes']}")

    # 非法 manifest 必须被校验拦下
    bad = {"id": "9Bad", "version": "abc", "modes": ["teleport"]}
    problems = validate_manifest(bad)
    if len(problems) < 3:
        raise AssertionError(f"非法 manifest 应报 3 项问题，实际 {problems}")

    # 模式注册表：内置模式齐备，流转边与插件绑定一致
    names = modes.mode_names()
    for want in ("normal", "battle", "trade", "diary", "dialogue"):
        if want not in names:
            raise AssertionError(f"缺少内置模式 {want}")
    if modes.mode_edges("battle") != ["onWin", "onLose", "onFlee"]:
        raise AssertionError(f"battle 流转边错误：{modes.mode_edges('battle')}")
    if modes.mode_edges("unknown-mode"):
        raise AssertionError("未注册模式应无流转边")
    if not modes.is_special_goto("@restart") or not modes.is_special_goto("@loop:x"):
        raise AssertionError("特殊跳转识别错误")
    if modes.resolve_goto("@loop:dungeon") != "dungeon":
        raise AssertionError("@loop: 目标解析错误")

    return "manifest 规范化/校验 + 模式注册表与流转边"


# ═══════════════════════════════════════════════════════════════
#  5. 端到端：脚本化输入真跑引擎
# ═══════════════════════════════════════════════════════════════
def _run_scripted(script: str, quiet: bool = True):
    """用 DSE_INPUT 脚本跑一局自带示例，返回 (engine, 进入序列, 输出文本)。"""
    from dse_core import create_engine
    from dse_core.sdk import engine_root

    os.environ["DSE_INPUT"] = script
    ctx = create_engine(engine_root(), quiet=quiet)

    enters = []
    ctx.on("scene/enter", lambda sid, scene: enters.append(
        (sid,
         ctx.state.get("flags.starter.mountain"),
         ctx.state.get("flags.starter.fled"),
         ctx.state.get("visits.%s" % sid))))

    engine = ctx.services["engine"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        engine.start()
    return engine, enters, buf.getvalue()


def check_engine_end_to_end():
    # 线路 A：进山（打上 mountain 标记）→ 慢慢退回（打上 fled 标记）→ 回到起点。
    # 输入用尽后引擎以 quit 正常退出，退出码 0。
    engine, enters, out = _run_scripted("1,2")
    if engine.exit_code != 0:
        raise AssertionError(f"线路 A 退出码应为 0，实际 {engine.exit_code}")
    scenes = [e[0] for e in enters]
    if scenes != ["start", "forest", "start"]:
        raise AssertionError(f"线路 A 的场景推进错误：{scenes}")
    if enters[1][1] is not True:
        raise AssertionError("进山后 flags.starter.mountain 应为 True")
    if enters[1][2] is not None:
        raise AssertionError("退回前不应有 fled 标记")
    if enters[2][2] is not True:
        raise AssertionError("退回后 flags.starter.fled 应为 True")
    if enters[2][3] != 2:
        raise AssertionError(f"第二次进 start 的 visits 应为 2，实际 {enters[2][3]}")
    if engine.current != "start":
        raise AssertionError(f"线路 A 结束场景应为 start，实际 {engine.current}")
    if "山道 · 林深处" not in out:
        raise AssertionError("输出里没有森林场景正文")

    # 线路 B：回屋 → 直达结局 inn-wait
    engine2, enters2, out2 = _run_scripted("2")
    if engine2.exit_code != 0:
        raise AssertionError(f"线路 B 退出码应为 0，实际 {engine2.exit_code}")
    if [e[0] for e in enters2] != ["start", "inn-wait"]:
        raise AssertionError(f"线路 B 的场景推进错误：{[e[0] for e in enters2]}")
    if engine2.current != "inn-wait":
        raise AssertionError(f"线路 B 应停在结局 inn-wait，实际 {engine2.current}")
    if "结局 · 留在岸这边" not in out2:
        raise AssertionError("输出里没有结局标题")

    return f"脚本输入真跑引擎：{len(enters)}+{len(enters2)} 次场景进入，状态推进与结局均正确"


def main():
    print("dse-core (cordis-py) 无头自检（不进交互循环、不启动 GUI）")
    check("导入自本仓库 src", check_imports_local_package)
    check("条件表达式 AST 白名单", check_expression_safety)
    check("状态服务（效果/快照往返）", check_state_service)
    check("场景图静态分析", check_graph_analysis)
    check("manifest 与模式注册表", check_manifest_and_modes)
    check("脚本化端到端驱动引擎", check_engine_end_to_end)

    if _FAILS:
        print(f"FAIL: {len(_FAILS)} 项检查未通过")
        for f in _FAILS:
            print(f"  - {f}")
        return 1

    print(
        "selfcheck ok: 条件表达式白名单 + 状态效果与快照往返 + 场景图可达性/结局/悬空边 + "
        "manifest 校验 + DSE_INPUT 脚本真跑引擎（场景推进与结局）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
