"""命令行 dse：play / scenes / info / check。

移植自 dse-core(Node) cli.js 的 P1 子集（packs / new / doctor / saves
属 P2）。约定：stdout 只放结果，诊断走 stderr；check 发现问题退出码 1。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, graph
from .loader import load_pack_file, load_project
from .plugins.scenes import find_dangling, validate_scenes
from .sdk import inspect_project, load_dict, play
from .schema import validate_pack


def _print_banner() -> None:
    title = f"字 典 场 景 引 擎  v{__version__}"
    width = sum(2 if ord(ch) > 0x2E7F else 1 for ch in title)
    border = "═" * 40
    print(f"╔{border}╗")
    print(f"║   {title}{' ' * max(0, 37 - width)}║")
    print(f"║   Dictionary Scene Engine (Python){' ' * max(0, 37 - 32)}║")
    print(f"╚{border}╝")


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dse",
        description="字典场景引擎 CLI —— 场景即字典，能力即插件",
    )
    parser.add_argument("--version", action="version", version=f"dse-core {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_play = sub.add_parser("play", help="开始游戏")
    p_play.add_argument("--root", default=".", help="工程根目录（含 dse.yml），缺省当前目录")
    p_play.add_argument("--entry", help="覆盖入口场景 ID")
    p_play.add_argument("--input", help='脚本输入序列，逗号分隔（如 "1,1,a,a"），用尽自动退出')
    p_play.add_argument("--banner", action="store_true", help="打印启动横幅")
    p_play.set_defaults(func=_cmd_play)

    for name, help_text, func in (
        ("scenes", "列出全部场景", _cmd_scenes),
        ("info", "工程体检（结局/悬空/不可达）", _cmd_info),
        ("check", "校验内容（Schema/悬空），有问题退出码 1", _cmd_check),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--root", default=".", help="工程根目录（含 dse.yml），缺省当前目录")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"[dse] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
