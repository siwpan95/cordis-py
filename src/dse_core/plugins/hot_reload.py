"""内容热重载插件 —— 「改字典，游戏内即时生效」（引擎零改动）。

移植自 dse-core(Node) plugins/hot-reload.js。

监听内容包目录，YAML 文件变化时（防抖后）：
1. scenes.reload(path) 重新读取并重建场景字典（双缓冲，失败保留旧内容）
2. emit 'hot-reload/applied' 通知其他插件（音效插件会发声）
3. io.wake('') 请求重渲染 —— 交互模式下输入阻塞在 input()，
   下一条输入/重绘自然用上新字典（Node 的事件循环可打断等待，Python 不能）

这正是 Cordis 论文「时空可组合性」的落地体验：玩家状态（时间轴）完全
保留，只有空间（场景字典）被更新。

实现说明：Node 用 chokidar（fs 事件）；Python 版用 stdlib 轮询线程
（mtime 比对 + 防抖），零第三方依赖。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from ..runtime import Service

_PATTERNS = ("*.yml", "*.yaml")


class HotReloadService(Service):
    """内容热重载服务（ctx['hot-reload']，可选插件）。"""

    name = "hot-reload"
    inject = ("scenes", "io")

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.paths = [str(p) for p in (self.config.get("paths") or ["./content"])]
        self.debounce = float(self.config.get("debounce") or 200) / 1000.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._mtimes: dict[Path, float] = {}

    def setup(self) -> None:
        # 路径白名单：只监听工程内的目录
        root = self.ctx.root.resolve()
        watched: list[Path] = []
        for p in self.paths:
            path = (root / p).resolve()
            if path != root and root not in path.parents:
                raise ValueError(f"热重载监听路径越出工程目录: {p}")
            watched.append(path)
        for base in watched:
            if base.is_dir():
                for pattern in _PATTERNS:
                    for f in base.rglob(pattern):
                        self._mtimes[f] = f.stat().st_mtime
        self._thread = threading.Thread(target=self._loop, args=(watched,), daemon=True)
        self._thread.start()
        self.ctx.info("hot-reload", f"watching {', '.join(self.paths)}")

    def _loop(self, watched: list[Path]) -> None:
        """轮询线程：mtime 比对 + 防抖。"""
        while not self._stop.wait(0.2):
            changed: list[Path] = []
            for base in watched:
                if not base.is_dir():
                    continue
                for pattern in _PATTERNS:
                    for f in base.rglob(pattern):
                        try:
                            mtime = f.stat().st_mtime
                        except OSError:
                            continue
                        if self._mtimes.get(f) != mtime:
                            self._mtimes[f] = mtime
                            changed.append(f)
            if not changed:
                continue
            time.sleep(self.debounce)  # 防抖：等写入稳定
            self._apply_many(changed)

    def _apply_many(self, files: list[Path]) -> None:
        """P10 批量提交：防抖窗口内的多文件变更只 rebuild 一次（逐包 emit 不变）。"""
        root = self.ctx.root.resolve()
        rels: list[str] = []
        for f in files:
            # 转成配置里 packs 的相对路径形式（./content/x.yml）。基准是 ctx 根
            # 而非 cwd：从工程外启动时 cwd ≠ 根，相对路径会带上 ../ 前缀导致找不到包
            try:
                rels.append("./" + f.resolve().relative_to(root).as_posix())
            except ValueError:
                continue
        if not rels:
            return
        results = self.ctx.scenes.reload_many(rels)
        applied = [rel for rel, ok in results.items() if ok]
        for rel in applied:
            self.ctx.io.print(f"  ⚡ 内容已热更新：{rel}（场景总数 {self.ctx.scenes.size}）")
            self.ctx.emit("hot-reload/applied", rel)
        if applied:
            self.ctx.io.wake("")

    def _apply(self, file: Path) -> None:
        # 转成配置里 packs 的相对路径形式（./content/x.yml）。基准是 ctx 根
        # 而非 cwd：从工程外启动时 cwd ≠ 根，相对路径会带上 ../ 前缀导致找不到包
        root = self.ctx.root.resolve()
        try:
            rel = "./" + file.resolve().relative_to(root).as_posix()
        except ValueError:
            return
        if not self.ctx.scenes.reload(rel):
            return
        self.ctx.io.print(f"  ⚡ 内容已热更新：{rel}（场景总数 {self.ctx.scenes.size}）")
        self.ctx.emit("hot-reload/applied", rel)
        self.ctx.io.wake("")

    def dispose(self) -> None:
        self._stop.set()
