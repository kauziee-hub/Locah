"""Print `export NAME=value` lines for the AI and photo provider keys in .env — and nothing else.

The certification stack runs the real providers (the owner journeys are meant
to be real) against a LOCAL database and LOCAL storage. Loading the whole .env
would also load the hosted database URL and storage keys, so only this
allowlist is exported. Values are shell-quoted and never echoed by the stack
scripts (they `eval` this output).
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

ALLOW = (
    "AI_PROVIDER", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL", "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL", "OPENROUTER_BASE_URL", "GEMINI_API_KEY", "GEMINI_MODEL", "XAI_API_KEY", "XAI_MODEL",
    "IMAGE_SEARCH_PROVIDER", "UNSPLASH_ACCESS_KEY", "PIXABAY_API_KEY",
)


def main(path: str) -> None:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in ALLOW:
            continue
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if value:
            print(f"export {name}={shlex.quote(value)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".env")
