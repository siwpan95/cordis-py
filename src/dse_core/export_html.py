"""单文件 HTML 播放器导出（P7，对标 Twine 的单文件发布）。

把一个 normal 模式的场景工程导出为零依赖的单文件 HTML：内嵌场景字典 JSON +
浏览器端 JS 解释器（插值 / 条件选项 / extraText / onEnter / onExit / do 效果 /
加权随机 goto / @restart），双击即玩、可直接发 itch.io 或静态托管。

**能力边界（响亮告知，不静默降级）**：

- 非 normal 模式场景（battle / trade / diary / dialogue）由 Python 插件接管，
  浏览器端无插件运行时 —— 导出时逐条警告；运行端遇到时显示提示并视为结局。
- 条件表达式在浏览器端经「Python → JS 语法翻译 + Function 求值」执行：
  支持比较 / and-or-not / 算术 / 点路径与下标；不支持 ``//`` 整除与函数调用
  （引擎侧本来就不允许调用）。导出播放器**信任内容包表达式**（与 Twine 相同
  的信任模型），不要在导出工程里引用不可信内容包。
- 加权随机在浏览器端用 Math.random（无 seed 复现语义；seed 仅引擎侧有效）。
"""

from __future__ import annotations

import json
import re


def py_expr_to_js(expr: str) -> str:
    """把引擎的 Python 条件表达式翻译成 JS 等价式（白名单语法的子集直译）。"""
    s = str(expr)
    for py, js in (("True", "true"), ("False", "false"), ("None", "null"),
                   ("and", "&&"), ("or", "||")):
        s = re.sub(rf"\b{py}\b", js, s)
    s = re.sub(r"\bnot\s+", "!", s)  # "not x" → "!x"（吃掉原空格）
    if "//" in s:
        raise ValueError(f'表达式含 Python 整除 "//"，导出播放器不支持: {expr!r}')
    return s


def find_unsupported(scenes: dict) -> list[str]:
    """导出前静态扫描：返回 (mode 场景 / 不可译表达式) 警告列表。"""
    warnings: list[str] = []
    for scene_id, scene in scenes.items():
        if not isinstance(scene, dict):
            continue
        mode = scene.get("mode") or "normal"
        if mode != "normal":
            warnings.append(f"#{scene_id}: mode={mode} 场景浏览器端无插件接管，将显示提示并视为结局")
        exprs = [c.get("if") for c in scene.get("choices") or [] if isinstance(c, dict)]
        exprs += [seg.get("if") for seg in scene.get("extraText") or [] if isinstance(seg, dict)]
        for expr in exprs:
            if expr:
                try:
                    py_expr_to_js(expr)
                except ValueError as exc:
                    warnings.append(f"#{scene_id}: {exc}")
    return warnings


