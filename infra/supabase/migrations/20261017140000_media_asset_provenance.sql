-- Where a found photograph came from, and how to find another.
--
-- A stock photograph (source_type 'stock_photo') is credited on the site and
-- can be swapped for an alternative without rebuilding the site. Both need
-- more than the asset row held: the source and photo id, the attribution the
-- source asks for (photographer and source, with their links), why it was
-- chosen (internal, for audit — never shown), and the photo brief that found
-- it. One nullable JSONB column; every other asset keeps NULL.
--
-- Shape (written by MediaService.persist_found from FoundImage.provenance()):
--   { kind, provider, photo_id, page_url, attribution: {line, name, name_url, source,
--     source_url, page_url}, query, score, rubric, selection_reason, brief, stored_copy }
--
-- Forward-only; idempotent.

ALTER TABLE media_assets ADD COLUMN IF NOT EXISTS provenance JSONB;

COMMENT ON COLUMN media_assets.provenance IS
    'Stock photographs only: source, attribution, selection audit and the photo brief (website.image_retrieval).';
