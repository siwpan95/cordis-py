# cordis-py 立项计划书

> 状态：**P1-P11 全部完成**（0.1.0 / 0.2.0 / 0.3.0 / 0.4.0 / 0.5.0 / **0.6.0** 均已上 PyPI；207 测试全绿）
> 一句话：把 dse-core（字典场景引擎，Node/Cordis 4.0）移植为 **Python 原生引擎**，发布到 PyPI。

---

## 1. 背景与触发

- dse-core（Node 版）发布准备已全部就绪：五套测试全绿、tarball 已产出（`dse-core-0.1.0.tgz`，47 文件 / 97KB）。
- npm 线中止：siwpan 账号不可用（CLI token 于 16:47 被吊销，`E401`；全哥反馈账号已删除）。`dse-core` 在 npm 仍未发布。
- 全哥决定转向 PyPI，方向定名 **cordis-py**。
- **Node 版 `G:\repos\dse-core` 原样保留、持续维护**；cordis-py 是姊妹项目，不是替代。已产出的 tarball 留作以后发 npm 的种子。

## 2. 目标与非目标

**目标**
- Python 原生实现「场景即字典，能力即插件」，`pip install dse-core` 后 `dse play` 能玩。
- 内容包从「可执行 ESM 代码」升级为「数据文件（YAML）」——不需要 import 用户代码，**比 Node 版更安全**。
- P1 结束即可发布 0.1.0（TestPyPI 先行）。

**非目标（明确不做）**
- 不移植 Cordis 框架本身：以约 300 行 Python 原生插件运行时替代（见 §4）。
- 不追求与 Node 版内容包代码级兼容；提供迁移工具（P4）。
- 每阶段独立可发布，不憋大招。

## 3. 包名与仓库（待拍板项已标注）

| 项 | 值 | 状态 |
|---|---|---|
| 本地目录 | `G:\repos\cordis-py` | 本计划落地点 |
| Gitee 仓库 | `cordis-py`（public + MIT） | ✅ 已建仓推送（分支 `p1-core-engine`，匿名可 clone） |
| PyPI 发行名 | **`dse-core`** | ✅ **已发布 0.1.0**（2026-10-18，pypi.org/project/dse-core） |
| import 名 | `dse_core` | 与品牌、README 示例一致 |
| CLI 命令 | `dse` | 与 Node 版一致 |
| 备选 PyPI 名 | `cordis-py` | ✅ 已核实可用；想统一品牌可换（拍板项 1） |

## 4. 架构映射（Node → Python）

| Node 模块 | Python 模块 | 移植难度 |
|---|---|---|
| `lib/modes.mjs`（模式注册表，纯数据+函数） | `dse_core/modes.py` | 1:1 直译 |
| `lib/graph.mjs`（BFS/悬空/结局/最短路径，纯函数） | `dse_core/graph.py` | 1:1 直译 |
| `lib/registry.mjs`（manifest 规范化/校验） | `dse_core/manifest.py` | 逻辑 1:1；加载层从 ESM `import()` 改为数据文件读取 |
| `lib/dict.mjs`（cordis.yml + 内容包合并） | `dse_core/loader.py` | YAML 解析换 PyYAML |
| `schema/scene.schema.json` | 原样复制 + `jsonschema` 校验 | 直接复用 |
| `sdk/index.js`（门面：createEngine/inspectProject/analyze/loadPacks） | `dse_core/sdk.py` | 1:1 |
| `lib/boot.js` + `plugins/engine.js`（主循环） | `dse_core/runtime.py` + `dse_core/plugins/engine.py` | 重写 |
| `plugins/scenes/state/console-io.js`（内核层） | `dse_core/plugins/*.py` | 重写为 Python 类 |
| **Cordis 4.0**（DI + Context + 生命周期） | **`dse_core/runtime.py`**（原生插件运行时） | 重新设计 |
| `cordis.yml`（声明式插件清单） | `dse.yml`（同风格，PyYAML） | 直译 |
| `plugins/combat/trade/diary/dialogue.js` | `dse_core/plugins/*.py`（数据驱动，数值配置直译） | 中 |
| `plugins/save/save-migrate/achievements/i18n.js` | `dse_core/plugins/*.py` | 中 |
| `plugins/sound.js`（node 子进程合成音） | `dse_core/plugins/sound.py`（stdlib `wave` 合成，无子进程） | 中 |
| `plugins/hot-reload.js`（chokidar） | `dse_core/plugins/hot_reload.py`（watchdog 或轮询） | 中 |
| `cli.js`（play/scenes/info/check/packs/new/doctor/saves） | `dse_core/cli.py`（argparse，零依赖） | 中 |
| `tests/{unit,e2e,cli,traverse,coverage}.mjs` | `tests/test_*.py`（pytest） | 直译 |

