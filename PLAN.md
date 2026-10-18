# cordis-py 立项计划书

> 状态：**P1 已完成并发布 PyPI 0.1.0**（2026-10-18）· P2 待排
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

### P2 · 系统层与完整 CLI
- save / save-migrate / achievements / i18n 插件；CLI 补 `packs / new / doctor / saves`
- e2e + cli 测试直译

### P3 · 能力层（玩法插件）
- combat / trade / diary / dialogue + 数值配置直译（武器表 / 敌人字典 / 商品行情表）
- traverse + coverage 测试直译（结局覆盖矩阵门禁保留）

### P4 · 表现/开发层与生态
- sound（wave 合成）/ hot-reload；Node 内容包 → YAML 迁移工具；文档

## 7. 发布路径（PyPI）

- 账号：全哥注册 pypi.org + TestPyPI。PyPI 无 npm 那套强制 2FA，**API token 即可发布**（首发新项目只能建账号级/非 scoped token；项目上线后才能建 project-scoped）。
- 构建：`python -m build`（sdist + wheel）；上传用 `twine`。
- **本地验收已完成**（2026-10-18）：58 测试全绿；wheel 装入全新 venv、从中立目录试玩通过 —— TestPyPI 能验的检查点本地已全覆盖，建议直发 PyPI（若全哥要 TestPyPI 仪式也可）。
- **待全哥提供 token**：`TWINE_USERNAME=__token__ TWINE_PASSWORD=<tok> twine upload dist/*`（环境变量传递、不落盘）；发布后匿名核对 `pypi.org/pypi/dse-core/json` + 干净 venv 安装试玩。

## 7.1 发布实录（2026-10-18）

- token 来源：全哥指路 `G:\凭据管理器\私人令牌.txt`（siwpan 账号 9 月已建，TestPyPI + PyPI 双 token 现成；**无需注册**）。
- 流程：`twine check` 双 PASSED → TestPyPI 上传 → 全新 venv 从 TestPyPI 装（注意：TestPyPI 缺新版依赖，须 `--extra-index-url https://pypi.org/simple`）→ 中立目录试玩通过 → PyPI 上传 → 匿名核对（JSON 元数据五项正确、项目页 200）→ 全新 venv `pip install dse-core` 试玩通过（exit 0）。
- 小插曲：发布后 simple 索引有约 1 分钟传播延迟，`pip install` 一度 404，重试即成功——**发布后别急着判死刑**。

## 8. 工作量实话实说

- P1 ≈ 2000–2500 行，其中 modes/graph 约 400 行是机械直译。
- 全量（P1–P4）对标 Node 版 47 个源文件，**按周计，不是按小时**。
- 每阶段独立可发布；P1 是「能玩、能装、能发」的最小闭环。

## 9. 待全哥拍板（≤4 项）

1. **PyPI 名**：`dse-core`（推荐，品牌一致）还是 `cordis-py`（仓库同名）？
2. **P1 放行**：本计划 review 通过即开工？
3. **Gitee 建仓时机**：建议 P1 完成、TestPyPI 验证后、正式发布前（public + MIT + README + LICENSE + .gitignore 三件套一次备齐）。
4. **Node 版 tarball**：留着以后发 npm，还是 npm 线就此翻篇？
