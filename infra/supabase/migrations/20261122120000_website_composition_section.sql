-- The composition section: a section arranged freely, drawn only by the platform.
--
-- Every other section type is one design with a few layouts. A composition is
-- an arrangement of blocks (words, pictures, a number, a quote, a numbered list,
-- an action, a vertical label) on a 12-column grid, with overlapping layers,
-- framed and masked pictures, a ground, a height, motion and an arrangement of
-- its own for a phone. The layout engine and the reference reader choose
-- arrangements; platform code draws them (website.composition_grammar, which
-- also normalizes every stored composition). It reads no live record and
-- needs no module. The content schema mirrors composition_grammar.SCHEMA
-- exactly (a test compares them). Forward-only; idempotent.

INSERT INTO website_section_types (id, label, description, content_schema, allowed_variants, contributing_module, sort_order) VALUES
('composition', 'Composed section', 'Words, pictures and numbers arranged freely on a grid, composed for this business',
 '{"type":"object","required":["items"],"properties":{"role":{"type":"string","maxLength":12},"recipe":{"type":"string","maxLength":40},"title":{"type":"string","maxLength":120},"anchor":{"type":"string","maxLength":30},"ground":{"type":"string","maxLength":8},"height":{"type":"string","maxLength":8},"rows":{"type":"integer"},"items":{"type":"array","maxItems":12,"items":{"type":"object","required":["kind"],"properties":{"kind":{"type":"string","maxLength":12},"slot":{"type":"string","maxLength":40},"col":{"type":"integer"},"span":{"type":"integer"},"row":{"type":"integer"},"rows":{"type":"integer"},"layer":{"type":"integer"},"m_col":{"type":"integer"},"m_span":{"type":"integer"},"m_order":{"type":"integer"},"m_ratio":{"type":"string","maxLength":6},"lift":{"type":"boolean"},"plate":{"type":"boolean"},"vertical":{"type":"boolean"},"size":{"type":"string","maxLength":4},"tone":{"type":"string","maxLength":10},"frame":{"type":"string","maxLength":10},"align":{"type":"string","maxLength":8},"valign":{"type":"string","maxLength":8},"motion":{"type":"string","maxLength":10},"eyebrow":{"type":"string","maxLength":60},"title":{"type":"string","maxLength":160},"body":{"type":"string","maxLength":600},"value":{"type":"string","maxLength":24},"label":{"type":"string","maxLength":80},"caption":{"type":"string","maxLength":120},"cta_label":{"type":"string","maxLength":40},"cta_url":{"type":"string","maxLength":200},"price":{"type":"string","maxLength":40},"image_asset_id":{"type":"string","format":"uuid"},"points":{"type":"array","maxItems":6,"items":{"type":"object","required":["title"],"properties":{"title":{"type":"string","maxLength":80},"body":{"type":"string","maxLength":240},"meta":{"type":"string","maxLength":40}}}}}}}}}',
 ARRAY['free'], NULL, 26)
ON CONFLICT (id) DO UPDATE
SET label = EXCLUDED.label,
    description = EXCLUDED.description,
    content_schema = EXCLUDED.content_schema,
    allowed_variants = EXCLUDED.allowed_variants,
    sort_order = EXCLUDED.sort_order;
