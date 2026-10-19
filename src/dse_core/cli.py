"""命令行 dse：play / scenes / info / check / packs / saves / doctor / new。

移植自 dse-core(Node) cli.js。约定：stdout 只放结果，诊断走 stderr；
check 发现问题退出码 1。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from . import __version__, graph
from .loader import load_pack_file, load_project, load_yaml, read_plugin_config
from .plugins.scenes import find_dangling, validate_scenes
from .sdk import engine_root, inspect_project, load_dict, load_packs, play
from .schema import validate_pack

# ------------------------------------------------------------ 脚手架模板（dse new）


_TEMPLATES: dict[str, str] = {
    "hub": """pack:
  id: {name}
  name: {title}
  version: 0.1.0
  entry: start
scenes:
  start:
    title: 枢纽
    text: （写你的开场正文）
    choices:
      - text: 分支甲
        goto: branch-a
      - text: 分支乙
        goto: branch-b
  branch-a:
    title: 分支甲
    text: （写分支甲的内容）
    choices:
      - text: 回到枢纽
        goto: start
  branch-b:
    title: 分支乙
    text: （写分支乙的内容）
    choices:
      - text: 结局
        goto: end
  end:
    title: 结局
    text: （写结局正文）
""",
    "battle": """pack:
  id: {name}
  name: {title}
  version: 0.1.0
  entry: start
  modes: [battle]
  requires:
    plugins: [combat]
scenes:
  start:
    title: 遭遇前
    text: （写遭遇前的铺垫；敌人配置在 dse.yml 的 combat.enemies）
    choices:
      - text: 拔剑
        goto: fight
  fight:
    title: 战斗
    text: （写战斗开场）
    mode: battle
    battle: {{ enemy: wolf, onWin: win, onLose: lose, onFlee: start }}
  win:
    title: 胜利
    text: （写胜利后的内容）
  lose:
    title: 失败
    text: （写失败后的内容）
""",
    "branch": """pack:
  id: {name}
  name: {title}
  version: 0.1.0
  entry: start
scenes:
  start:
    title: 抉择
    text: （写正文）
    choices:
      - text: 答应
        do: {{ 'flags.{name}.agreed': true }}
        goto: end-yes
      - text: 拒绝
        if: 'gold >= 10'
        goto: end-no
  end-yes:
    title: 结局 · 应下
    text: （写正文）
  end-no:
    title: 结局 · 拒了
    text: （写正文）
""",
    "loop": """pack:
  id: {name}
  name: {title}
  version: 0.1.0
  entry: start
scenes:
  start:
    title: 循环起点
    text: （写正文；clues.loop.* 下的知识跨轮保留，见 dse.yml 的 state.loopKeep）
    choices:
      - text: 进入循环
        goto: '@loop:start'
""",
    "diary": """pack:
  id: {name}
  name: {title}
  version: 0.1.0
  entry: start
  modes: [diary]
  requires:
    plugins: [diary]
scenes:
  start:
    title: 夜读
    text: （写正文；diary 插件接管回溯，未安装时引擎会响亮报错）
    mode: diary
    diary: {{ onExit: start }}
""",
    "dialogue": """pack:
  id: {name}
  name: {title}
  version: 0.1.0
  entry: start
  modes: [dialogue]
  requires:
    plugins: [dialogue]
scenes:
  start:
    title: 对话
    text: （写正文）
    mode: dialogue
    dialogue:
      npc: （NPC 名）
      notes: 3
      onEnd: start
      topics:
        - id: t1
          name: 话题一
          reply: （对方回答）
""",
    "trade": """pack:
  id: {name}
  name: {title}
  version: 0.1.0
  entry: start
  modes: [trade]
  requires:
    plugins: [trade]
scenes:
  start:
    title: 开市
    text: （写正文）
    mode: trade
    trade: {{ name: 集市, days: 3, onEnd: end }}
  end:
    title: 收市
    text: （写正文）
