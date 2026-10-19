"""场景图分析（纯函数，不依赖运行时）。

移植自 dse-core(Node) lib/graph.mjs：从「场景字典 + 入口」出发做静态图
分析 —— 可达性、结局、悬空边、入度、深度、最短路径。引擎化之前这些逻辑
散落在 lint 与测试里各写一份（BFS 口径还不一致），现在收敛到一处共用。
"""

from __future__ import annotations

from .modes import is_special_goto, mode_edges, resolve_goto


def is_ending(scene) -> bool:
    """结局判定：normal 模式且无选项，或所有选项都是特殊目标（@restart 等）。"""
    if not scene:
        return False
    if scene.get("mode") and scene["mode"] != "normal":
        return False
    choices = scene.get("choices") or []
    return len(choices) == 0 or all(str(c.get("goto") or "").startswith("@") for c in choices)


def edges_of(scene_id: str, scene) -> list[dict]:
    """单个场景的全部出边（选项 goto + 模式流转边；加权 goto 逐项展开）。"""
    out: list[dict] = []
    for choice in (scene or {}).get("choices") or []:
        goto = choice.get("goto")
        raws: list[str] = []
        if isinstance(goto, list):  # 加权随机跳转：每个分支都是一条出边
            raws = [str(item.get("to") or "") for item in goto if isinstance(item, dict)]
        elif goto:
            raws = [str(goto)]
        for raw in raws:
            if not raw:
                continue
            target = resolve_goto(raw)
            if not target or target.startswith("@"):
                continue  # @restart 不参与可达
            out.append({"from": scene_id, "to": target, "kind": "choice", "raw": raw})
    mode = (scene or {}).get("mode") or "normal"
    block = (scene or {}).get(mode) or {}
    for key in mode_edges(mode):
        target = block.get(key)
        if target is not None:
            out.append({"from": scene_id, "to": str(target), "kind": "mode", "raw": f"{mode}.{key}"})
    return out


def reachable_from(scenes: dict, entry: str) -> dict:
    """从 entry 出发 BFS，返回 {reachable, order, depth}。

    注意：Python 的 set 不保序，order 单独用列表记录（Node 的 Set 保插入序）。
    """
    reachable: set[str] = set()
    order: list[str] = []
    depth: dict[str, int] = {}
    queue: list[tuple[str, int]] = [(entry, 0)]
    while queue:
        scene_id, d = queue.pop(0)
        if scene_id in reachable or scene_id not in scenes:
            continue
        reachable.add(scene_id)
        order.append(scene_id)
        depth[scene_id] = d
        for edge in edges_of(scene_id, scenes[scene_id]):
            if edge["to"] not in reachable:
                queue.append((edge["to"], d + 1))
    return {"reachable": reachable, "order": order, "depth": depth}


def analyze(scenes: dict, entry: str) -> dict:
    """全图分析：可达性 + 悬空 + 结局 + 入度统计。"""
    result = reachable_from(scenes, entry)
    reachable, order, depth = result["reachable"], result["order"], result["depth"]
    dangling: list[dict] = []
    ending_ids: list[str] = []
    in_degree: dict[str, int] = {}

    for scene_id, scene in scenes.items():
        if is_ending(scene):
            ending_ids.append(scene_id)
        for edge in edges_of(scene_id, scene):
            in_degree[edge["to"]] = in_degree.get(edge["to"], 0) + 1
            if edge["to"] not in scenes:
                dangling.append(edge)
        # 特殊目标自身的合法性（@loop: 目标必须存在）；加权 goto 逐项检查
        for choice in (scene or {}).get("choices") or []:
            goto = choice.get("goto")
            raws = (
                [str(item.get("to") or "") for item in goto if isinstance(item, dict)]
                if isinstance(goto, list)
                else [str(goto or "")]
            )
            for raw in raws:
                if raw.startswith("@") and not is_special_goto(raw):
                    dangling.append({"from": scene_id, "to": raw, "kind": "special", "raw": raw})
                elif raw.startswith("@loop:"):
                    target = resolve_goto(raw)
                    if target not in scenes:
                        dangling.append({"from": scene_id, "to": target, "kind": "loop", "raw": raw})

    unreachable = [sid for sid in scenes if sid not in reachable]
    return {
        "scenes": len(scenes),
        "reachable": reachable,
        "reachableCount": len(reachable),
        "unreachable": unreachable,
        "order": order,
        "depth": depth,
        "dangling": dangling,
        "endings": ending_ids,
        "endingsReachable": [i for i in ending_ids if i in reachable],
        "deadEnds": [sid for sid in order if in_degree.get(sid, 0) == 0 and sid != entry],
    }