_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  body { max-width: 42em; margin: 2em auto; padding: 0 1em; background: #faf8f5;
         color: #2b2b2b; font-family: "Georgia", "Songti SC", serif; line-height: 1.8; }
  h1 { font-size: 1.3em; border-bottom: 1px solid #ccc; padding-bottom: .4em; }
  #text { white-space: pre-wrap; margin: 1.2em 0; }
  .choice { display: block; margin: .5em 0; padding: .6em 1em; background: #fff;
            border: 1px solid #d8d2c8; border-radius: 6px; cursor: pointer;
            text-align: left; font-size: 1em; font-family: inherit; width: 100%; }
  .choice:hover { background: #f0ebe2; border-color: #b8b0a0; }
  #ending { color: #888; font-style: italic; }
  footer { margin-top: 3em; font-size: .8em; color: #aaa; }
</style>
</head>
<body>
<h1 id="title"></h1>
<div id="text"></div>
<div id="choices"></div>
<div id="ending"></div>
<footer>dse-core 单文件导出 · 字典场景引擎</footer>
<script>
// 注：不能用 "use strict" —— strict 模式禁用 with，而条件表达式求值依赖 with(S) 作用域
const GAME = __DATA__;

let state = JSON.parse(JSON.stringify(GAME.initial));
let current = GAME.entry;
let pendingExit = null;

function getPath(path) {
  let obj = state;
  for (const key of String(path).split(".")) {
    if (obj === null || typeof obj !== "object" || !(key in obj)) return null;
    obj = obj[key];
  }
  return obj;
}
function setPath(path, value) {
  const keys = String(path).split(".");
  let obj = state;
  for (const key of keys.slice(0, -1)) {
    if (typeof obj[key] !== "object" || obj[key] === null) obj[key] = {};
    obj = obj[key];
  }
  obj[keys[keys.length - 1]] = value;
}
function applyEffects(effects) {
  if (!effects) return;
  for (const [path, value] of Object.entries(effects)) {
    const cur = getPath(path);
    const isNum = (v) => typeof v === "number";
    setPath(path, isNum(value) && isNum(cur) ? cur + value : value);
  }
}
function interpolate(text) {
  return String(text == null ? "" : text).replace(/\\{([\\w.$]+)\\}/g, (m, p) => {
    const v = getPath(p);
    return v === null || v === undefined ? m : String(v);
  });
}
function checkExpr(expr) {
  if (!expr) return true;
  try {
    return !!(new Function("S", "with(S){ return (" + expr + "); }"))(state);
  } catch (e) { console.warn("条件求值失败:", expr, e); return false; }
}
function pickWeighted(options) {
  const total = options.reduce((s, o) => s + (o.weight || 1), 0);
  let pick = Math.random() * total;
  for (const o of options) { pick -= (o.weight || 1); if (pick < 0) return o.to; }
  return options[options.length - 1].to;
}

function render() {
  if (pendingExit !== null) {           // 旧场景 onExit 结算
    const old = GAME.scenes[pendingExit];
    pendingExit = null;
    if (old) applyEffects(old.onExit);
  }
  const scene = GAME.scenes[current];
  if (!scene) { document.getElementById("text").textContent = "（场景缺失: " + current + "）"; return; }
  applyEffects(scene.onEnter);

  const mode = scene.mode || "normal";
  let text = scene.text || "";
  for (const seg of scene.extraText || []) {
    if (checkExpr(seg.if)) text += "\\n" + (seg.text || "");
  }
  document.getElementById("title").textContent = interpolate(scene.title || current);
  document.getElementById("text").textContent = interpolate(text);

  const box = document.getElementById("choices");
  box.innerHTML = "";
  document.getElementById("ending").textContent = "";

  if (mode !== "normal") {
    document.getElementById("ending").textContent =
      "（此场景使用 " + mode + " 模式，单文件导出版不支持插件接管 —— 到此为止）";
    addRestart(box);
    return;
  }
  const choices = (scene.choices || []).filter((c) => checkExpr(c.if));
  if (choices.length === 0) {
    document.getElementById("ending").textContent = "（完）";
    addRestart(box);
    return;
  }
  choices.forEach((choice) => {
    const btn = document.createElement("button");
    btn.className = "choice";
    btn.textContent = interpolate(choice.text);
    btn.onclick = () => {
      applyEffects(choice.do);
      let goto = choice.goto;
      if (Array.isArray(goto)) goto = pickWeighted(goto);
      if (goto === "@restart") {
        state = JSON.parse(JSON.stringify(GAME.initial));
        current = GAME.entry;
      } else if (typeof goto === "string" && goto.startsWith("@loop:")) {
        current = goto.slice(6);
      } else if (typeof goto === "string") {
        pendingExit = current;
        current = goto;
      }
      render();
    };
    box.appendChild(btn);
  });
}
function addRestart(box) {
  const btn = document.createElement("button");
  btn.className = "choice";
  btn.textContent = "再来一次";
  btn.onclick = () => {
    state = JSON.parse(JSON.stringify(GAME.initial));
    pendingExit = null;
    current = GAME.entry;
    render();
  };
  box.appendChild(btn);
}
render();
</script>
</body>
</html>
"""


def render_html(scenes: dict, entry: str, initial: dict, title: str = "字典场景引擎") -> str:
    """生成单文件 HTML 播放器文本。"""
    data = {"scenes": scenes, "entry": entry, "initial": initial or {}}
    payload = json.dumps(data, ensure_ascii=False)
    return _TEMPLATE.replace("__TITLE__", str(title)).replace("__DATA__", payload)
