"""本地化插件（骨架）—— 文本 ID → 字符串表。

移植自 dse-core(Node) plugins/i18n.js。

渐进启用，不破坏既有内容：
- 识别 `@KEY@` 形式的引用，命中则替换为本地化文本；未命中原样保留
  （内容里直接写中文、不写 ID 的老内容完全不受影响）；
- locale 优先级：state.locale > 环境变量 DSE_LOCALE > dse.yml defaultLocale。

命令：`lang` 查看当前语言 / `lang en-US` 切换。
"""

from __future__ import annotations

import os
import re

from ..runtime import Service

_KEY_PATTERN = re.compile(r"@([A-Za-z0-9_.-]+)@")


class I18nService(Service):
    """本地化服务（ctx.i18n，可选插件）。"""

    name = "i18n"
    inject = ("state",)

    def __init__(self, ctx, config):
        super().__init__(ctx, config)
        self.tables = self.config.get("locales") or {}
        self.default_locale = self.config.get("defaultLocale") or "zh-CN"
        self.misses: set[str] = set()

    def setup(self) -> None:
        # 文本渲染管道：引擎插值之后、其他装饰之前替换
        self.on("text/render", self.translate)
        self.on("engine/command", self.handle)
        self.ctx.info("i18n", f"locale={self.locale()}, tables={len(self.tables)}")

    # ------------------------------------------------------------ 查表

    def locale(self) -> str:
        """当前语言：state.locale > DSE_LOCALE > 配置默认。"""
        current = self.ctx.state.get("locale")
        return current or os.environ.get("DSE_LOCALE") or self.default_locale

    def lookup(self, key: str, locale: str | None = None):
        """查表：key → 文本；未命中返回 None（调用方决定回退）。"""
        locale = locale or self.locale()
        table = self.tables.get(locale)
        if table and key in table:
            return table[key]
        fallback = self.tables.get(self.default_locale)
        if fallback and key in fallback:
            return fallback[key]
        return None

    def translate(self, text):
        """翻译一段文本：把其中的 @key@ 替换为本地化文本，未命中保持原样。"""
        if not isinstance(text, str) or "@" not in text:
            return text

        def replace(match: "re.Match") -> str:
            value = self.lookup(match.group(1))
            if value is None:
                self.misses.add(match.group(1))
                return match.group(0)
            return str(value)

        return _KEY_PATTERN.sub(replace, text)

    # ------------------------------------------------------------ 命令

    def handle(self, line: str, choices: list):
        """`lang [<locale>]`：查看或切换语言。"""
        parts = line.strip().split()
        cmd = parts[0].lower() if parts else ""
        arg = parts[1] if len(parts) > 1 else None
        if cmd != "lang" and cmd != "语言":
            return None
        if not arg:
            available = ", ".join(self.tables) or "（未配置）"
            self.ctx.io.print(f"  当前语言: {self.locale()}（可用: {available}）")
            return {"type": "rerender"}
        if arg not in self.tables:
            available = ", ".join(self.tables) or "（未配置）"
            self.ctx.io.print(f'  没有语言包 "{arg}"（可用: {available}）')
            return {"type": "rerender"}
        self.ctx.state.set("locale", arg)
        self.ctx.io.print(f"  已切换到 {arg}")
        return {"type": "rerender"}

    def missing(self) -> list[str]:
        """未命中清单（供 lint / 测试断言填表完整性）。"""
        return sorted(self.misses)