def shortest_path(scenes: dict, entry: str, target_id: str) -> list[str] | None:
    """从 entry 到指定场景的一条最短路径（供测试生成"直达路线"）。"""
    prev: dict[str, str] = {}
    queue = [entry]
    seen = {entry}
    while queue:
        scene_id = queue.pop(0)
        if scene_id == target_id:
            break
        for edge in edges_of(scene_id, scenes.get(scene_id)):
            if edge["to"] in seen:
                continue
            seen.add(edge["to"])
            prev[edge["to"]] = scene_id
            queue.append(edge["to"])
    if target_id not in seen:
        return None
    path = [target_id]
    while path[0] != entry:
        path.insert(0, prev.get(path[0]))
    return path


# ------------------------------------------------------------ 可视化导出（P7）

def _scene_label(scene_id: str, scene) -> str:
    title = (scene or {}).get("title") or scene_id
    return str(title).replace('"', "'")


def to_dot(scenes: dict, entry: str) -> str:
    """导出 Graphviz DOT（结局双圈、入口加粗、mode 场景方框）。"""
    lines = ["digraph scenes {", "  rankdir=LR;", '  node [shape=ellipse];']
    for scene_id, scene in scenes.items():
        mode = (scene or {}).get("mode") or "normal"
        attrs = [f'label="{_scene_label(scene_id, scene)}"']
        if is_ending(scene):
            attrs.append("shape=doublecircle")
        elif mode != "normal":
            attrs.append("shape=box")
        if scene_id == entry:
            attrs.append("penwidth=2")
        lines.append(f'  "{scene_id}" [{", ".join(attrs)}];')
    for scene_id, scene in scenes.items():
        for edge in edges_of(scene_id, scene):
            style = "dashed" if edge["kind"] == "mode" else "solid"
            lines.append(f'  "{edge["from"]}" -> "{edge["to"]}" [style={style}];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_mermaid(scenes: dict, entry: str) -> str:
    """导出 Mermaid flowchart（结局双圈 (( ))、mode 场景方框、mode 边虚线）。

    场景 id 里的 ``-`` / ``.`` 会被 Mermaid 误解析为连线语法，节点 id 统一
    替换为安全形式（label 保留原 id）。
    """
    def nid(scene_id: str) -> str:
        return "n_" + "".join(c if c.isalnum() or c == "_" else "_" for c in scene_id)

    def shape(scene_id: str, scene) -> str:
        label = _scene_label(scene_id, scene)
        mode = (scene or {}).get("mode") or "normal"
        if is_ending(scene):
            return f'{nid(scene_id)}(("{label}"))'
        if mode != "normal":
            return f'{nid(scene_id)}["{label}"]'
        return f'{nid(scene_id)}("{label}")'

    lines = ["flowchart LR"]
    for scene_id, scene in scenes.items():
        lines.append(f"  {shape(scene_id, scene)}")
    for scene_id, scene in scenes.items():
        for edge in edges_of(scene_id, scene):
            arrow = "-.->" if edge["kind"] == "mode" else "-->"
            lines.append(f"  {nid(edge['from'])} {arrow} {nid(edge['to'])}")
    return "\n".join(lines) + "\n"
