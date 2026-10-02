/** Business Interview v1. Server authority: platform_core.interview.models. */
export type InterviewFactKey = 'description' | 'classification' | 'operating_model' | 'locations'
  | 'offerings' | 'customer_actions' | 'operational_characteristics' | 'brand' | 'tone'
  | 'colours' | 'opening_hours' | 'phone' | 'email' | 'website_priorities'
export type InterviewFact = {
  value: string; source: 'USER_STATEMENT' | 'PLATFORM' | 'AI_EXTRACTION'
  confirmation: 'confirmed' | 'unconfirmed'; evidence: string; updated_at: string
}
export type InterviewMedia = {
  asset_id: string; role: 'logo' | 'hero' | 'business' | 'offering' | 'gallery'
  label: string; source: 'USER_UPLOAD' | 'AI_GENERATED' | 'CATALOGUE_EXTRACTED'
}
/** One line read from the owner's menu / catalogue. `low`: shown unticked to check. */
export type ExtractedItem = {
  name: string; description: string; price: string; unit: string; variant: string; attributes: string
  confidence: 'high' | 'low'
}
/** A menu, catalogue, price list or brochure the owner attached, as LOCAH read it. */
export type DocumentRead = {
  asset_id: string
  kind: 'menu' | 'catalogue' | 'price_list' | 'brochure' | 'other'
  status: 'reading' | 'ready' | 'failed' | 'applied' | 'dismissed'
  reason: string
  groups: { name: string; items: ExtractedItem[] }[]
  facts: Record<string, string>
}
/** A picture the website plans to show, and whether it is the owner's or a draft. */
export type PlannedMedia = {
  key: string; purpose: 'hero' | 'category' | 'item' | 'story' | 'cta' | 'background'
  section: string; subject: string
  truth_class: 'factual' | 'representative' | 'mood' | 'graphic'
  source: 'owner_uploaded' | 'catalogue_extracted' | 'existing_business_asset' | 'gemini_generated'
    | 'graphic_generated' | null
  aspect: string; crop: string; style: string; prompt_version: string
  status: 'planned' | 'ready' | 'failed' | 'skipped'; asset_id: string | null
  approval: 'draft' | 'approved' | 'removed'; reason: string
}
export type InterviewModule = {
  module_id: string; label: string; reason: string; capability_ids: string[]; dependencies: string[]
  status: 'SUPPORTED' | 'SUPPORTED_REQUIRES_CONFIGURATION' | 'SUPPORTED_NOT_ENABLED' | 'NOT_CURRENTLY_AVAILABLE'
  availability_reason: string; choice: 'pending' | 'approved' | 'declined'
  /** Who the tool is for: the owner's customers, or running the business. */
  group?: 'customer' | 'operations'
  /** How strongly the conversation points at it; `dependency` = another tool needs it. */
  strength?: 'strong' | 'useful' | 'dependency'
  evidence?: { kind: 'owner_said' | 'operating_model' | 'answer' | 'dependency' | 'profile'; text: string }[]
  /** What still has to be set up before customers can use it. */
  configuration_needed?: string
  /** Owner-facing names of the tools that need this one. */
  needed_by?: string[]
}
export type DiscoveryTargetStatus = 'open' | 'asked' | 'partial' | 'answered' | 'declined' | 'deferred'
/** What Locah knows about one concept (not one question), and how often it asked. */
export type DiscoveryTarget = {
  status: DiscoveryTargetStatus; asked: number; last_asked_turn: number | null
  summary: string; quote: string
}
export type DraftProvenance = 'ai_suggestion' | 'owner_claim' | 'owner_edited' | 'owner_approved'
export type DraftText = { text: string; provenance: DraftProvenance; updated_at: string }
/** Website wording beside the conversation. Presentation, never business truth. */
export type WebsiteDraft = {
  hero_headline: DraftText | null; hero_subheadline: DraftText | null
  about: DraftText | null; cta_label: DraftText | null
  offerings: { name: string; description: DraftText | null }[]
  owner_claims: { claim: string; quote: string }[]
  dismissed: string[]
}
export type DraftField = 'hero_headline' | 'hero_subheadline' | 'about' | 'cta_label' | 'offering'
export type DraftCommand = {
  field: DraftField; op: 'edit' | 'approve' | 'dismiss' | 'regenerate'
  text?: string; offering_name?: string
}
export type InterviewReadiness = {
  ready: boolean; missing: string[]; reason: string
  /** Can the first website be designed well: content, conversion, visuals, story, structure. */
  website?: Record<string, boolean>
}
export type CatalogueNeed = 'varieties' | 'cuts' | 'sizes' | 'projects' | 'price' | 'photo'
/** What the business sells, as a structure — groups and the items inside them. */
export type CatalogueGroup = {
  name: string
  items: { name: string; price: string; unit: string; description: string; source: string }[]
  sold_by: string; price: string; unit: string; needs: CatalogueNeed[]
  label_source: 'owner' | 'ai_suggestion'; description: string
}
/** One line of the catalogue as the owner reads it in a panel. */
export type CatalogueLine = {
  name: string; suggested_label: boolean; items: string[]; sold_by: string; price: string
  needs: CatalogueNeed[]
}
export type CatalogueEdit = { group: string; item?: string; price?: string; unit?: string; add_items?: string[] }
/** A canonical customer action ("order_whatsapp") and how it reads ("Order on WhatsApp"). */
export type InterviewAction = { id: string; label: string }
/** One typed line of how buying works. */
export type InterviewBuyingLine = {
  kind: 'units' | 'delivery' | 'pickup' | 'dine_in' | 'on_site' | 'payment'
  text: string
}
export type InterviewCoverage = 'unknown' | 'partial' | 'sufficient' | 'high_confidence'
/**
 * The side panel: typed understanding built by the server, never a fact dump.
 * Offerings, customer actions, website content, operating facts, place, hours
 * and tools are separate types and never mixed.
 */
