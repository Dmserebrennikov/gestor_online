"""Convert CommonMark-ish LLM output to Telegram HTML.

Telegram does not treat ``**bold**`` as formatting unless ``parse_mode`` is set,
and MarkdownV2 needs almost every punctuation character escaped. HTML is the
safer outbound mode: convert the usual Markdown markers, escape the rest.
"""

from __future__ import annotations

import html
import re

_FENCE_RE = re.compile(r"```(?:\w+)?\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)

_PLACEHOLDER = "\x00{i}\x00"


def markdown_to_telegram_html(text: str) -> str:
    """Turn ``**bold**``, italics, code, links, and headings into Telegram HTML."""
    placeholders: list[str] = []

    def stash(fragment: str) -> str:
        placeholders.append(fragment)
        return _PLACEHOLDER.format(i=len(placeholders) - 1)

    def keep_fence(match: re.Match[str]) -> str:
        code = html.escape(match.group(1).rstrip("\n"))
        return stash(f"<pre>{code}</pre>")

    def keep_inline_code(match: re.Match[str]) -> str:
        return stash(f"<code>{html.escape(match.group(1))}</code>")

    converted = _FENCE_RE.sub(keep_fence, text)
    converted = _INLINE_CODE_RE.sub(keep_inline_code, converted)
    converted = html.escape(converted)
    converted = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', converted)
    converted = _BOLD_RE.sub(r"<b>\1</b>", converted)
    converted = _STRIKE_RE.sub(r"<s>\1</s>", converted)
    converted = _ITALIC_RE.sub(r"<i>\1</i>", converted)
    converted = _HEADING_RE.sub(r"<b>\1</b>", converted)

    for index, fragment in enumerate(placeholders):
        converted = converted.replace(_PLACEHOLDER.format(i=index), fragment)
    return converted
