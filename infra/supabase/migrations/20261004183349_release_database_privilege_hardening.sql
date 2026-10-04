-- These helpers are API/RLS implementation details, not PostgREST endpoints.
-- Supabase's explicit default role grants survive REVOKE ... FROM PUBLIC.
REVOKE EXECUTE ON FUNCTION
    public.academics_guardian_portal(uuid),
    public.academics_scope_allows_assessment(uuid),
    public.academics_scope_allows_batch(uuid),
    public.assignment_scope_allows_member(uuid),
    public.assignment_scope_allows_quote(uuid, uuid),
    public.document_access_business(text),
    public.document_request_business(text),
    public.procurement_post_trade(uuid, uuid, uuid, text, jsonb, text)
FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION
    public.academics_guardian_portal(uuid),
    public.academics_scope_allows_assessment(uuid),
    public.academics_scope_allows_batch(uuid),
    public.assignment_scope_allows_member(uuid),
    public.assignment_scope_allows_quote(uuid, uuid),
    public.document_access_business(text),
    public.document_request_business(text),
    public.procurement_post_trade(uuid, uuid, uuid, text, jsonb, text)
TO platform_api;

-- Preserve bodies and authorization semantics; resolve builtins first and put
-- the temporary schema last so caller-created objects cannot shadow them.
ALTER FUNCTION public.current_business_id() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.current_identity_id() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.location_scope_allows(uuid) SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.ledger_entries_append_only() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.reviews_never_deleted() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.reviews_moderation_log_append_only() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.reviews_reviews_guard() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.reviews_photos_guard() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.assignment_scope_allows_identity(uuid) SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.memberships_period_is_history() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.queue_history_append_only() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.tasks_history_append_only() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.quotes_guard_accepted_prices() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.quotes_guard_accepted_children() SET search_path = pg_catalog, public, extensions, pg_temp;
ALTER FUNCTION public.document_request_token_hash() SET search_path = pg_catalog, public, extensions, pg_temp;

-- Relocatable extension; existing exclusion constraints keep their object IDs.
ALTER EXTENSION btree_gist SET SCHEMA extensions;
