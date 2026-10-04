"""Internal privileged helpers cannot bypass the API via Supabase RPC."""
from __future__ import annotations

import os

import pytest

from platform_testing.phase_b import sql

pytestmark = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="local test database required")

INTERNAL = [
    "academics_guardian_portal(uuid)", "academics_scope_allows_assessment(uuid)",
    "academics_scope_allows_batch(uuid)", "assignment_scope_allows_member(uuid)",
    "assignment_scope_allows_quote(uuid,uuid)", "document_access_business(text)",
    "document_request_business(text)", "procurement_post_trade(uuid,uuid,uuid,text,jsonb,text)",
]


@pytest.mark.parametrize("function", INTERNAL)
def test_internal_helpers_are_api_only(function: str) -> None:
    row = sql("SELECT has_function_privilege('anon', :fn, 'EXECUTE'), "
              "has_function_privilege('authenticated', :fn, 'EXECUTE'), "
              "has_function_privilege('platform_api', :fn, 'EXECUTE')", fn=f"public.{function}")[0]
    assert tuple(row) == (False, False, True)


def test_release_helpers_have_fixed_search_paths() -> None:
    functions = ["current_business_id", "current_identity_id", "location_scope_allows",
                 "ledger_entries_append_only", "reviews_never_deleted", "reviews_moderation_log_append_only",
                 "reviews_reviews_guard", "reviews_photos_guard", "assignment_scope_allows_identity",
                 "memberships_period_is_history", "queue_history_append_only", "tasks_history_append_only",
                 "quotes_guard_accepted_prices", "quotes_guard_accepted_children", "document_request_token_hash"]
    rows = sql("SELECT proname, proconfig FROM pg_proc JOIN pg_namespace n ON n.oid=pronamespace "
               "WHERE n.nspname='public' AND proname=ANY(:names)", names=functions)
    assert len(rows) == len(functions)
    assert all("search_path=pg_catalog, public, extensions, pg_temp" in row[1] for row in rows)


def test_btree_gist_lives_in_extensions_not_public() -> None:
    assert sql("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace "
               "WHERE e.extname='btree_gist'")[0][0] == "extensions"