### 插件运行时设计（cordis-py 的核心）

- `Plugin` 协议：`name`、`inject`（依赖服务名列表）、`setup(ctx)` / `dispose(ctx)`。
- `Context`：服务注册表 + 配置 + 状态容器；按依赖拓扑排序后启动（替代 Cordis 的 DI 自动编排）。
- 配置注入：`dse.yml` 中每条插件 `config` 直接映射为 dataclass。
- 与 Cordis 的差异坦然接受：Python 生态显式注册表比魔法 DI 更地道；`static inject` → `inject = ['state', 'io']`。

## 5. 条件表达式（安全模型升级）

- Node 版：`state.check()` → `new Function`（非沙箱，内容包即可执行代码）。
- Python 版：内容包是**数据**，表达式经 **AST 白名单求值**（仅 BoolOp/Compare/Name/Constant/Subscript/算术；禁调用、禁属性穿透、禁导入）。
- 这是移植中少有的「比原版强」的点，README 当卖点写。

## 6. 分阶段计划

### P1 · 可发布的最小引擎 —— ✅ 已完成（2026-10-17）

- runtime + 内核四插件（scenes / state / console-io / engine 主循环）
- modes / graph / manifest / loader / schema / safety 六件套
- starter 内容包译成 YAML + 示例 `dse.yml` 工程
- unit 测试直译 + pytest 全绿；最小 CLI：`play / check / scenes / info`
- **偏差记录**：combat 参考能力插件从 P3 提前到 P1 —— starter 的战斗线是示例内容包的
  主线路，且 mode 委托架构需要至少一个能力插件来证明；trade / dialogue / diary 仍在 P3。
- **验收**：✅ `dse play --input ...` 脚本跑通战斗线；`dse check` 通过（7 场景 / 3 结局全可达）；
  58 项测试全绿；sdist + wheel 构建成功。**TestPyPI 安装验证待用户放行后执行**（见 §7）。

### P2 · 系统层与完整 CLI —— ✅ 已完成（2026-10-18）

- save / save-migrate / achievements / i18n 四插件（Node 版 1:1 移植）
- save 吸收 dse-core 新版特性：save-migrate 可选集成（版本盖章 + 按链迁移，不 inject）
- CLI 补 packs / saves / doctor / new（7 个模板；`new` 文本级注册进 dse.yml，保留注释格式）
- **引擎加固**：内容用了某模式但无插件接管时**响亮报错**（Node 版静默回退 normal 会把
  mode 场景误判成结局）；`dse doctor` 提供静态交叉核对（模式 × 已装插件）
- **测试**：88 项全绿（P1 58 + P2 30）；e2e 覆盖存档往返、成就随档、v1→v2 迁移、
  战斗中之外无插件模式的失败路径
- **踩坑记账**：① 上一轮四个 Write 被用户中断后整体回滚——**分块落盘 + 即时提交**；
  ② 模式守卫初版漏了 `mode != "normal"` 条件，把 normal 也拦了（6 个 e2e 挂掉）——
  测试即护栏；③ 测试夹具 wiring 要调 setup()（table 在 setup 里建）， stub io 会被
  `ctx.io.print` 教做人。

