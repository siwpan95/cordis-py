# dse-core · 字典场景引擎（Python 版）

> Dictionary Scene Engine —— 场景即字典，能力即插件。
> 本仓库是引擎的 **Python 原生实现**（cordis-py），Node/Cordis 版见姊妹仓库
> [dse-core](https://gitee.com/siwpan/dse-core)。立项计划书见 [PLAN.md](PLAN.md)。

## 30 秒上手

```bash
pip install -e .          # 开发安装（或 pip install dse-core）
dse play                  # 玩自带示例内容包（战斗线最小可玩版）
dse play --input "1,1,a,a,a"   # 脚本模式：无交互跑完整条线路（CI 友好）
dse scenes                # 列出场景
dse check                 # 校验内容（悬空跳转等），有问题退出码 1
```

## 内容包 = 数据，不是代码

与 Node 版最大的差异：内容包是 **YAML 数据文件**，不是可执行模块。
条件表达式经 **AST 白名单求值**（仅比较/布尔/算术/下标，禁调用、禁下划线属性）——
不需要 import 任何用户代码，也没有 `new Function`。

```yaml
# content/starter.yml（节选）
pack:
  id: starter
  name: 启程
  entry: start
scenes:
  start:
    title: 村口 · 启程
    text: '天没亮透……三条路摆在你面前。'
    choices:
      - { text: '往北进山', do: { 'flags.starter.mountain': true }, goto: forest }
  forest:
    text: '……一只独眼狼从阴影里站起来。'
    choices:
      - { text: '拔剑', goto: wolf-fight }
  wolf-fight:
    mode: battle                      # 非 normal 模式由能力插件接管
    battle: { enemy: wolf, onWin: forest-win, onLose: forest-lose, onFlee: start }
```

## 架构

```
dse_core/
├── modes.py       # 模式注册表（scene.mode 唯一真源）
├── graph.py       # 场景图静态分析（可达性/悬空/结局/最短路径，纯函数）
├── manifest.py    # 内容包元数据（规范化/校验）
├── loader.py      # 工程加载（dse.yml + YAML 内容包合并）
├── schema.py      # JSON Schema 校验（schema/scene.schema.json）
├── safety.py      # 条件表达式 AST 白名单求值
├── runtime.py     # 插件运行时（Service/Context/依赖拓扑/事件）—— Cordis 的 Python 原生替代
├── sdk.py         # 编程式门面（create_engine / play / inspect_project）
├── cli.py         # 命令行 dse：play / scenes / info / check
└── plugins/       # 内核层 scenes/state/console_io/engine + 参考能力插件 combat
```

插件用声明式依赖组装，引擎零改动即可扩展：

```python
from dse_core.runtime import Service

class MyPlugin(Service):
    name = "my-plugin"
    inject = ("state", "io")          # 等价于 Cordis 的 static inject
    def setup(self):
        self.ctx.on("scene/enter", lambda scene_id, scene: ...)
```

## 与 Node 版的关系

- Node 版持续维护；本仓库是**移植版**，内容格式不互通（YAML ↔ ESM）。
- 移植路线图：**P1 可发布最小引擎（本阶段）→ P2 系统层（save/achievements/i18n）+ 完整 CLI → P3 能力层（trade/dialogue/diary）→ P4 表现层（sound/hot-reload）+ 内容迁移工具**。详见 [PLAN.md](PLAN.md)。

## 安全模型

- 内容包是数据；表达式求值禁调用与下划线属性访问。
- `dse.yml` 与内容包路径均限制在工程目录内（路径白名单）。

## License

MIT · Copyright (c) 2026 全哥 (siwpan)
