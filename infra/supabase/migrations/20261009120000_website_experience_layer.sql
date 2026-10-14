-- The experience layer for tenant websites (creative-composer-v4).
--
-- A site's composition and motion are chosen per business
-- (platform_core/interview/experience.py) from layouts the renderer draws
-- (apps/web/src/components/website/experience). New layouts for existing
-- section types, one new section type, and three item fields:
--
--   hero              + cinematic_zoom, orbit, plane, kinetic, depth, aurora
--   about             + word_reveal, sticky_split, collage
--   category_showcase + rail, bento
--   product_showcase  + menu_book, rail, bento, spotlight, stack;
--                     items + diet, spice, tag (as the owner said them)
--   cta_band          + giant
--   highlights        + counters
--   marquee           (new) a moving line of the business's own short words
--
-- Nothing here is a live record or needs a module. Forward-only; idempotent.

UPDATE website_section_types
SET allowed_variants = ARRAY['centered', 'left_aligned', 'image_left', 'image_right', 'full_width', 'commerce_split',
                             'editorial_overlay', 'cinematic', 'airy_split', 'editorial_split', 'cinematic_zoom',
                             'orbit', 'plane', 'kinetic', 'depth', 'aurora']
WHERE id = 'hero';

UPDATE website_section_types
SET allowed_variants = ARRAY['text_only', 'image_left', 'image_right', 'story_split', 'word_reveal', 'sticky_split',
                             'collage']
WHERE id = 'about';

UPDATE website_section_types
SET allowed_variants = ARRAY['centered', 'left_aligned', 'image_banner', 'giant']
WHERE id = 'cta_band';

UPDATE website_section_types
SET allowed_variants = ARRAY['strip', 'cards', 'counters']
WHERE id = 'highlights';

UPDATE website_section_types
SET allowed_variants = ARRAY['image_cards', 'tiles', 'chips', 'rail', 'bento']
WHERE id = 'category_showcase';

UPDATE website_section_types
SET content_schema = '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300},"anchor":{"type":"string","maxLength":30},"order_label":{"type":"string","maxLength":40},"filters":{"type":"array","maxItems":12,"items":{"type":"string","maxLength":40}},"categories":{"type":"array","maxItems":12,"items":{"type":"object","required":["name"],"properties":{"name":{"type":"string","maxLength":80},"description":{"type":"string","maxLength":200},"meta":{"type":"string","maxLength":60},"tags":{"type":"array","maxItems":8,"items":{"type":"string","maxLength":40}},"image_asset_id":{"type":"string","format":"uuid"}}}},"items":{"type":"array","maxItems":48,"items":{"type":"object","required":["name"],"properties":{"name":{"type":"string","maxLength":80},"category":{"type":"string","maxLength":80},"description":{"type":"string","maxLength":200},"price":{"type":"string","maxLength":40},"unit":{"type":"string","maxLength":40},"diet":{"type":"string","maxLength":12},"spice":{"type":"string","maxLength":12},"tag":{"type":"string","maxLength":24},"image_asset_id":{"type":"string","format":"uuid"}}}}}}',
    allowed_variants = ARRAY['category_boards', 'commerce_grid', 'menu_grid', 'compact_list', 'project_cards',
                             'plan_cards', 'service_cards', 'menu_book', 'rail', 'bento', 'spotlight', 'stack']
WHERE id = 'product_showcase';

INSERT INTO website_section_types (id, label, description, content_schema, allowed_variants, contributing_module, sort_order) VALUES
('marquee', 'Moving band', 'A moving line of the business''s own short words: its categories and true facts',
 '{"type":"object","properties":{"label":{"type":"string","maxLength":80},"items":{"type":"array","maxItems":12,"items":{"type":"string","maxLength":40}}}}',
 ARRAY['band', 'outline'],
 NULL, 14)
ON CONFLICT (id) DO UPDATE
SET label = EXCLUDED.label,
    description = EXCLUDED.description,
    content_schema = EXCLUDED.content_schema,
    allowed_variants = EXCLUDED.allowed_variants,
    sort_order = EXCLUDED.sort_order;