### P3 · 能力层（玩法插件）—— ✅ 代码完成（2026-10-18，待发版）

- trade：天数循环 + 库存买卖 + 确定性行情（buy/sell/next/info；收市结算 tradeProfit）
- diary：只读回溯（⚠️ 核心约束——重读绝不 goto/不执行 onEnter，已读 ∩ 字典存在才可重读）
- dialogue：话题询问 + 注意点预算（问满强制结束；已问去重；effect 数据驱动）
- 全局命令名单收敛到 plugins/commands.py（combat/trade/diary/dialogue 共用）
- **测试**：97 项全绿（P1 58 + P2 31 + P3 8）；经营全周期逐金可算、对话去重/预算、
  重读零状态变更（与正规进入场景的 onEnter 对照）均有断言

### P4 · 表现/开发层与生态 —— ✅ 代码完成（2026-10-18）

- sound：程序化合成 PCM（波形 + ADSR，stdlib wave 编码）+ 事件订阅 +
  数据驱动音效库；Windows winsound 异步播放，其他平台子进程，无播放器静默降级；
  静音（DSE_MUTE > config.mute）不生成文件，退出清理临时文件
- hot-reload：stdlib 轮询线程（mtime + 防抖，零第三方依赖）→ scenes.reload
  （双缓冲，坏包保留旧字典）→ emit 'hot-reload/applied' → 音效插件发声
- **scenes.reload()**：热更核心机制，从 Node 版补移植（双缓冲 + 回滚内容缓存）
- 内容迁移工具：随 dict-scene-engine 重构交付（该仓 scripts/migrate/，
  export-packs.mjs + json2yaml.py + port-manifest.py，已实证转换 39 包/587 场景）
- **测试**：107 项全绿（合成形状/WAV 头、静音零文件、播放即清理、
  reload 热更/拒坏包/跳未知包、路径白名单、轮询线程集成）

## 7. 发布路径（PyPI）

- 账号：全哥注册 pypi.org + TestPyPI。PyPI 无 npm 那套强制 2FA，**API token 即可发布**（首发新项目只能建账号级/非 scoped token；项目上线后才能建 project-scoped）。
- 构建：`python -m build`（sdist + wheel）；上传用 `twine`。
- **本地验收已完成**（2026-10-18）：58 测试全绿；wheel 装入全新 venv、从中立目录试玩通过 —— TestPyPI 能验的检查点本地已全覆盖，建议直发 PyPI（若全哥要 TestPyPI 仪式也可）。
- **待全哥提供 token**：`TWINE_USERNAME=__token__ TWINE_PASSWORD=<tok> twine upload dist/*`（环境变量传递、不落盘）；发布后匿名核对 `pypi.org/pypi/dse-core/json` + 干净 venv 安装试玩。

## 7.1 发布实录（0.1.0，2026-10-18）

- token 来源：全哥指路 `G:\凭据管理器\私人令牌.txt`（siwpan 账号 9 月已建，TestPyPI + PyPI 双 token 现成；**无需注册**）。
- 流程：`twine check` 双 PASSED → TestPyPI 上传 → 全新 venv 从 TestPyPI 装（注意：TestPyPI 缺新版依赖，须 `--extra-index-url https://pypi.org/simple`）→ 中立目录试玩通过 → PyPI 上传 → 匿名核对（JSON 元数据五项正确、项目页 200）→ 全新 venv `pip install dse-core` 试玩通过（exit 0）。
- 小插曲：发布后 simple 索引有约 1 分钟传播延迟，`pip install` 一度 404，重试即成功——**发布后别急着判死刑**。

## 7.2 发布实录（0.2.0 / 0.3.0，2026-10-18）

- **0.2.0**（P2）：四系统层插件 + CLI 补全 + 模式守卫 + DSE_SAVE_DIR。全链路同 0.1.0 仪式。
- **0.3.0**（P3+P4）：能力层三插件（trade/diary/dialogue）+ sound + hot-reload +
  scenes.reload()。twine check 双 PASSED → 上传 → 匿名核对（项目页 200、
  新 venv `pip install dse-core==0.3.0` 版本正确、`dse doctor` 正常）。
