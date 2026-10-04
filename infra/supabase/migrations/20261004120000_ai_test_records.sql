-- AI Employee Studio — Test Mode records.
--
-- When the owner approves what an AI employee proposed in Test Mode, the
-- order, booking or enquiry is written HERE, never to orders_orders,
-- bookings_bookings, leads_leads or payment_attempts. It is checked against
-- the live price, stock words and free times first, so it is a real result,
-- but it is isolated by construction: no module reads this table, no domain
-- event is emitted, no message is sent and no money moves. A test payment
-- goes through the test adapter only and is stored in `payment`.
--
-- `cleared_at` is set when the owner clears their test records; cleared rows
-- are kept for the audit trail and never shown again.

CREATE TABLE ai_test_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id),
    kind TEXT NOT NULL CHECK (kind IN ('order', 'booking', 'lead')),
    reference TEXT NOT NULL,
    scenario TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    amount NUMERIC(12, 2),
    status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'paid', 'payment_failed', 'cancelled')),
    payment JSONB,
    created_by UUID NOT NULL REFERENCES platform_identities(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at TIMESTAMPTZ,
    UNIQUE (business_id, reference)
);
CREATE INDEX ai_test_records_business_idx ON ai_test_records (business_id, created_at DESC) WHERE cleared_at IS NULL;

ALTER TABLE ai_test_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_test_records FORCE ROW LEVEL SECURITY;
CREATE POLICY ai_test_records_member_read ON ai_test_records
    FOR SELECT TO public USING (business_id = current_business_id());
CREATE POLICY ai_test_records_api ON ai_test_records
    FOR ALL TO platform_api USING (business_id = current_business_id())
    WITH CHECK (business_id = current_business_id());
GRANT SELECT, INSERT, UPDATE ON ai_test_records TO platform_api;
REVOKE DELETE ON ai_test_records FROM platform_api;
REVOKE ALL PRIVILEGES ON TABLE ai_test_records FROM anon;
