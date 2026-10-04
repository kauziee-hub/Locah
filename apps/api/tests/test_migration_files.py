"""Migration files stay deployable.

Supabase records each migration by the timestamp at the front of its file name;
two files with the same timestamp fail the deploy on a duplicate key. Names
must also sort in the order they are meant to run.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "supabase" / "migrations"
NAME = re.compile(r"^(\d{14})_[a-z0-9_]+\.sql$")


def test_every_migration_has_its_own_timestamped_version() -> None:
    files = sorted(p.name for p in MIGRATIONS.glob("*.sql"))
    assert files, f"no migrations found in {MIGRATIONS}"
    bad = [f for f in files if not NAME.match(f)]
    assert not bad, f"migration names must be <14-digit timestamp>_<snake_case>.sql: {bad}"
    versions = Counter(f[:14] for f in files)
    duplicates = sorted(v for v, n in versions.items() if n > 1)
    assert not duplicates, f"two migrations share a version (Supabase would refuse the deploy): {duplicates}"