- 至此 **Node 版 47 个源文件对应的引擎能力全部移植完毕**，无剩余缺口。

- token 来源：全哥指路 `G:\凭据管理器\私人令牌.txt`（siwpan 账号 9 月已建，TestPyPI + PyPI 双 token 现成；**无需注册**）。
- 流程：`twine check` 双 PASSED → TestPyPI 上传 → 全新 venv 从 TestPyPI 装（注意：TestPyPI 缺新版依赖，须 `--extra-index-url https://pypi.org/simple`）→ 中立目录试玩通过 → PyPI 上传 → 匿名核对（JSON 元数据五项正确、项目页 200）→ 全新 venv `pip install dse-core` 试玩通过（exit 0）。
- 小插曲：发布后 simple 索引有约 1 分钟传播延迟，`pip install` 一度 404，重试即成功——**发布后别急着判死刑**。

## 7.3 发布实录（0.4.0，2026-10-19）—— P5-P7 增强版

- **P5 内核层**：effect 可逆副作用原语（8 插件迁移 self.on，热重载零残留）+ fiber 状态机
  + 事件五模式（补 parallel/serial）+ config_schema 校验 + doctor 拓扑巡检
- **P6 叙事层**：extraText 条件段 / onExit 效果块 / 加权随机 goto（seed 可复现）
- **P7 工具链**：dse graph（DOT/Mermaid）/ dse test（脚本回归）/ dse export-html（单文件播放器）
- 测试 107 → 150 全绿；twine check 双 PASSED → 上传 → 匿名核对（latest=0.4.0，双文件在列）
- **踩坑记账**：① PyPI JSON 索引传播延迟约 1 分钟（老坑重现）；② 腾讯云 pip 镜像同步
  更慢，venv 验证须 `-i https://pypi.org/simple` 直连官方索引；③ E:\Python314 环境重建后
  twine 未迁回，补装 7.0.0。

## 7.4 发布实录（0.5.0，2026-10-19）—— P8-P10 收官（2026-10-20 补录提交）

- **P8 叙事结构包**：tunnels 隧道 / once 选项 / visits 计数 / emit 效果键（166 测试全绿）
- **P9 体验与数据包**：文本变体 / rollback 回滚 / telemetry 埋点分析（181 测试全绿）
- **P10 运行时深水区**：isolate 隔离域 / 批量热更 / i18n-extract（193 测试全绿）
- 即：0.5.0 = 0.4.0 的 P5-P7 **再加** P8-P10，测试 150 → 193。

### ⚠️ 版本漂移与本次补录的由来

0.5.0 于 2026-10-19 02:08 上传 PyPI，但当时**只在工作树里改了版本号就构建上传，没有随提交入库**
—— 仓库 HEAD 一度停在 0.4.0（P10 代码其实已在，只是版本号没跟进），形成
「PyPI 0.5.0 / 仓库 0.4.0」的漂移。

补录方式是**比对分发包而非凭记忆**：取 PyPI 上 `dse_core-0.5.0.tar.gz` 与仓库 HEAD 逐文件 diff。

- 直接 diff 会显示**几乎全部文件都不同** —— 那是 sdist 用 LF、仓库工作树用 CRLF 造成的**假差异**，
  `diff --strip-trailing-cr` 之后才看得清。
- 忽略行尾后，实质差异**只有两行版本号**：`pyproject.toml` 与 `src/dse_core/sdk.py`；
  `tests/`（除未打包的 `fixtures/`）与 `README.md` 与仓库 HEAD 完全一致。
- 结论：0.5.0 **没有 0.4.0 之外的功能改动**，就是 P5-P10 全量再提一档版本号。本提交据此对齐。