""",
}

_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def _print_banner() -> None:
    title = f"字 典 场 景 引 擎  v{__version__}"
    width = sum(2 if ord(ch) > 0x2E7F else 1 for ch in title)
    border = "═" * 40
    print(f"╔{border}╗")
    print(f"║   {title}{' ' * max(0, 37 - width)}║")
    print(f"║   Dictionary Scene Engine (Python){' ' * max(0, 37 - 32)}║")
    print(f"╚{border}╝")


def _resolve_root(root: str | None) -> str:
    """未指定 --root 时：当前目录有 dse.yml 就用它，否则用包内自带示例工程。"""
    if root is not None:
        return root
    cwd = Path.cwd()
    if (cwd / "dse.yml").is_file():
        return str(cwd)
    return str(engine_root())


def _cmd_play(args) -> int:
    if args.input:
        os.environ["DSE_INPUT"] = args.input
    if args.banner:
        _print_banner()
    return play(root=args.root, entry=args.entry)


def _cmd_scenes(args) -> int:
    data = load_dict(args.root)
    print(f"工程: {data['root']}（入口 {data['entry']}，内容包 {len(data['packFiles'])} 个）")
    for scene_id in data["ids"]:
        scene = data["dict"][scene_id]
        mode = scene.get("mode") or "normal"
        title = scene.get("title") or scene_id
        n_choices = len(scene.get("choices") or [])
        print(f"  {scene_id:<20} [{mode:<8}] {title}（{n_choices} 选项）")
    print(f"共 {len(data['ids'])} 个场景")
    return 0


def _cmd_info(args) -> int:
    report = inspect_project(args.root)
    print(f"工程: {report['root']}")
    print(f"入口: {report['entry']}")
    print(f"场景: {report['scenes']} | 结局: {report['endings']}（可达 {report['endingsReachable']}）")
    print(f"内容包: {', '.join(report['packFiles']) or '（无）'}")
    for m in report["packs"]:
        print(f"  - {m['id']} v{m['version']}《{m['name']}》 {m['scenes']} 场景 modes={m['modes']}")
    if report["dangling"]:
        print("悬空跳转:", file=sys.stderr)
        for d in report["dangling"]:
            print(f"  - {d['from']} -> {d['to']} ({d['kind']})", file=sys.stderr)
    if report["unreachable"]:
        print(f"警告: 不可达场景 {', '.join(report['unreachable'])}", file=sys.stderr)
    return 0


def _cmd_check(args) -> int:
    root = Path(args.root)
    problems: list[str] = []
    try:
        project = load_project(root)
    except Exception as exc:  # noqa: BLE001 — 加载失败本身就是 check 的结论
        print(f"[check] 工程加载失败: {exc}", file=sys.stderr)
        return 1

    # 1. Schema + 结构校验（逐内容包）
    for rel in project.pack_files:
        path = (root / rel).resolve()
        _, scenes = load_pack_file(path)
        problems += validate_pack(scenes, source=rel)
        problems += validate_scenes(scenes, rel)

    # 2. 悬空跳转
    problems += find_dangling(project.dict)

    # 3. 图分析（不可达仅警告，不判失败）
    report = graph.analyze(project.dict, project.entry)

    if problems:
        print(f"[check] 发现 {len(problems)} 个问题:", file=sys.stderr)
        for p in problems:
            print(p, file=sys.stderr)
        return 1
    print(f"[check] 通过：{report['scenes']} 场景 / {len(report['endings'])} 结局（可达 {len(report['endingsReachable'])}）")
    if report["unreachable"]:
        print(f"警告: 不可达场景 {', '.join(report['unreachable'])}", file=sys.stderr)
    return 0


def _cmd_packs(args) -> int:
    packs = load_packs(args.root)
    if not packs:
        print("（没有内容包）")
        return 0
    for m in packs:
        print(f"  {m['id']:<16} v{m['version']:<8} 《{m['name']}》 {m['scenes']} 场景  modes={m['modes']}")
        if m["requires"]["plugins"]:
            print(f"  {'':<16} 依赖插件: {', '.join(m['requires']['plugins'])}")
    print(f"共 {len(packs)} 个内容包")
    return 0


def _cmd_saves(args) -> int:
    """离线列出存档位（不启动引擎）。"""
    root = Path(args.root)
    manifest = load_yaml(root / "dse.yml")
    save_cfg = read_plugin_config(manifest, "save")
    save_dir = (root / (save_cfg.get("dir") or "./saves")).resolve()
    if not save_dir.is_dir():
        print(f"（存档目录不存在: {save_dir}）")
        return 0
    slots = []
    for f in sorted(save_dir.glob("*.json")):
        try:
            record = json.loads(f.read_text(encoding="utf-8"))
            slots.append((f.stem, record.get("scene"), record.get("savedAt", "")))
        except (OSError, json.JSONDecodeError):
            slots.append((f.stem, "（损坏）", ""))
    if not slots:
        print(f"（暂无存档: {save_dir}）")
        return 0
    for slot, scene, saved_at in slots:
        print(f"  {slot:<16} 场景: {scene}  保存于: {saved_at}")
    print(f"共 {len(slots)} 个存档（目录: {save_dir}）")
    return 0


def _cmd_doctor(args) -> int:
    """工程体检：结构 + 图分析 + 内容模式 vs 已装插件交叉核对。"""
    root = Path(args.root)
    problems: list[str] = []
    try:
        project = load_project(root)
        manifest = load_yaml(root / "dse.yml")
    except Exception as exc:  # noqa: BLE001
        print(f"[doctor] 工程加载失败: {exc}", file=sys.stderr)
        return 1

    # 结构 + 悬空
    for rel in project.pack_files:
        path = (root / rel).resolve()
        _, scenes = load_pack_file(path)
        problems += validate_pack(scenes, source=rel)
        problems += validate_scenes(scenes, rel)
    problems += find_dangling(project.dict)

    report = graph.analyze(project.dict, project.entry)

    # 内容用到的模式 vs dse.yml 已装插件
    from .modes import MODE_REGISTRY

    installed = {
        item.get("id") for item in (manifest if isinstance(manifest, list) else []) if isinstance(item, dict)
    }
    used_modes = {(s.get("mode") or "normal") for s in project.dict.values()}
    print(f"工程: {root}")
    print(f"场景 {report['scenes']} | 结局 {len(report['endings'])}（可达 {len(report['endingsReachable'])}）"
          f" | 悬空 {len(report['dangling'])} | 不可达 {len(report['unreachable'])}")
    print(f"内容用到的模式: {', '.join(sorted(used_modes))}")
    for mode in sorted(used_modes):
        if mode == "normal":
            continue
        plugin = MODE_REGISTRY.get(mode, {}).get("plugin") or mode
        status = "✓" if plugin in installed else "✗ 未安装"
        print(f"  {mode:<10} → 插件 {plugin:<12} {status}")
        if plugin not in installed:
            problems.append(f"模式 {mode} 需要插件 {plugin}，但 dse.yml 未安装")

    # 插件依赖拓扑巡检（静态解析 inject，不启动引擎；对齐 Cordis fiber 巡检）
    from .sdk import _resolve_plugin

    plugin_ids: list[str] = []
    for pid in ["scenes", "state", "io", "engine"] + [
        item["id"] for item in (manifest if isinstance(manifest, list) else [])
        if isinstance(item, dict) and item.get("id")
    ]:
        if pid not in plugin_ids:
            plugin_ids.append(pid)

    classes: dict[str, type] = {}
    for pid in plugin_ids:
        try:
            classes[pid] = _resolve_plugin(pid)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"插件 {pid} 无法解析: {exc}")
    for pid, cls in classes.items():
        for dep in cls.inject:
            if dep not in classes:
                problems.append(f"插件 {pid} 依赖未加载的服务: {dep}")

    ordered: list[str] = []
    remaining = dict(classes)
    while remaining:
        ready = [p for p, c in remaining.items() if all(d in ordered for d in c.inject)]
        if not ready:
            problems.append(f"插件依赖存在循环: {sorted(remaining)}")
            break
        for p in ready:
            ordered.append(p)
            del remaining[p]
    if ordered:
        print(f"插件启动顺序（拓扑序）: {' → '.join(ordered)}")

    if problems:
        print(f"[doctor] 发现 {len(problems)} 个问题:", file=sys.stderr)
        for p in problems:
            print(p, file=sys.stderr)
        return 1
    print("[doctor] 健康")
    return 0


def _cmd_new(args) -> int:
    """脚手架：生成一个 YAML 内容包骨架，并尝试挂进 dse.yml。"""
    name = args.name.strip()
    if not _ID_RE.match(name):
        print(f"[new] 包名非法: {name}（小写字母开头，仅 a-z 0-9 _ -）", file=sys.stderr)
        return 1
    template = _TEMPLATES.get(args.template)
    if template is None:
        print(f"[new] 未知模板: {args.template}（可用: {', '.join(sorted(_TEMPLATES))}）", file=sys.stderr)
        return 1
    root = Path(args.root)
    content_dir = root / "content"
    content_dir.mkdir(parents=True, exist_ok=True)
    target = content_dir / f"{name}.yml"
    if target.exists():
        print(f"[new] 文件已存在: {target}", file=sys.stderr)
        return 1
    target.write_text(template.format(name=name, title=args.title or name), encoding="utf-8")
    print(f"已生成 {target}")

    # 挂进 dse.yml 的 scenes.packs（文本级插入，保留注释与格式）
    manifest_path = root / "dse.yml"
    rel_entry = f"./content/{name}.yml"
    if manifest_path.is_file():
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
        last_pack_idx = None
        in_scenes = False
        for i, line in enumerate(lines):
            if re.match(r"^-\s+id:\s+scenes\s*$", line):
                in_scenes = True
            elif re.match(r"^-\s+id:", line) and in_scenes:
                in_scenes = False
            if in_scenes and re.match(r"^\s+-\s+\./content/.*\.(yml|yaml)\s*$", line):
                last_pack_idx = i
        if last_pack_idx is not None:
            indent = re.match(r"^(\s+)-\s", lines[last_pack_idx]).group(1)
            lines.insert(last_pack_idx + 1, f"{indent}- {rel_entry}")
            manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"已挂进 {manifest_path}（scenes.packs）")
        else:
            print(f"未找到 scenes.packs 锚点，请手动在 {manifest_path} 添加: - {rel_entry}")
    else:
        print(f"工程无 dse.yml，请手动创建并添加 packs: - {rel_entry}")
    return 0


def _cmd_graph(args) -> int:
    """导出场景图：Graphviz DOT 或 Mermaid（Twine passage map 的 CLI 对应物）。"""
    data = load_dict(args.root)
    scenes, entry = data["dict"], data["entry"]
    out = graph.to_mermaid(scenes, entry) if args.format == "mermaid" else graph.to_dot(scenes, entry)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"已导出 {args.format} 场景图: {args.output}（{len(scenes)} 场景）")
    else:
        print(out, end="")
    return 0


def _cmd_test(args) -> int:
    """脚本化回归：跑输入序列，断言最终场景与状态表达式（CI 友好）。"""
    import random as _random

    from .sdk import create_engine

    os.environ["DSE_INPUT"] = args.script
    try:
        ctx = create_engine(args.root, entry=args.entry)
        engine = ctx.services["engine"]
        state = ctx.services["state"]  # 先抓引用：engine 结束后 ctx.dispose() 会清空服务表
        if args.seed is not None:
            engine.rng = _random.Random(args.seed)
        engine.start()
    finally:
        os.environ.pop("DSE_INPUT", None)  # 不残留进程环境（pytest 同进程连跑）

    failures: list[str] = []
    if args.expect_scene is not None and engine.current != args.expect_scene:
        failures.append(f"最终场景应为 {args.expect_scene}，实际 {engine.current}")
    for expr in args.expect or []:
        if not state.check(expr):
            failures.append(f'状态断言失败: "{expr}"')
    if args.expect_exit is not None and engine.exit_code != args.expect_exit:
        failures.append(f"退出码应为 {args.expect_exit}，实际 {engine.exit_code}")

    if failures:
        for f in failures:
            print(f"[test] ✗ {f}", file=sys.stderr)
        return 1
    print(f"[test] ✓ 通过（剧本 {len(args.script.split(','))} 步，最终场景 {engine.current}，退出码 {engine.exit_code}）")
    return 0


def _cmd_export_html(args) -> int:
    """导出单文件 HTML 播放器（normal 模式工程；mode 场景响亮警告）。"""
    from .export_html import find_unsupported, render_html

    data = load_dict(args.root)
    scenes, entry = data["dict"], data["entry"]

    # 取 state 初始值（dse.yml 里 state 插件的 config.initial）
    manifest = load_yaml(Path(data["root"]) / "dse.yml")
    initial: dict = {}
    for item in (manifest if isinstance(manifest, list) else []):
        if isinstance(item, dict) and item.get("id") == "state":
            initial = (item.get("config") or {}).get("initial") or {}

    warnings = find_unsupported(scenes)
    for w in warnings:
        print(f"[export-html] ⚠ {w}", file=sys.stderr)

    out_path = Path(args.output or f"{Path(data['root']).name}.html")
    title = args.title or Path(data["root"]).name
    out_path.write_text(render_html(scenes, entry, initial, title=title), encoding="utf-8")
    print(f"已导出单文件播放器: {out_path}（{len(scenes)} 场景，警告 {len(warnings)} 条）")
    return 0


def _cmd_analyze(args) -> int:
    """消费 telemetry 埋点 JSONL，输出路径分布报告（选择埋点 → 迭代闭环）。"""
    import json
    from collections import Counter

    path = Path(args.root) / (args.file or "telemetry.jsonl")
    if not path.is_file():
        print(f"[analyze] 埋点文件不存在: {path}（先在 dse.yml 启用 telemetry 插件并游玩）", file=sys.stderr)
        return 1

    sessions = 0
    scene_visits: Counter = Counter()
    choice_counts: Counter = Counter()
    endings: Counter = Counter()
    bad_lines = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            event = rec.get("event")
            if event == "session/start":
                sessions += 1
            elif event == "scene/enter":
                scene_visits[rec.get("scene") or "?"] += 1
            elif event == "choice/made":
                choice_counts[(rec.get("scene") or "?", rec.get("choice") or "?")] += 1
            elif event == "engine/end":
                endings[rec.get("scene") or "?"] += 1

    print(f"埋点文件: {path}")
    print(f"会话数: {sessions} | 场景访问 {sum(scene_visits.values())} 次 | 选择 {sum(choice_counts.values())} 次"
          f" | 结局到达 {sum(endings.values())} 次" + (f" | 坏行 {bad_lines}" if bad_lines else ""))
    if scene_visits:
        print("\n场景访问 Top:")
        for scene, n in scene_visits.most_common(args.top):
            print(f"  {scene:<24} {n}")
    if choice_counts:
        print("\n选项分布:")
        by_scene: dict[str, list] = {}
        for (scene, choice), n in choice_counts.items():
            by_scene.setdefault(scene, []).append((choice, n))
        for scene, items in by_scene.items():
            total = sum(n for _, n in items)
            print(f"  #{scene}")
            for choice, n in sorted(items, key=lambda x: -x[1]):
                print(f"    {n:>4} ({n * 100 // total:>3}%)  {choice}")
    if endings:
        print("\n结局到达率:")
        total_end = sum(endings.values())
        for scene, n in endings.most_common():
            print(f"  {scene:<24} {n}（{n * 100 // total_end}%）")
    return 0


def _cmd_i18n_extract(args) -> int:
    """P10 行级本地化提取（Yarn Spinner localization-first 的 dse 对应物）。

    扫全部场景的 text / title / choices[].text / extraText[].text，生成
    i18n/<locale>.yml 待翻译表：key = <场景>.<字段>[.<序号>]，value 缺省原文。
    已存在的表增量合并 —— 已翻译的 key 保留译值，新 key 补原文，删除的 key
    移入表尾注释块（不静默丢翻译）。
    """
    import yaml

    root = Path(args.root)
    data = load_dict(args.root)
    scenes = data["dict"]

    extracted: dict[str, str] = {}
    for sid, scene in scenes.items():
        if not isinstance(scene, dict):
            continue
        for field in ("text", "title"):
            value = scene.get(field)
            if isinstance(value, str) and value.strip() and "@" not in value:
                extracted[f"{sid}.{field}"] = value
        for i, choice in enumerate(scene.get("choices") or []):
            if isinstance(choice, dict):
                value = choice.get("text")
                if isinstance(value, str) and value.strip() and "@" not in value:
                    extracted[f"{sid}.choices.{i}"] = value
        for j, seg in enumerate(scene.get("extraText") or []):
            if isinstance(seg, dict):
                value = seg.get("text")
                if isinstance(value, str) and value.strip() and "@" not in value:
                    extracted[f"{sid}.extraText.{j}"] = value

    out_dir = root / "i18n"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.locale}.yml"

    existing: dict = {}
    if out_path.is_file():
        loaded = load_yaml(out_path)
        if isinstance(loaded, dict):
            existing = loaded

    merged: dict[str, str] = {}
    kept = 0
    for key, source in extracted.items():
        if key in existing and existing[key] != source:
            merged[key] = existing[key]  # 已译值优先（不被原文覆盖）
            kept += 1
        else:
            merged[key] = source
    orphans = sorted(k for k in existing if k not in extracted)

    header = (
        f"# dse i18n-extract 生成 · locale: {args.locale}\n"
        f"# 共 {len(merged)} 条（保留已译 {kept} 条）；内容里以 @key@ 引用，"
        f"dse.yml 的 i18n.locales.{args.locale} 挂本表\n"
    )
    body = yaml.safe_dump(merged, allow_unicode=True, sort_keys=True, width=120)
    if orphans:
        body += "\n# ---- 已下线的 key（源内容已删除，确认后手动清理）----\n"
        body += "".join(f"# {k}: {existing[k]!r}\n" for k in orphans)
    out_path.write_text(header + body, encoding="utf-8")
    print(f"已提取 {len(merged)} 条文本 → {out_path}（保留已译 {kept} 条，下线 {len(orphans)} 条）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dse",
        description="字典场景引擎 CLI —— 场景即字典，能力即插件",
    )
    parser.add_argument("--version", action="version", version=f"dse-core {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_play = sub.add_parser("play", help="开始游戏")
    p_play.add_argument("--root", default=None, help="工程根目录（含 dse.yml）；缺省：当前目录有则用，否则用包内示例")
    p_play.add_argument("--entry", help="覆盖入口场景 ID")
    p_play.add_argument("--input", help='脚本输入序列，逗号分隔（如 "1,1,a,a"），用尽自动退出')
    p_play.add_argument("--banner", action="store_true", help="打印启动横幅")
    p_play.set_defaults(func=_cmd_play)

    for name, help_text, func in (
        ("scenes", "列出全部场景", _cmd_scenes),
        ("info", "工程体检（结局/悬空/不可达）", _cmd_info),
        ("check", "校验内容（Schema/悬空），有问题退出码 1", _cmd_check),
        ("packs", "列出内容包（manifest）", _cmd_packs),
        ("saves", "列出存档位（离线，不启动引擎）", _cmd_saves),
        ("doctor", "工程体检 + 内容模式 vs 已装插件交叉核对", _cmd_doctor),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--root", default=None, help="工程根目录；缺省当前目录有 dse.yml 则用，否则包内示例")
        p.set_defaults(func=func)

    p_new = sub.add_parser("new", help="脚手架生成 YAML 内容包骨架")
    p_new.add_argument("name", help="包名（小写字母开头，仅 a-z 0-9 _ -）")
    p_new.add_argument("--template", default="hub", choices=sorted(_TEMPLATES), help="结构模板（缺省 hub）")
    p_new.add_argument("--title", help="展示名（缺省同包名）")
    p_new.add_argument("--root", default=None, help="工程根目录；缺省当前目录有 dse.yml 则用，否则包内示例")
    p_new.set_defaults(func=_cmd_new)

    p_graph = sub.add_parser("graph", help="导出场景图（DOT / Mermaid）")
    p_graph.add_argument("--format", choices=["dot", "mermaid"], default="mermaid", help="导出格式（缺省 mermaid）")
    p_graph.add_argument("-o", "--output", help="写入文件；缺省打印到 stdout")
    p_graph.add_argument("--root", default=None, help="工程根目录")
    p_graph.set_defaults(func=_cmd_graph)

    p_test = sub.add_parser("test", help="脚本化回归：跑输入序列并断言结果（CI 友好）")
    p_test.add_argument("--script", required=True, help='输入序列，逗号分隔（如 "1,1,a"）')
    p_test.add_argument("--expect-scene", help="断言最终场景 ID")
    p_test.add_argument("--expect", action="append", help="断言状态表达式（可多次，AST 白名单求值）")
    p_test.add_argument("--expect-exit", type=int, help="断言退出码")
    p_test.add_argument("--seed", type=int, help="覆盖加权随机种子（复现随机分支）")
    p_test.add_argument("--entry", help="覆盖入口场景 ID")
    p_test.add_argument("--root", default=None, help="工程根目录")
    p_test.set_defaults(func=_cmd_test)

    p_html = sub.add_parser("export-html", help="导出单文件 HTML 播放器（normal 模式工程）")
    p_html.add_argument("-o", "--output", help="输出文件（缺省 <工程名>.html）")
    p_html.add_argument("--title", help="页面标题（缺省取工程目录名）")
    p_html.add_argument("--root", default=None, help="工程根目录")
    p_html.set_defaults(func=_cmd_export_html)

    p_analyze = sub.add_parser("analyze", help="消费 telemetry 埋点，输出路径分布报告")
    p_analyze.add_argument("--file", help="埋点文件名（缺省 telemetry.jsonl）")
    p_analyze.add_argument("--top", type=int, default=10, help="场景访问 Top N（缺省 10）")
    p_analyze.add_argument("--root", default=None, help="工程根目录")
    p_analyze.set_defaults(func=_cmd_analyze)

    p_i18n = sub.add_parser("i18n-extract", help="提取场景文本生成待翻译表（增量合并保留已译值）")
    p_i18n.add_argument("--locale", default="en-US", help="目标语言（缺省 en-US）")
    p_i18n.add_argument("--root", default=None, help="工程根目录")
    p_i18n.set_defaults(func=_cmd_i18n_extract)

    args = parser.parse_args(argv)
    args.root = _resolve_root(args.root)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"[dse] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
