"""Extract the leading definition without following documentation links or using sample values."""

import html
import re


def leading_definition(description: str) -> str:
    text = html.unescape(description)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    return " ".join(re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].split()[:80])
