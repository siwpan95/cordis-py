# dse-core · 字典场景引擎（Python 版）

## 仓库角色定位（投资组合分级 ①）

> 本仓在 siwpan 投资组合（D:/projects/repos，共 133 仓）中定级为 **① 核心推进**，领域 **游戏引擎/框架**，定位 **引擎平台层**。
> **角色**：dse-core 的 Python 版场景引擎内核，随 dse-core 维护。
> **维护策略**：① 核心推进——持续投入、不允许冻结；随所属收敛点 / 流水线长期演进。
> 投资组合统一分级索引（多机可查）：[组合分级决策索引 · allin 事实源](https://gitee.com/siwpan/allin/blob/master/docs/事实源/组合分级决策索引.md)。

> Dictionary Scene Engine —— 场景即字典，能力即插件。
> 本仓库是引擎的 **Python 原生实现**（cordis-py），Node/Cordis 版见姊妹仓库
> [dse-core](https://gitee.com/siwpan/dse-core)。立项计划书见 [PLAN.md](PLAN.md)。

[![PyPI](https://img.shields.io/pypi/v/dse-core)](https://pypi.org/project/dse-core/)
[![Python](https://img.shields.io/pypi/pyversions/dse-core)](https://pypi.org/project/dse-core/)
[![License](https://img.shields.io/pypi/l/dse-core)](https://pypi.org/project/dse-core/)

**PyPI**：<https://pypi.org/project/dse-core/> ｜ **发行名 `dse-core` / 导入名 `dse_core`**
（连字符 vs 下划线；CLI 命令是 `dse`。⚠ 别和 Gitee 上的 Node 版仓库 `siwpan/dse-core` 弄混 ——
**PyPI 上的 `dse-core` 就是本仓**，见 `pyproject.toml` 的 `name`。）

> **版本已对齐（2026-10-20）**：PyPI 最新 = `pyproject.toml` = `dse_core.__version__` = **0.5.0**。
> 此前存在漂移 —— 0.5.0 上传时只改了工作树版本号、未随提交入库，仓库一度停在 0.4.0；
> 已按分发包比对结果补发版提交对齐（详见 [PLAN.md §7.4](PLAN.md)）。

## 30 秒上手

```bash
pip install dse-core      # 从 PyPI 安装（开发安装见文末）
dse play                  # 玩自带示例内容包（战斗线最小可玩版）
dse play --input "1,1,a,a,a"   # 脚本模式：无交互跑完整条线路（CI 友好）
dse scenes                # 列出场景
dse packs                 # 列出内容包（manifest / 依赖声明）
dse check                 # 静态校验内容（Schema / 悬空跳转），有问题退出码 1
dse traverse              # 动态遍历：真的跑引擎走遍全图，执行每条 goto 边/效果/条件
dse coverage              # 结局覆盖门：每个结局须有 traverse(T) 或 e2e(E) 来源，双缺退出码 1
dse doctor                # 体检 + 内容模式 vs 已装插件交叉核对
dse saves                 # 离线列出存档位
dse new my-pack --template hub   # 脚手架生成 YAML 内容包并挂进 dse.yml
dse graph --format mermaid       # P7：导出场景图（Mermaid / DOT，Twine 图谱的 CLI 对应物）
dse test --script "1,1,a" --expect-scene end-rich --expect "gold >= 10"   # P7：脚本化回归（CI 友好）
dse export-html -o game.html     # P7：导出单文件 HTML 播放器（normal 模式工程，双击即玩）
```

自带示例工程随包发布（`src/dse_core/example/`）：在含 `dse.yml` 的目录里
运行 `dse play` 玩你自己的工程，否则玩包内示例。

### 两道内容门：check 管结构，traverse 管跑得通

`dse check` 是**静态**的（毫秒级）：看 Schema、看悬空跳转、看图的连通性，**不执行**任何条件或效果。
`dse traverse` 是**动态**的（秒级）：真的把引擎跑起来，在每个场景用当时的真实状态求值条件、
执行效果、跟随实际跳转。两者抓的问题不重叠：

| 问题 | `dse check` | `dse traverse` |
|------|:--:|:--:|
| 悬空跳转、Schema 不符 | ✅ | — |
| 条件表达式写炸（求值抛异常） | ❌ | ✅ |
| 选项条件恒假，场景实际是死路 | ❌（结构上边是通的） | ✅ |
| 新加了结局但没有任何路径能到 | ❌ | ✅（配合 `dse coverage`） |

```bash
dse traverse --json                       # 结构化输出，便于 CI 解析
dse coverage --e2e end-secret             # 声明某个结局已由 e2e 用例覆盖（可重复）
```

`traverse` 会从 `entry` 做 DFS，用 `state.snapshot()/restore()` 隔离分支，结束后还原现场 ——
**只读操作，不留副作用**。时间循环内容（`@loop`）靠 `--max-revisit`（缺省 3）与
`--max-steps`（缺省 500）收敛，撞限的分支会如实报「截断」而不是静默跳过。

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

P6 叙事增强（对标 Ink/Twine）：

```yaml
scenes:
  crossroad:
    text: '两条路摆在你面前。'
    onEnter: { visits: +1 }             # 进入时执行（已有）
    onExit: { gold: +10 }               # P6：离开场景时结算，先于新场景 onEnter
    extraText:                          # P6：条件文本段，求值为真才拼接
      - if: 'flags.met_wolf'
        text: '你认得林间那道爪痕。'
    choices:
      - text: 掷命运硬币                 # P6：加权随机跳转
        goto:
          - { to: lucky, weight: 1 }
          - { to: unlucky, weight: 3 }
```

加权随机的确定性来源：`dse.yml` 里 `engine.config.seed` 固定后结果可复现
（测试 / CI 友好）；缺省真随机。rng 状态不入存档，读档后重新洗牌。

P8 叙事结构（对标 Ink tunnels / 一次性选项 / 访问计数）：

```yaml
scenes:
  plaza:
    text: '这是你第 {visits.plaza} 次站在这里。'   # visits 内建计数，先于 onEnter
    choices:
      - text: 逛商店
        goto: { call: shop }       # tunnels：压栈跳转，可复用内容块
      - text: 看一眼告示牌
        once: true                 # 选过即消失；once: <key> 自定义稳定键（推荐）
        do: { gold: +1, emit: notice/read }   # emit：事件桥接宿主插件，不写状态
        goto: plaza
  shop:
    text: '老板：随便看。'
    choices:
      - { text: 离开商店, goto: '@return' }    # 弹栈返回调用点；空栈响亮报错
```

`once` 记录于 `state.onceSeen`，随存档持久化；`@restart` / `@loop:` 会清空
调用栈与 once 记录（全量重置语义）。

P9 体验与数据（文本变体 / 回滚 / 埋点分析）：

```yaml
scenes:
  hall:
    text: '兜底文本'
    variants: ['大厅空荡荡的。', '大厅里点起了灯。', '大厅传来回声。']
    variantMode: cycle        # 按 visits 轮转；shuffle = 随机（seed 可复现）
```

- **rollback**：游戏内输入 `rollback [n]`（别名 `rb`/`back`）回退 n 个选择点。
  历史快照栈上限 `engine.config.maxHistory`（缺省 50）；语义是时间回溯
  （重进场景会再跑 visits/onEnter，净效果与「未曾离开」一致）；历史属会话，
  读档后清空。导出的 HTML 播放器自带「↩ 回滚一步」按钮。
- **telemetry 埋点**：dse.yml 加 `- id: telemetry` 后，游玩过程的事件
  （会话/进场景/选项/结局）JSONL 落盘 `telemetry.jsonl`（限工程目录内，
  `DSE_TELEMETRY=0` 一键关闭）；`dse analyze` 输出场景访问 Top、选项分布
  百分比、结局到达率 —— 独立作者的「选择埋点 → 迭代闭环」。

P10 运行时深水区（对齐 Cordis rc.10 机制）：

```python
child = ctx.isolate("state", "scenes")   # 隔离域：列出服务独立注册
child.plugin(StateService, {...})        # 同名不同实例，互不干扰
child.start()                            # 未隔离服务沿父链解析；事件总线全局共享
```

- **ctx.isolate**：服务隔离域（测试隔离 / 多会话并存）；隔离名单内的服务
  不向上穿透（未注册时响亮 AttributeError），`ctx.inspect()` 聚合子域 fiber
  并标注 realm 深度
- **批量热更**：`scenes.reload_many(rels)` —— 防抖窗口内多文件变更只
  rebuild 一次；组合校验失败整体回滚，不留「一半新一半旧」中间态
- **dse i18n-extract**：扫场景文本生成 `i18n/<locale>.yml` 待翻译表
  （key = `<场景>.<字段>[.<序号>]`）；增量合并保留已译值，下线 key 进注释块
  不静默丢翻译；已用 `@key@` 接管的内容自动跳过

## 架构

```
dse_core/
├── modes.py       # 模式注册表（scene.mode 唯一真源）
├── graph.py       # 场景图静态分析（可达性/悬空/结局/最短路径，纯函数）
├── traverse.py    # 场景图动态遍历（真跑引擎：DFS + 状态隔离 + 结局覆盖门）
├── manifest.py    # 内容包元数据（规范化/校验）
├── loader.py      # 工程加载（dse.yml + YAML 内容包合并）
├── schema.py      # JSON Schema 校验（schema/scene.schema.json）
├── safety.py      # 条件表达式 AST 白名单求值
├── runtime.py     # 插件运行时（Service/Context/依赖拓扑/事件）—— Cordis 的 Python 原生替代
├── sdk.py         # 编程式门面（create_engine / play / inspect_project）
├── cli.py         # 命令行 dse：play / scenes / info / check / traverse / coverage / packs / saves / doctor / new
└── plugins/       # 内核层 scenes/state/console_io/engine
                   # 能力层 combat/trade/diary/dialogue（各接管一种 scene.mode）
                   # 系统层 save/save-migrate/achievements/i18n
                   # 表现层 sound（程序化合成，静音/清理）· 开发层 hot-reload（轮询热更）
```

插件用声明式依赖组装，引擎零改动即可扩展：

```python
from dse_core.runtime import Service

class MyPlugin(Service):
    name = "my-plugin"
    inject = ("state", "io")          # 等价于 Cordis 的 static inject
    config_schema = {                  # P5：配置校验（required/properties，缺键响亮报错）
        "properties": {"level": {"type": "int", "default": 1}}
    }
    def setup(self):
        self.on("scene/enter", lambda scene_id, scene: ...)  # P5：随 dispose 自动摘除
        self.effect(lambda: open_resource())   # P5：返回的 disposer 随 dispose 自动回滚
```

**运行时增强**（P5，对齐 Cordis 4.0）：

- `ctx.effect()` / `self.on()` —— 可逆副作用原语：插件卸载时 disposer 自动逆序
  回滚、监听器自动摘除（热重载不再累积残留）
- fiber 生命周期状态机（PENDING → LOADING → ACTIVE / FAILED → DISPOSED），
  `ctx.inspect()` 快照巡检；`dse doctor` 静态输出插件拓扑启动顺序
- 事件分发五模式齐备：`emit`（观察）/ `parallel`（容错扇出）/ `serial`
  （遇错中断）/ `bail`（委托）/ `pipeline`（即 waterfall，返回值链）

**系统层插件**（P2，`dse.yml` 里按 id 启用）：

| 插件 | 能力 |
|---|---|
| `save` | save/load/slots 命令；slot 白名单 + 原子落盘 + 读档结构校验 + 场景改名兜底 |
| `save-migrate` | 存档版本链迁移（`config.migrations` 挂模块，旧档不失效） |
| `achievements` | 事件驱动成就解锁（scene/enter + choice/made），随档持久化 |
| `i18n` | `@key@` 查表替换（未命中原样保留）、`lang` 命令切换语言 |

## 与 Node 版的关系

- Node 版持续维护；本仓库是**移植版**，内容格式不互通（YAML ↔ ESM）。
- 移植路线图：**P1 可发布最小引擎 ✅ → P2 系统层与完整 CLI ✅ → P3 能力层 ✅ → P4 表现/开发层 ✅（sound/hot-reload；Node→YAML 迁移工具随 dict-scene-engine 重构交付）**。详见 [PLAN.md](PLAN.md)。
- **已知边界**：内容用了某模式但没装对应插件时，引擎**响亮报错**（而非 Node 版的静默回退）——`dse doctor` 可静态交叉核对。

## 安全模型

- 内容包是数据；表达式求值禁调用与下划线属性访问。
- `dse.yml` 与内容包路径均限制在工程目录内（路径白名单）。

## License

MIT · Copyright (c) 2026 全哥 (siwpan)
