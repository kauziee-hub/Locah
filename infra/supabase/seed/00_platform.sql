-- Platform module registry (Doc 08 §6.1 + optional modules)
INSERT INTO module_definitions (id, name, module_class, description, dependencies) VALUES
-- Platform Core (auto-included for every Business)
('core-business-identity', 'Business Identity', 'platform_core', 'Business root entity and lifecycle', '{}'),
('core-business-profile', 'Business Profile', 'platform_core', 'Public-facing business profile', '{core-business-identity}'),
('core-website', 'Website', 'platform_core', 'Structured website model', '{core-business-profile}'),
('core-workspace', 'Workspace Foundation', 'platform_core', 'Operator shell foundation', '{core-business-identity}'),
('core-settings', 'Settings', 'platform_core', 'Business-wide configuration', '{core-business-identity}'),
('core-locations', 'Location Foundation', 'platform_core', 'Location management', '{core-business-identity}'),
('core-team-access', 'Team & Access', 'platform_core', 'Memberships, roles, permissions', '{core-business-identity}'),
('core-module-management', 'Module Management', 'platform_core', 'Module registry and lifecycle', '{core-business-identity}'),
('core-notifications', 'Basic Notifications', 'platform_core', 'In-platform notifications', '{core-business-identity}'),
('core-marketplace-presence', 'Marketplace Presence', 'platform_core', 'Marketplace indexing projection', '{core-business-profile}'),
-- Optional Business Modules (First Launch)
('offerings-catalog', 'Offerings Catalog', 'optional', 'Product/service catalog', '{core-business-profile}'),
('orders', 'Orders', 'optional', 'Order management', '{offerings-catalog}'),
('bookings', 'Bookings', 'optional', 'Reservation management', '{offerings-catalog}'),
('payments', 'Payments', 'optional', 'Payment processing', '{orders}'),
('memberships', 'Memberships', 'optional', 'Membership plans', '{payments}'),
('customer-relationships', 'Customer Relationships', 'optional', 'CRM', '{orders}'),
('leads', 'Leads', 'optional', 'Lead pipeline', '{core-business-profile}'),
('inventory', 'Inventory', 'optional', 'Stock management', '{offerings-catalog}'),
('fulfilment', 'Fulfilment', 'optional', 'Delivery and pickup', '{orders,inventory}'),
('workforce', 'Workforce', 'optional', 'Staff and provider management', '{core-team-access}'),
-- Later / Future optional modules (Doc 11 §18.2 — registered with canonical IDs,
-- no entitlement or activation at First Launch; launch depth is release config).
('queue-operations', 'Queue Operations', 'optional', 'Walk-in queue and token management', '{core-team-access}'),
('invoicing', 'Invoicing', 'optional', 'Invoices and receivables', '{core-business-profile}'),
('loyalty', 'Loyalty', 'optional', 'Points, tiers, and rewards', '{customer-relationships}'),
('payroll', 'Payroll', 'optional', 'Compensation and payout coordination', '{workforce}'),
('messaging', 'Messaging', 'optional', 'External messaging channels', '{core-notifications}'),
('marketing', 'Marketing', 'optional', 'Campaigns and promotional audiences', '{customer-relationships}'),
('reviews', 'Reviews', 'optional', 'Transaction-linked feedback', '{core-business-profile}'),
('analytics', 'Analytics', 'optional', 'Business reporting and insights', '{core-workspace}'),
('business-passport', 'Business Passport', 'optional', 'Verified credential dossier', '{core-business-profile}'),
('business-community', 'Business Community', 'optional', 'Community posts and follows', '{core-marketplace-presence}'),
('b2b-network', 'B2B Network', 'optional', 'Supplier and partner discovery', '{core-business-profile}')
ON CONFLICT (id) DO NOTHING;

-- Website section types — canonical structured sections (Doc 12 §11.1, §18.2)
-- These are the building blocks for structured Website content.
-- content_schema is a simplified JSON Schema for the section's content JSONB field.
-- No arbitrary HTML or executable code may be stored in section content.
INSERT INTO website_section_types (id, label, description, content_schema, allowed_variants, contributing_module, sort_order) VALUES

-- Core sections (available to all businesses)
('hero', 'Hero / Banner', 'Main header section with headline, subheadline, and call-to-action',
 '{"type":"object","required":["headline"],"properties":{"headline":{"type":"string","maxLength":120},"headline_accent":{"type":"string","maxLength":60},"eyebrow":{"type":"string","maxLength":60},"subheadline":{"type":"string","maxLength":300},"cta_label":{"type":"string","maxLength":60},"cta_url":{"type":"string","maxLength":500},"image_asset_id":{"type":"string","format":"uuid"},"badges":{"type":"array","maxItems":4,"items":{"type":"string","maxLength":40}}}}',
 ARRAY['centered', 'left_aligned', 'image_left', 'image_right', 'full_width', 'commerce_split', 'editorial_overlay', 'cinematic', 'airy_split', 'editorial_split', 'cinematic_zoom', 'orbit', 'plane', 'kinetic', 'depth', 'aurora'],
 NULL, 10),

