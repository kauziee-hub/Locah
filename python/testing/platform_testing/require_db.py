"""A test that needs the database runs — or the run fails. It never skips quietly.

Most integration tests skip themselves when no database is configured, which is
right on a laptop without Postgres. In CI (GitHub sets ``CI=true``) or with
``LOCAH_REQUIRE_DB=1`` that skip would hide a whole suite: the worker suite was
skipped for weeks in local "full" runs with nobody noticing (2026-11-24). Here:

- the run refuses to start when no database URL is set at all;
- any test skipped for want of a database is reported as a failure.

Registered for the API and worker suites by ``-p platform_testing.require_db``
in ``apps/api/pyproject.toml``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Generator, Mapping
from typing import Any

import pytest

_DATABASE_REASON = re.compile(r"DATABASE_URL|database|postgres", re.IGNORECASE)


def database_required(environ: Mapping[str, str] = os.environ) -> bool:
    return environ.get("CI", "").strip().lower() == "true" or environ.get("LOCAH_REQUIRE_DB", "").strip() == "1"


def database_configured(environ: Mapping[str, str] = os.environ) -> bool:
    return bool(environ.get("DATABASE_URL", "").strip() or environ.get("TEST_DATABASE_URL", "").strip())


def pytest_sessionstart(session: pytest.Session) -> None:
    if database_required() and not database_configured():
        pytest.exit("A database is required for this run (CI or LOCAH_REQUIRE_DB=1) and none is configured: "
                    "set TEST_DATABASE_URL to a local Postgres.", returncode=3)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Generator[None, Any, None]:
    outcome = yield
    report = outcome.get_result()
    if report.skipped and database_required() and _DATABASE_REASON.search(str(report.longrepr or "")):
        report.outcome = "failed"
        report.longrepr = (f"Skipped for want of a database, but this run requires one "
                           f"(CI or LOCAH_REQUIRE_DB=1): {report.longrepr}")
