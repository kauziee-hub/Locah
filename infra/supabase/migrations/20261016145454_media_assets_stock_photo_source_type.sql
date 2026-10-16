-- Website pictures found by image_retrieval are saved as media_assets with
-- source_type = 'stock_photo' (bucket external). The v4 provenance check
-- listed only uploaded/generated sources, so those inserts failed.
-- Forward-only: replace the check; do not edit the original constraint.

ALTER TABLE media_assets DROP CONSTRAINT IF EXISTS media_assets_source_type_check;

ALTER TABLE media_assets ADD CONSTRAINT media_assets_source_type_check CHECK (source_type IN (
    'owner_uploaded',
    'catalogue_extracted',
    'existing_business_asset',
    'gemini_generated',
    'graphic_generated',
    'stock_photo'
));
