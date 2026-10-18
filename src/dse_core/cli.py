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

    args = parser.parse_args(argv)
    args.root = _resolve_root(args.root)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"[dse] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