export type InterviewUnderstanding = {
  business: {
    /** Empty while the name is still to be asked. */
    name: string
    kind: string
    category: string
    category_key: string
    subcategory_key: string
    /** "Fitness & wellness" — for "Looks like: Fitness & wellness → Gym". */
    category_group: string
    /** "inferred": read from what the owner said, shown as "Looks like…". */
    category_source: '' | 'owner_picked' | 'inferred'
    place: string
    name_pending: boolean
  }
  /** One sentence of what Locah understood, for the confirmation moment. */
  read_back: string
  /** What the side panel's "Change" can choose from. */
  options: {
    /** The ones that fit this business; `all_actions` behind "More". */
    actions: { id: string; label: string }[]
    all_actions: { id: string; label: string }[]
    fulfilment: { id: string; label: string }[]
    payment: { id: string; label: string }[]
  }
  /** What is chosen now, as ids (for the editors). */
  choices: { actions: string[]; fulfilment: string[]; payment: string[]; area: string }
  /** How the website will feel, once there is enough to say (design family words). */
  direction?: { family: string; words: string[] } | null
  offer: {
    summary: string
    groups: { name: string; items: string[]; price: string; needs: CatalogueNeed[] }[]
  }
  actions: InterviewAction[]
  buying: InterviewBuyingLine[]
  contact: { location: string; phone: string; hours: string }
  /** Parts of the website the owner asked for ("Contact section"). */
  content: string[]
  traits: string[]
  worth_knowing: { id: string; label: string; short: string; importance: 'blocking' | 'high_value' | 'enrichment' | 'optional' }[]
  tools: { id: string; label: string; why: string; choice: 'pending' | 'approved' | 'declined' }[]
  /** Quiet progress by dimension — never "question 12 of 19". */
  progress: { dimension: string; label: string; coverage: InterviewCoverage }[]
  readiness: InterviewReadiness
  logo:
    | { state: 'none' }
    | { state: 'ready'; source: 'USER_UPLOAD' | 'AI_GENERATED'; url: string | null }
    | { state: 'requested' | 'unavailable' | 'queued' | 'failed'; reason: string | null }
  /** One "so far" line, from typed understanding only. */
  synthesis: string
  kind: string
  catalogue: CatalogueLine[]
}
export type BusinessBlueprint = {
  schema_version: 1; business_id: string; session_id: string; revision: number
  created_at: string; updated_at: string; transport: 'chat' | 'voice'; turn_count: number
  identity: Record<string, InterviewFact>; business_classification: InterviewFact | null
  operating_model: InterviewFact | null; locations: InterviewFact | null; offerings: InterviewFact | null
  customer_actions: InterviewFact | null; operational_characteristics: InterviewFact | null
  brand: InterviewFact | null; tone: InterviewFact | null; colours: InterviewFact | null
  logo_state: 'not_supplied' | 'uploaded' | 'generation_requested' | 'generated'
  media_assets: InterviewMedia[]
  media_generation_requests: { role: 'hero' | 'logo' | 'visual'
    /** For a draft visual: the slot it fills ("hero", "category:chicken"). */
    key?: string
    status: 'requested' | 'unavailable' | 'queued' | 'ready' | 'failed'
    reason: string | null; asset_id: string | null }[]
  requested_capabilities: { intent: string; original_request: string }[]
  recommended_modules: InterviewModule[]; declined_modules: string[]; approved_modules: string[]
  website_content: Record<string, InterviewFact>; website_priorities: InterviewFact | null
  template_preferences: { template_id: string | null; source: 'PLATFORM' | 'USER_STATEMENT' }
  known_facts: Partial<Record<InterviewFactKey, InterviewFact>>
  suggested_content: Record<string, { text: string; source: 'AI_SUGGESTION'; confirmation: 'confirmed' | 'unconfirmed' }>
  unconfirmed_facts: Partial<Record<InterviewFactKey, InterviewFact>>
  unsupported_requests: { original_request: string; normalized_intent: string; business_classification: string
    closest_supported_capabilities: string[]; why_unsupported: string; required_mechanics: string[]; session_reference: string }[]
  remaining_questions: { field: InterviewFactKey; text: string; reason: string }[]
  completion_state: { status: 'collecting' | 'review' | 'ready' | 'built'; sufficient: boolean; confirmed: boolean
    completed_at: string | null; first_preview_at: string | null; generation_job_id: string | null
    /** First time there was enough for a strong first version. Build never disappears after. */
    ready_at?: string | null }
  messages: { role: 'user' | 'assistant'; text: string; at: string; via?: 'text' | 'voice' }[]
  last_turn: { provider: string; model: string; latency_ms: number; input_tokens: number | null
    output_tokens: number | null; cost: number | null; retries: number; fallback_reason: string | null } | null
  applied_requests: string[]
  /** How the owner talks: Locah answers in the same mix. */
  language_style: 'en' | 'ta' | 'ta_en' | 'hi' | 'hi_en' | 'other'
  /** The language the owner asked Locah to reply in; 'auto' mirrors each message. */
  language_preference?: 'auto' | 'en' | 'ta' | 'ta_en'
  operating_patterns: { pattern: string; quote: string }[]
  /** Numbers the owner said, verified against their own words. */
  highlights: { value: string; label: string; quote: string }[]
  asked_optional: ('locations' | 'phone' | 'logo')[]
  /** Discovery state per concept ("offerings.units", "fulfilment.mode", ...). */
  discovery: Record<string, DiscoveryTarget>
  last_asked_target: string | null
  website_draft: WebsiteDraft
  readiness: InterviewReadiness
  applied_setup_offerings: string[]
  taxonomy: { groups: CatalogueGroup[] }
  /** Whether the owner agreed to draft visuals for the website. */
  visual_consent: 'unknown' | 'draft_visuals' | 'own_photos' | 'none'
  /** The kind of business picked at creation — a seed for questions, never a fact. */
  category?: { category_key: string; subcategory_key: string; label: string; source: 'owner_picked' | 'inferred' } | null
  asks?: { ask: string; targets: string[]; turn: number }[]
  /** The owner chose "Keep refining first". */
  refining?: boolean
  checkpoint_turn?: number | null
  /** The owner asked to build: show the summary to confirm. */
  confirm_requested?: boolean
  content_wishes?: string[]
  /** Started by talking, before the business had a name: the name is asked once. */
  name_pending?: boolean
  documents?: DocumentRead[]
  media_plan?: PlannedMedia[]
}
export type BusinessInterviewData = {
  blueprint: BusinessBlueprint; classification_seed: string
  understanding: InterviewUnderstanding
  /** Build is offered as soon as there is something honest to build, and never withdrawn. */
  build_available?: boolean
  /** Items the owner named in the conversation that are not draft catalogue items yet. */
  setup_pending?: string[]
  available_modules: InterviewModule[]
  templates: { id: string; name: string; description: string; primary_color: string; accent_color: string
    available: boolean; look: string[]; page_count: number }[]
  voice: { available: boolean; reason: string }
  image_generation: { available: boolean; reason: string }
}
export type InterviewCommand = {
  revision: number; request_id: string
  action: 'turn' | 'confirm' | 'choices' | 'template' | 'media' | 'image' | 'build' | 'draft' | 'setup' | 'catalogue'
    | 'refine' | 'review' | 'correct' | 'keep_tools' | 'document' | 'document_apply'
  text?: string; field?: InterviewFactKey; choices?: Record<string, 'approved' | 'declined'>
  /** For action 'correct': which part of the understanding, and its typed new value. */
  slot?: 'offerings' | 'actions' | 'fulfilment' | 'area' | 'payment' | 'location' | 'phone' | 'hours'
    | 'story' | 'description' | 'price_visibility' | 'category' | 'name'
  values?: string[]
  /** A spoken turn arrives as its transcript, through this same command. */
  via?: 'text' | 'voice'
  template_id?: string; media?: InterviewMedia
  /** For action 'image': what to draw. */
  image_role?: 'hero' | 'logo'
  /** For action 'draft': edit, keep, remove or rewrite one piece of website wording. */
  draft?: DraftCommand
  /** For action 'catalogue': prices, units and varieties the owner typed. */
  catalogue?: CatalogueEdit[]
  /** For 'document' / 'document_apply': the uploaded file, and the lines ("Group::Item") accepted. */
  document_id?: string
  accept?: string[]
}

/** POST /v1/platform/businesses/start — a Business to talk to LOCAH about. */
export type StartConversationResult = {
  business: { id: string; slug: string; display_name: string }
  /** false: an untouched draft this owner had already started was reused. */
  created: boolean
}
/** GET /v1/public/taxonomy/search */
export type TaxonomyMatch = {
  category_key: string
  category_label: string
  subcategory_key: string
  subcategory_label: string
  template: string
  playbook: string
}
