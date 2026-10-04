-- "Not now" on a recommended tool (Modules → Recommended for your Business).
--
-- One row per Business and module the owner put off. `evidence_keys` are the
-- reasons LOCAH had at that moment ("said:orders", "records:sellable"); the tool
-- comes back only when a reason appears that is not in this list — something
-- the owner said, recorded or switched on since. `restored_at` is set when the
-- owner brings it back themselves; putting it off again clears it.

CREATE TABLE business_module_dismissals (
    business_id UUID NOT NULL REFERENCES businesses(id),
    module_id TEXT NOT NULL,
    evidence_keys TEXT[] NOT NULL DEFAULT '{}',
    dismissed_by UUID NOT NULL REFERENCES platform_identities(id),
    dismissed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    restored_at TIMESTAMPTZ,
    PRIMARY KEY (business_id, module_id)
);

ALTER TABLE business_module_dismissals ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_module_dismissals FORCE ROW LEVEL SECURITY;
CREATE POLICY business_module_dismissals_member_read ON business_module_dismissals
    FOR SELECT TO public USING (business_id = current_business_id());
CREATE POLICY business_module_dismissals_api ON business_module_dismissals
    FOR ALL TO platform_api USING (business_id = current_business_id())
    WITH CHECK (business_id = current_business_id());
GRANT SELECT, INSERT, UPDATE ON business_module_dismissals TO platform_api;
REVOKE DELETE ON business_module_dismissals FROM platform_api;
REVOKE ALL PRIVILEGES ON TABLE business_module_dismissals FROM anon;
