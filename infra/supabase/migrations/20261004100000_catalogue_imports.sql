-- Catalogue import batches (Offerings → Import).
--
-- One row per committed import of a CSV / XLSX sheet (or an AI-read document)
-- into the catalogue. Imported items are always created as drafts; the owner
-- reviews them and makes them live from the batch. The batch keeps which
-- offerings it created or updated, so the review screen and the audit trail
-- can find them, and the file hash lets Locah say "this exact file was already
-- imported" before anything is duplicated.

CREATE TABLE offerings_catalog_imports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id),
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('csv', 'xlsx', 'document')),
    row_count INTEGER NOT NULL DEFAULT 0,
    created_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    offering_ids UUID[] NOT NULL DEFAULT '{}',
    created_by UUID NOT NULL REFERENCES platform_identities(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_offerings_catalog_imports_recent ON offerings_catalog_imports (business_id, created_at DESC);
CREATE INDEX idx_offerings_catalog_imports_hash ON offerings_catalog_imports (business_id, file_hash);

ALTER TABLE offerings_catalog_imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE offerings_catalog_imports FORCE ROW LEVEL SECURITY;
CREATE POLICY offerings_catalog_imports_member_read ON offerings_catalog_imports
    FOR SELECT TO public USING (business_id = current_business_id());
CREATE POLICY offerings_catalog_imports_api ON offerings_catalog_imports
    FOR ALL TO platform_api USING (business_id = current_business_id())
    WITH CHECK (business_id = current_business_id());
GRANT SELECT, INSERT, UPDATE ON offerings_catalog_imports TO platform_api;
REVOKE DELETE ON offerings_catalog_imports FROM platform_api;
REVOKE ALL PRIVILEGES ON TABLE offerings_catalog_imports FROM anon;
