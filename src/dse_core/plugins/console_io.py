"""终端 IO 适配器：把「输入/输出」抽象为 ctx.io 服务。

移植自 dse-core(Node) plugins/console-io.js。换 UI（Web / Discord）时
只需替换本插件，引擎与其他插件不动。

与 Node 版的差异：Python 主循环是同步的，交互模式直接用 input()；
EOF（Ctrl+D / 管道结束）返回 'quit'，与 Node 的 eof 语义一致。

脚本模式（CLI 非交互 / CI）：环境变量 DSE_INPUT 为逗号或换行分隔的输入
序列，ask() 按序取出并回显；序列用尽后返回 'quit'，让引擎走正常退出流程
（打印提示 → dispose → 退出码 0），而不是卡在等待输入上。
"""

from __future__ import annotations

import os
import re
import sys

from ..runtime import Service


class ConsoleIO(Service):
    """终端 IO 服务（ctx.io）。"""

    name = "io"
    inject = ()

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        raw = os.environ.get("DSE_INPUT")
        self.scripted: list[str] | None = (
            [s.strip() for s in re.split(r"[,\n]", raw) if s.strip()] if raw else None
        )
        if self.scripted is not None:
            self.ctx.info("io", f"scripted input: {len(self.scripted)} steps")

    def print(self, text: str = "") -> None:
        sys.stdout.write(str(text) + "\n")

    def blank(self) -> None:
        self.print("")

    def ask(self, prompt: str = "> ") -> str:
        """读取一行输入。脚本模式按序取用（用尽返回 quit）；交互模式 EOF 亦返回 quit。"""
        if self.scripted is not None:
            nxt = self.scripted.pop(0) if self.scripted else "quit"
            sys.stdout.write(f"{prompt}{nxt}\n")
            sys.stdout.flush()
            return nxt
        try:
            return input(prompt).strip()
        except EOFError:
            return "quit"

    def wake(self, text: str = "") -> None:
        """注入一条虚拟输入（热重载等场景用来打断等待、触发重渲染）。"""
        if self.scripted is None:
            self.scripted = []
        self.scripted.insert(0, text)
