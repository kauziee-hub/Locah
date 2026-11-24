-- A picture LOCAH drew is labelled with the provider that drew it: a
-- Cloudflare Workers AI drawing (IMAGE_FALLBACK=cloudflare) was recorded as
-- gemini_generated. Forward-only: replace the check; keep every earlier value.

ALTER TABLE media_assets DROP CONSTRAINT IF EXISTS media_assets_source_type_check;

ALTER TABLE media_assets ADD CONSTRAINT media_assets_source_type_check CHECK (source_type IN (
    'owner_uploaded',
    'catalogue_extracted',
    'existing_business_asset',
    'gemini_generated',
    'cloudflare_generated',
    'graphic_generated',
    'stock_photo'
));
