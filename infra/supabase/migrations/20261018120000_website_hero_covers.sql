-- Hero covers (creative-composer-v5, experience layer).
--
-- Six more first screens, each a different piece of art direction with its
-- own movement, so businesses of one trade stop opening on the same scene
-- (apps/web/src/components/website/experience/Covers.tsx):
--
--   arch       words beside a tall arched photograph
--   window     the headline across the page, the photograph seen between its lines
--   gallery    an editorial collage of three photographs
--   ledger     a ruled sheet: headline, photograph, hours / address / phone
--   signature  the food's photograph beside priced dishes from the owner's range
--   stage      the headline centred, the photograph framed on a mat beneath it
--
-- Layout only: the hero's content schema is unchanged, and none reads a live
-- record or needs a module. Forward-only; idempotent.

UPDATE website_section_types
SET allowed_variants = ARRAY['centered', 'left_aligned', 'image_left', 'image_right', 'full_width', 'commerce_split',
                             'editorial_overlay', 'cinematic', 'airy_split', 'editorial_split', 'cinematic_zoom',
                             'orbit', 'plane', 'kinetic', 'depth', 'aurora', 'page',
                             'arch', 'window', 'gallery', 'ledger', 'signature', 'stage']
WHERE id = 'hero';