**记账**：① 判断「分发包 vs 仓库差了什么」要先消掉行尾差异，否则会被 CRLF/LF 淹没；
② 发版前先确认版本号已进入 git，别只改工作树 —— 否则下次核对时连「0.5.0 改了什么」都无从查证。

### 版本 tag 补录（2026-10-20）

此前 5 个版本**一个 tag 都没打**（`git tag -l` 为空）。已按「tag 指向该版本内容定型的提交、
不含事后补写的文档提交」这条惯例补上 annotated tag：

| tag | 目标提交 | 该提交 pyproject 版本 | 落点依据 |
|-----|----------|----------------------|----------|
| v0.1.0 | `46d5d0e` | 0.1.0 | PyPI 上传 10-18 10:05 前的最后一个提交（`2e40435` 是上传**后**写的发布实录，不入选） |
| v0.2.0 | `c9234d4` | 0.2.0 | `release: 0.2.0` 提交（10:48，与 PyPI 上传同刻） |
| v0.3.0 | `d7fb894` | 0.3.0 | `release: 0.3.0` 提交（11:03，PyPI 上传 11:04） |
| v0.4.0 | `5bce944` | 0.4.0 | `release: 0.4.0` 提交（08:55，PyPI 上传 08:52） |
| v0.5.0 | `e4f9cbb` | 0.5.0 | 本轮补录的发版提交 |

> 注：PyPI 的 `upload_time` 是 **UTC**，本地提交时间是 **UTC+8**，比对时要先换算
> （0.1.0 的落点就是靠这个换算定出来的 —— 只看提交信息会误选到 `2e40435`）。

### 补充：本地未推送 WIP 中的踩坑记账（2026-10-29 对齐时从 stash 保留）

对齐时发现远端 0.6.0 基线已不含以下三条（原存在于本地未推送的 7.4 实录草稿），
按「资产与历史永远保全」在此保留，供后续决定是否并入正式实录：

- once 记录须按**对象身份**找回原始序号
- rollback 快照必须抢在 `onExit` 结算前（否则 onExit 效果双份）
- telemetry setup 重入未复位 `_enabled`（测试抓到）

## 7.5 发布实录（0.6.0，2026-10-20）—— P11 遍历与覆盖门

### 为什么补这一版

核账时发现 Python 版与 Node 版存在**一处实质能力缺口**，不是文档或版本号的差异：

Node 版 `tests/traverse.mjs` + `tests/coverage.mjs` 有**动态**遍历与结局覆盖两级门，
而 Python 版只有 `dse check`（静态：Schema + 悬空跳转 + 图分析）。两者抓的东西不同：

| | `dse check`（静态） | `dse traverse`（动态） |
|---|---|---|
| 是否执行条件表达式 | ❌ 不执行 | ✅ 按真实状态求值 |
| 是否执行效果（onEnter/onExit/emit） | ❌ | ✅ |
| 能抓「`if` 恒假导致死路」 | ❌ 结构上边是通的 | ✅ |
| 能抓「条件/效果表达式写炸」 | ❌ | ✅ |
| 代价 | 毫秒级 | 秒级（要跑引擎） |

所以这一版是**补齐**，而不是「再提一档版本号」。

### P11 内容

- **`dse_core/traverse.py`（新模块）**
  - `traverse(ctx, entry=, max_steps=, max_revisit=, seed=)`：从 entry 做 **DFS**，
    逐场景调用 `engine.render()` 拿到**当前状态过滤后**的真实选项，沿每条 goto 递归，
    记录走过的边 `(from, to, kind)`、访问场景、可达结局、完整路径数、错误列表。
  - 分支隔离靠 `state.snapshot()/restore()`：兄弟分支互不污染；遍历整体从 `state.reset()`
    开始、`finally` 里还原调用方原状态 —— 遍历是**只读操作**，不留副作用。
  - 终止保证：`max_steps`（缺省 500）+ `max_revisit`（同场景在一条路径上最多进 3 次，
    给 `@loop` 时间循环内容留正常空间又不至于不收敛）。
  - `coverage(scenes, trace, e2e_endings=)`：每个结局须有来源 ——
    `T`（本次遍历走到）或 `E`（调用方 `--e2e` 声明的既有用例），**双缺即失败**。
