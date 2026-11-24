"""mypy ratchet: the error count may only go down.

The repository carries type errors from before strict checking; failing CI on
all of them meant CI's mypy step always failed and pytest never ran. This runs
the same check and compares its error count with the recorded baseline
(tools/ci/mypy-baseline.txt):

- more errors than the baseline: fail, and say how many were added;
- fewer: pass, and ask for the baseline to come down (``--update`` writes it);
- equal: pass.

    uv run python tools/ci/mypy_ratchet.py            # CI
    uv run python tools/ci/mypy_ratchet.py --update   # after fixing errors
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name("mypy-baseline.txt")
COMMAND = [sys.executable, "-m", "mypy", "--explicit-package-bases", "."]


def count(output: str) -> int:
    if re.search(r"^Success: no issues found", output, re.M):
        return 0
    found = re.search(r"^Found (\d+) errors? in \d+ files?", output, re.M)
    if not found:
        raise SystemExit(f"mypy did not report a count — its output ends:\n{output[-2000:]}")
    return int(found.group(1))


def main(argv: list[str]) -> int:
    result = subprocess.run(COMMAND, cwd=ROOT, capture_output=True, text=True)
    output = result.stdout + result.stderr
    now = count(output)
    baseline = int(BASELINE.read_text().strip())
    if "--update" in argv:
        if now > baseline:
            print(f"Refusing to raise the baseline: {now} errors > {baseline}.")
            return 1
        BASELINE.write_text(f"{now}\n")
        print(f"mypy baseline: {baseline} -> {now}")
        return 0
    if now > baseline:
        print(output[-6000:])
        print(f"\nmypy: {now} errors, {now - baseline} more than the baseline of {baseline}. "
              "Fix the new ones — the count may only go down.")
        return 1
    if now < baseline:
        print(f"mypy: {now} errors, {baseline - now} fewer than the baseline of {baseline}. "
              "Lower it: uv run python tools/ci/mypy_ratchet.py --update")
    else:
        print(f"mypy: {now} errors (baseline {baseline}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
