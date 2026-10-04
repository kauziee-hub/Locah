-- The first website draft used to open with instructions to the owner
-- ("Your website starts here — Complete your business interview…"). Publishing
-- that draft showed those instructions to customers. The starter now opens with
-- the business's own name; existing starter heroes (draft or published) are
-- changed the same way. Heroes the owner or the generator wrote are untouched.

UPDATE website_sections s
SET content = jsonb_build_object('headline', b.display_name)
FROM businesses b
WHERE s.business_id = b.id
  AND s.section_type_id = 'hero'
  AND s.content->>'headline' = 'Your website starts here'
  AND s.content->>'subheadline' = 'Complete your business interview to create a draft, or edit this page yourself.';