- **CLI 两个子命令**：`dse traverse`、`dse coverage`，均支持 `--entry/--json/--seed/--root`
  （coverage 另有可重复的 `--e2e`），退出码按门禁结果给（有问题/缺来源 → 1）。

### 实跑验证（打包内的 example 工程）

```
$ dse traverse
访问场景: 7 | 走过边: 9 | 结局: 3
完整路径: 39
可达结局: end-hero, forest-lose, inn-wait
截断分支: start（重访超限 3）        # start 自环，属预期

$ dse coverage
结局总数: 3 | 有来源: 3 | 缺来源: 0
  ✓ end-hero  [T]   ✓ forest-lose  [T]   ✓ inn-wait  [T]
退出码: 0
```

两处**门禁有效性**的反向验证（都确认会失败，不是摆设）：

1. 造一个「没人能走到」的孤儿结局 → `coverage` 退出码 **1**，点名该结局；
   加 `--e2e <该结局>` 后退出码 **0**（E 来源生效）。
2. 造一个「所有选项条件恒假」的场景 → `traverse` 退出码 **1**，
   报 `[start] 无可用去向（所有选项条件均为假）`；而同一工程 `dse check` **通过**
   —— 这正是静态分析看不见、只有动态遍历才能抓的那一类问题。

### 实现过程中踩的坑（记账）

- `SceneService.get()` 对不存在的场景**抛 KeyError 而不是返回 None**，所以遍历前要
  `scenes.has()` 先判 —— 否则「悬空跳转」会被当成崩溃而不是一条 error 记录。
- `SceneService` **没有 `.items()`**，`coverage()` 要取 `getattr(scenes, "dict", scenes)`
  才能同时吃 `SceneService` 和裸 dict。
- `engine.render()` 会**直接往 stdout 打印整个界面**（标题/正文/选项），不吞掉的话跑一次
  traverse 会把全树剧情刷满屏 —— 用 `contextlib.redirect_stdout(io.StringIO())` 只为拿返回值。
- 截断记录一开始按分支累加，同一个自环撞 27 次就刷 27 条一模一样的记录、把真问题淹没；
  改为「场景+原因」去重。
- `create_engine(entry=...)` 会写 **`DSE_ENTRY` 进程环境变量且不清理**，遍历结束后必须
  还原（CLI 里 save/restore），否则同进程后续命令会被这次 `--entry` 带偏。
- 「悬空 goto」这一项本想用 traverse 抓，结果发现 `SceneService.rebuild()` 在**加载期**
  就抛 `ValueError("存在未定义的场景跳转")` —— 门禁已经更早生效了，测试改为断言加载期拒绝。

### 发版

- 版本号 0.5.0 → 0.6.0（`pyproject.toml` + `sdk.__version__`，**这次随提交入库**）。
- 测试 193 → **207 全绿**（新增 `tests/test_traverse_p11.py` 14 项）。
- `twine check` 双 PASSED → 上传 PyPI → 匿名核对 JSON 元数据 + 全新 venv 安装试玩。

## 8. 工作量实话实说

- P1 ≈ 2000–2500 行，其中 modes/graph 约 400 行是机械直译。
- 全量（P1–P4）对标 Node 版 47 个源文件，**按周计，不是按小时**。
- 每阶段独立可发布；P1 是「能玩、能装、能发」的最小闭环。

## 9. 待全哥拍板（≤4 项）

1. **PyPI 名**：`dse-core`（推荐，品牌一致）还是 `cordis-py`（仓库同名）？
2. **P1 放行**：本计划 review 通过即开工？
3. **Gitee 建仓时机**：建议 P1 完成、TestPyPI 验证后、正式发布前（public + MIT + README + LICENSE + .gitignore 三件套一次备齐）。
4. **Node 版 tarball**：留着以后发 npm，还是 npm 线就此翻篇？