('about', 'About / Story', 'Business description, history, and mission',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"body":{"type":"string","maxLength":2000},"image_asset_id":{"type":"string","format":"uuid"},"eyebrow":{"type":"string","maxLength":40},"quote":{"type":"string","maxLength":200},"anchor":{"type":"string","maxLength":30}}}',
 ARRAY['text_only', 'image_left', 'image_right', 'story_split', 'word_reveal', 'sticky_split', 'collage'],
 NULL, 20),

('contact', 'Contact Information', 'Contact details, address, and enquiry prompt',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"address":{"type":"string","maxLength":500},"phone":{"type":"string","maxLength":50},"email":{"type":"string","maxLength":200},"hours_summary":{"type":"string","maxLength":500},"show_map":{"type":"boolean"}}}',
 ARRAY['full', 'compact'],
 NULL, 30),

('highlights', 'Highlights', 'A few numbers the business itself stated, shown prominently',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"items":{"type":"array","maxItems":6,"items":{"type":"object","required":["value","label"],"properties":{"value":{"type":"string","maxLength":24},"label":{"type":"string","maxLength":40}}}}}}',
 ARRAY['strip', 'cards', 'counters'],
 NULL, 15),

('feature_grid', 'What we do', 'The things the business does, or how a customer works with them',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300},"items":{"type":"array","maxItems":9,"items":{"type":"object","required":["title"],"properties":{"title":{"type":"string","maxLength":80},"body":{"type":"string","maxLength":240}}}}}}',
 ARRAY['cards', 'steps', 'list'],
 NULL, 25),

('text_block', 'Text Block', 'Freeform structured text content block',
 '{"type":"object","required":["body"],"properties":{"title":{"type":"string","maxLength":120},"body":{"type":"string","maxLength":5000}}}',
 ARRAY['default', 'highlighted'],
 NULL, 40),

('location_list', 'Locations', 'List of business locations with contact information',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"show_hours":{"type":"boolean"},"show_map":{"type":"boolean"},"locations":{"type":"array","maxItems":12,"items":{"type":"object","required":["name"],"properties":{"id":{"type":"string","maxLength":80},"name":{"type":"string","maxLength":80},"address":{"type":"string","maxLength":500},"hours_summary":{"type":"string","maxLength":500},"is_primary":{"type":"boolean"}}}}}}',
 ARRAY['cards', 'list'],
 NULL, 50),

('gallery', 'Photo Gallery', 'Collection of images showcasing the business',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"image_asset_ids":{"type":"array","items":{"type":"string","format":"uuid"},"maxItems":20}}}',
 ARRAY['grid', 'masonry', 'carousel'],
 NULL, 60),

-- Module-contributed sections (offerings-catalog)
('offerings_list', 'Offerings / Products / Services', 'Display business offerings with prices',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300},"offering_types":{"type":"array","items":{"type":"string"}},"max_items":{"type":"integer","minimum":1,"maximum":50}}}',
 ARRAY['cards', 'list', 'grid'],
 'offerings-catalog', 70),

('menu_section', 'Menu', 'Food/beverage menu display',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"show_prices":{"type":"boolean"},"category_filter":{"type":"array","items":{"type":"string"}}}}',
 ARRAY['categorized', 'simple'],
 'offerings-catalog', 80),

('rooms_section', 'Rooms / Accommodation', 'Accommodation unit listing',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300}}}',
 ARRAY['cards', 'list'],
 'offerings-catalog', 90),

('plans_section', 'Membership Plans', 'Membership or subscription plan display',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300},"highlight_plan_id":{"type":"string","format":"uuid"}}}',
 ARRAY['cards', 'comparison'],
 'offerings-catalog', 100),

('classes_section', 'Classes / Schedule', 'Scheduled classes or sessions',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"show_upcoming_only":{"type":"boolean"},"max_items":{"type":"integer","minimum":1,"maximum":20}}}',
 ARRAY['schedule', 'cards'],
 'offerings-catalog', 110),

('reviews_section', 'Verified customer reviews', 'Published reviews from completed customer interactions',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300}}}',
 ARRAY['cards', 'list'],
 'reviews', 115),

-- Call-to-action / enquiry sections
('cta_band', 'Call to Action', 'Prominent call-to-action strip',
 '{"type":"object","required":["headline","cta_label"],"properties":{"headline":{"type":"string","maxLength":200},"body":{"type":"string","maxLength":500},"cta_label":{"type":"string","maxLength":60},"cta_url":{"type":"string","maxLength":500},"image_asset_id":{"type":"string","format":"uuid"}}}',
 ARRAY['centered', 'left_aligned', 'image_banner', 'giant'],
 NULL, 120),

('enquiry_form', 'Enquiry / Lead Capture', 'Contact/enquiry form for lead capture',
 '{"type":"object","properties":{"title":{"type":"string","maxLength":120},"subtitle":{"type":"string","maxLength":300},"offering_id":{"type":"string","format":"uuid"}}}',
 ARRAY['default', 'compact'],
 'leads', 130)

ON CONFLICT (id) DO NOTHING;

