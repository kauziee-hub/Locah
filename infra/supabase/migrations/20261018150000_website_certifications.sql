-- Website quality certification.
--
-- A built draft is rendered, judged against the reference standard and gated
-- (pass / repair / fail_closed). The verdict is recorded HERE, bound to a
-- fingerprint of the exact draft it judged: an edit after certification makes
-- the certificate stale. With WEBSITE_CERTIFICATION=enforce, publish refuses a
-- draft without a current passing certificate and hands the owner the gate's
-- requests ("We need 2–3 photographs of your actual clinic…") instead of
-- silently publishing a weak site. Rows are append-only history.

CREATE TABLE website_certifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id),
    website_id UUID NOT NULL REFERENCES websites(id),
    version_id UUID NOT NULL REFERENCES website_versions(id),
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pass', 'repair', 'fail_closed')),
    score NUMERIC(5, 2),
    blocked_on TEXT CHECK (blocked_on IN ('owner', 'platform')),
    owner_requests JSONB NOT NULL DEFAULT '[]'::jsonb,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX website_certifications_business_idx ON website_certifications (business_id, created_at DESC);

ALTER TABLE website_certifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE website_certifications FORCE ROW LEVEL SECURITY;
CREATE POLICY website_certifications_member_read ON website_certifications
    FOR SELECT TO public USING (business_id = current_business_id());
CREATE POLICY website_certifications_api ON website_certifications
    FOR ALL TO platform_api USING (business_id = current_business_id())
    WITH CHECK (business_id = current_business_id());
GRANT SELECT, INSERT ON website_certifications TO platform_api;
REVOKE UPDATE, DELETE ON website_certifications FROM platform_api;
REVOKE ALL PRIVILEGES ON TABLE website_certifications FROM anon;
