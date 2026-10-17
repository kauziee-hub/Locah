-- Premium, multi-page websites (creative-composer-v5).
--
-- A site is now a home page and inner pages (menu / shop / services, about,
-- visit), each with many sections, in a design language of its own (theme.dna).
-- Four new section types and three new layouts:
--
--   statement         one sentence as the page's centrepiece (giant | split | image)
--   pillars           what the business stands on (cards | numbered | strip)
--   faq               questions answered only from the owner's facts (accordion | split)
--   media_text        passages beside their pictures (alternating | sticky)
--   hero              + page (an inner page's opening)
--   product_showcase  + hover_list, chapters; content + eyebrow, more_label / more_path (a home
--                     teaser linking to the full range on its own page)
--   gallery           + rail
--
-- None reads a live record or needs a module. Forward-only; idempotent.

UPDATE website_section_types
SET allowed_variants = ARRAY['centered', 'left_aligned', 'image_left', 'image_right', 'full_width', 'commerce_split',
                             'editorial_overlay', 'cinematic', 'airy_split', 'editorial_split', 'cinematic_zoom',
                             'orbit', 'plane', 'kinetic', 'depth', 'aurora', 'page']
WHERE id = 'hero';

UPDATE website_section_types
SET content_schema = '{"type":"object","properties":{"eyebrow":{"type":"string","maxLength":40},"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300},"anchor":{"type":"string","maxLength":30},"order_label":{"type":"string","maxLength":40},"more_label":{"type":"string","maxLength":40},"more_path":{"type":"string","maxLength":80},"filters":{"type":"array","maxItems":12,"items":{"type":"string","maxLength":40}},"categories":{"type":"array","maxItems":12,"items":{"type":"object","required":["name"],"properties":{"name":{"type":"string","maxLength":80},"description":{"type":"string","maxLength":200},"meta":{"type":"string","maxLength":60},"tags":{"type":"array","maxItems":8,"items":{"type":"string","maxLength":40}},"image_asset_id":{"type":"string","format":"uuid"}}}},"items":{"type":"array","maxItems":48,"items":{"type":"object","required":["name"],"properties":{"name":{"type":"string","maxLength":80},"category":{"type":"string","maxLength":80},"description":{"type":"string","maxLength":200},"price":{"type":"string","maxLength":40},"unit":{"type":"string","maxLength":40},"diet":{"type":"string","maxLength":12},"spice":{"type":"string","maxLength":12},"tag":{"type":"string","maxLength":24},"image_asset_id":{"type":"string","format":"uuid"}}}}}}',
    allowed_variants = ARRAY['category_boards', 'commerce_grid', 'menu_grid', 'compact_list', 'project_cards',
                             'plan_cards', 'service_cards', 'menu_book', 'rail', 'bento', 'spotlight', 'stack',
                             'hover_list', 'chapters']
WHERE id = 'product_showcase';

UPDATE website_section_types
SET allowed_variants = ARRAY['grid', 'masonry', 'carousel', 'rail']
WHERE id = 'gallery';

INSERT INTO website_section_types (id, label, description, content_schema, allowed_variants, contributing_module, sort_order) VALUES
('statement', 'Statement', 'One sentence as the page''s centrepiece, in the owner''s words',
 '{"type":"object","required":["text"],"properties":{"eyebrow":{"type":"string","maxLength":40},"text":{"type":"string","maxLength":280},"highlight":{"type":"string","maxLength":60},"image_asset_id":{"type":"string","format":"uuid"}}}',
 ARRAY['giant', 'split', 'image'], NULL, 16),
('pillars', 'Pillars', 'What the business stands on, each from the owner''s own words or facts',
 '{"type":"object","properties":{"image_asset_id":{"type":"string","format":"uuid"},"eyebrow":{"type":"string","maxLength":40},"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300},"items":{"type":"array","maxItems":6,"items":{"type":"object","required":["title"],"properties":{"title":{"type":"string","maxLength":60},"body":{"type":"string","maxLength":200},"icon":{"type":"string","maxLength":20}}}}}}',
 ARRAY['cards', 'numbered', 'strip'], NULL, 17),
('faq', 'Questions', 'Questions a visitor asks, answered only from what the owner told LOCAH',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300},"items":{"type":"array","maxItems":10,"items":{"type":"object","required":["q","a"],"properties":{"q":{"type":"string","maxLength":140},"a":{"type":"string","maxLength":500}}}}}}',
 ARRAY['accordion', 'split'], NULL, 118),
('media_text', 'Picture and words', 'Passages about the business, each beside its own picture',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"more_label":{"type":"string","maxLength":40},"more_path":{"type":"string","maxLength":80},"items":{"type":"array","maxItems":4,"items":{"type":"object","required":["title"],"properties":{"eyebrow":{"type":"string","maxLength":40},"title":{"type":"string","maxLength":80},"body":{"type":"string","maxLength":360},"image_asset_id":{"type":"string","format":"uuid"}}}}}}',
 ARRAY['alternating', 'sticky'], NULL, 24)
ON CONFLICT (id) DO UPDATE
SET label = EXCLUDED.label,
    description = EXCLUDED.description,
    content_schema = EXCLUDED.content_schema,
    allowed_variants = EXCLUDED.allowed_variants,
    sort_order = EXCLUDED.sort_order;
