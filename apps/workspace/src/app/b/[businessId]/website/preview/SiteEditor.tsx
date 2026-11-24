'use client'

/**
 * The Website editor.
 *
 * Two panes: the controls on the left, and on the right the ACTUAL public site
 * rendering this Business's draft, via a short-lived preview token. Nothing is
 * re-implemented — what the owner sees is the page their customers will get,
 * which is the only honest answer to "what will this look like?".
 *
 * Every save is the existing section content-update endpoint, so the structured
 * Website model stays authoritative and the owner can only change the things
 * their SectionType actually allows.
 *
 * Three ways to change the site, all on the same governed API:
 *   Sections   reword, re-picture, drag to reorder, hide, copy, remove, add
 *   Design     colours, lettering, sizes, corners — laid over the designed theme
 *   Ask LOCAH  any of the above, asked for in words
 * Clicking a part of the page in the preview opens it here (EditorBridge in
 * apps/web). An owner personalises; the composition and motion the site was
 * designed with are not theirs to break.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AssistantPanel } from './AssistantPanel'
import { DesignPanel } from './DesignPanel'
import {
  addSection,
  arrangeSection,
  duplicateSection,
  listSectionTypes,
  removeSection,
  reorderSections,
  setSectionVisible,
  type SectionType,
} from './structure-actions'
import {
  approveDraftImage,
  completeImageUpload,
  generateSectionImage,
  refreshPreviewToken,
  requestImageUpload,
  saveSectionContent,
} from './actions'

/** Preview tokens last 10 minutes; re-mint well inside that so a long editing
 *  session never drops to a broken frame. */
const TOKEN_REFRESH_MS = 7 * 60 * 1000

const ACCEPTED_IMAGE_TYPES = 'image/jpeg,image/png,image/webp,image/gif'
const MAX_IMAGE_BYTES = 10 * 1024 * 1024

type PicturePolicy = 'draw' | 'real_photo'

export type EditorSection = {
  id: string
  section_type_id: string
  layout_variant?: string | null
  content: Record<string, unknown>
  assets?: Record<string, { url: string; alt_text?: string | null; draft?: boolean }>
  /** Which pictures this section can carry — the server's one decision.
   *  "draw": generate, regenerate, upload, remove. "real_photo": upload only. */
  image_policy?: { self?: PicturePolicy; items?: PicturePolicy }
  is_visible: boolean
  sort_order?: number
  /** Set when the section shows a tool's live records (menu, rooms, plans). */
  module_binding?: unknown
}

export type EditorPage = {
  id: string
  title: string
  slug: string
  sections: EditorSection[]
}

type Field = { key: string; label: string; help?: string; multiline?: boolean }

/** A repeating field: a short list of small records the owner can add to,
 *  reword and remove, within the limit the section type allows. */
type ListField = {
  key: string
  label: string
  help?: string
  max: number
  parts: { key: string; label: string; multiline?: boolean; required?: boolean }[]
  addLabel: string
}

const LISTS: Record<string, ListField> = {
  feature_grid: {
    key: 'items',
    label: 'Items',
    max: 9,
    addLabel: 'Add an item',
    parts: [
      { key: 'title', label: 'Title', required: true },
      { key: 'body', label: 'Description (optional)', multiline: true },
    ],
  },
  highlights: {
    key: 'items',
    label: 'Numbers',
    help: 'Only numbers that are true — for example "15" and "years in business".',
    max: 6,
    addLabel: 'Add a number',
    parts: [
      { key: 'value', label: 'Number', required: true },
      { key: 'label', label: 'What it counts', required: true },
    ],
  },
}

/** What an owner may change, per section type. Anything not listed here is
 *  structure, and structure is not edited by hand. */
const FIELDS: Record<string, Field[]> = {
  hero: [
    { key: 'eyebrow', label: 'Small line above the headline', help: 'e.g. your area' },
    { key: 'headline', label: 'Headline', help: 'The first thing a visitor reads.' },
    {
      key: 'headline_accent',
      label: 'Words to colour',
      help: 'Part of the headline to show in your accent colour. Leave empty for none.',
    },
    { key: 'subheadline', label: 'Supporting line', multiline: true },
    { key: 'cta_label', label: 'Button text', help: 'e.g. "See the menu"' },
    { key: 'cta_url', label: 'Button goes to', help: 'A path on your site, like /menu' },
  ],
  about: [
    { key: 'title', label: 'Heading' },
    { key: 'body', label: 'Your story', multiline: true },
    { key: 'quote', label: 'A line in your words (optional)', multiline: true },
  ],
  text_block: [
    { key: 'title', label: 'Heading' },
    { key: 'body', label: 'Text', multiline: true },
  ],
  contact: [
    { key: 'title', label: 'Heading' },
    { key: 'address', label: 'Address', multiline: true },
    { key: 'phone', label: 'Phone' },
    { key: 'email', label: 'Email' },
    { key: 'hours_summary', label: 'Opening hours', multiline: true },
  ],
  cta_band: [
    { key: 'headline', label: 'Heading' },
    { key: 'body', label: 'Supporting line', multiline: true },
    { key: 'cta_label', label: 'Button text' },
    { key: 'cta_url', label: 'Button goes to' },
  ],
  offerings_list: [
    { key: 'title', label: 'Heading' },
    {
      key: 'subtitle',
      label: 'Supporting line',
      multiline: true,
      help: 'The items themselves come from your Offerings — edit them there.',
    },
  ],
  menu_section: [
    { key: 'title', label: 'Menu heading' },
  ],
  rooms_section: [
    { key: 'title', label: 'Rooms heading' },
    { key: 'subtitle', label: 'Supporting line', multiline: true },
  ],
  plans_section: [
    { key: 'title', label: 'Plans heading' },
    { key: 'subtitle', label: 'Supporting line', multiline: true },
  ],
  classes_section: [
    { key: 'title', label: 'Classes heading' },
  ],
  enquiry_form: [
    { key: 'title', label: 'Form heading' },
    { key: 'subtitle', label: 'Supporting line', multiline: true },
  ],
  gallery: [{ key: 'title', label: 'Gallery heading' }],
  location_list: [{ key: 'title', label: 'Heading' }],
  feature_grid: [
    { key: 'title', label: 'Heading' },
    { key: 'subtitle', label: 'Supporting line', multiline: true },
  ],
  highlights: [{ key: 'title', label: 'Heading (optional)' }],
  product_showcase: [
    { key: 'title', label: 'Heading' },
    {
      key: 'subtitle',
      label: 'Supporting line',
      multiline: true,
      help: 'The items and prices come from your catalogue — complete them there.',
    },
    { key: 'order_label', label: 'Order button text', help: 'e.g. "Order on WhatsApp"' },
  ],
  category_showcase: [
    { key: 'title', label: 'Heading' },
    { key: 'subtitle', label: 'Supporting line', multiline: true },
  ],
  fulfilment_strip: [{ key: 'title', label: 'Heading (optional)' }],
}

/** Human names for section types. Owners never see the identifier. */
const SECTION_NAMES: Record<string, string> = {
  hero: 'Top of the page',
  about: 'About',
  text_block: 'Text',
  contact: 'Contact details',
  cta_band: 'Call to action',
  offerings_list: 'What you offer',
  menu_section: 'Menu',
  rooms_section: 'Rooms',
  plans_section: 'Plans',
  classes_section: 'Classes',
  enquiry_form: 'Enquiry form',
  gallery: 'Gallery',
  location_list: 'Locations',
  feature_grid: 'What you do',
  highlights: 'Numbers',
  product_showcase: 'What you sell',
  category_showcase: 'Categories',
  fulfilment_strip: 'How ordering works',
  statement: 'Big statement',
  pillars: 'What you stand for',
  faq: 'Questions & answers',
  media_text: 'Story with a picture',
  marquee: 'Moving band of words',
  reviews_section: 'Customer reviews',
}

const COMPOSED_NAMES: Record<string, string> = {
  story: 'Your story (composed)',
  statement: 'Statement (composed)',
  pillars: 'What you stand for (composed)',
  numbers: 'Numbers (composed)',
  featured: 'Signature range (composed)',
}

function sectionName(s: EditorSection): string {
  if (s.section_type_id === 'composition') {
    const role = String((s.content as { role?: unknown })?.role || '')
    return COMPOSED_NAMES[role] || 'Composed section'
  }
  return SECTION_NAMES[s.section_type_id] || s.section_type_id.replace(/_/g, ' ')
}

type Row = Record<string, string>

function rowsOf(value: unknown): Row[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((v): v is Record<string, unknown> => Boolean(v) && typeof v === 'object')
    .map((v) => Object.fromEntries(Object.entries(v).map(([k, x]) => [k, String(x ?? '')])))
}

function ListEditor({
  field,
  sectionId,
  value,
  onCommit,
}: {
  field: ListField
  sectionId: string
  value: unknown
  onCommit: (rows: Row[]) => void
}) {
  const [rows, setRows] = useState<Row[]>(() => rowsOf(value))
  // Rows missing a required part are kept on screen while the owner types,
  // and left out of what is saved — the section type would reject them.
  const complete = (list: Row[]) =>
    list.filter((r) => field.parts.every((p) => !p.required || (r[p.key] || '').trim()))
  const save = (next: Row[]) => {
    setRows(next)
    onCommit(
      complete(next).map((r) =>
        Object.fromEntries(
          field.parts
            .map((p) => [p.key, (r[p.key] || '').trim()] as const)
            .filter(([, v]) => v !== '')
        )
      )
    )
  }
  return (
    <div className="ed-field">
      <span className="ed-label">{field.label}</span>
      {field.help ? <p className="ed-help" style={{ marginTop: 0 }}>{field.help}</p> : null}
      <ol className="ed-list">
        {rows.map((row, i) => (
          <li className="ed-list__row" key={i}>
            {field.parts.map((part) => {
              const id = `${sectionId}-${field.key}-${i}-${part.key}`
              const common = {
                id,
                className: `ed-input${part.multiline ? ' ed-input--area ed-input--short' : ''}`,
                defaultValue: row[part.key] || '',
                onBlur: (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => {
                  if (e.target.value === (row[part.key] || '')) return
                  save(rows.map((r, j) => (j === i ? { ...r, [part.key]: e.target.value } : r)))
                },
              }
              return (
                <div key={part.key}>
                  <label className="ed-sublabel" htmlFor={id}>
                    {part.label}
                  </label>
                  {part.multiline ? <textarea {...common} /> : <input {...common} />}
                </div>
              )
            })}
            <button
              type="button"
              className="ed-list__remove"
              onClick={() => save(rows.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </li>
        ))}
      </ol>
      {rows.length < field.max ? (
        <button
          type="button"
          className="btn btn-ghost ed-list__add"
          onClick={() => setRows([...rows, {}])}
        >
          {field.addLabel}
        </button>
      ) : null}
    </div>
  )
}

const REAL_PHOTO = 'This should be a real photo of your work — upload one instead.'

function ImageField({
  businessId,
  sectionId,
  policy,
  label = 'Picture',
  target,
  currentUrl,
  currentAssetId,
  draft,
  onUploaded,
  onRemove,
}: {
  businessId: string
  sectionId: string
  policy: PicturePolicy
  label?: string
  /** A card's picture inside the section; omitted for the section's own. */
  target?: { list_key: 'items' | 'categories'; index: number }
  currentUrl?: string
  currentAssetId?: string
  /** A picture LOCAH drew that the owner has not approved yet. */
  draft?: boolean
  onUploaded: (assetId: string) => void | Promise<void>
  onRemove: () => void | Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [justUploaded, setJustUploaded] = useState<string | null>(null)
  // What this field just put there, before the page reloads its data: a
  // picture LOCAH just drew is a draft at once (label + "Keep this picture").
  const [fresh, setFresh] = useState<{ id: string; drawn: boolean } | null>(null)
  const [kept, setKept] = useState(false)
  const [removed, setRemoved] = useState(false)
  const shown = removed ? null : justUploaded || currentUrl
  const assetId = fresh?.id ?? currentAssetId
  const isDraft = Boolean((fresh ? fresh.drawn : draft) && !kept)

  const pick = async (file: File) => {
    setError(null)
    if (file.size > MAX_IMAGE_BYTES) {
      setError('That image is over 10MB. Try a smaller one.')
      return
    }
    setBusy(true)
    try {
      const started = await requestImageUpload(businessId, file.type, file.size, file.name)
      if (!started.ok) {
        setError(started.error)
        return
      }
      const put = await fetch(started.uploadUrl, {
        method: 'PUT',
        headers: { 'Content-Type': file.type },
        body: file,
      })
      if (!put.ok) {
        setError(`Upload failed (${put.status}).`)
        return
      }
      const done = await completeImageUpload(businessId, started.assetId)
      if (!done.ok) {
        setError(done.error)
        return
      }
      if (done.url) setJustUploaded(done.url)
      setFresh({ id: started.assetId, drawn: false })
      setKept(false)
      setRemoved(false)
      await onUploaded(started.assetId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ed-field">
      <span className="ed-label">{label}</span>
      {shown ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="ed-thumb" src={shown} alt="" />
      ) : (
        <p className="ed-help" style={{ marginTop: 0 }}>
          No picture yet. A good photo of your space or your work makes the biggest difference.
        </p>
      )}
      {policy === 'real_photo' ? (
        <p className="ed-help" style={{ marginTop: 0 }}>{REAL_PHOTO}</p>
      ) : null}
      {isDraft ? (
        <p className="ed-help" style={{ marginTop: 0 }}>
          <strong>Draft picture by LOCAH</strong> — it illustrates the mood, it is not a photo of your
          business. Replace it with your own photo, keep it, or remove it.
        </p>
      ) : null}
      <label className={`btn btn-ghost ed-upload${busy ? ' is-busy' : ''}`}>
        {busy ? 'Working…' : shown ? 'Replace with my photo' : 'Add a picture'}
        <input
          type="file"
          accept={ACCEPTED_IMAGE_TYPES}
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) void pick(file)
          }}
        />
      </label>
      {policy === 'draw' ? (
      <button
        type="button"
        className="btn btn-ghost"
        disabled={busy}
        onClick={async () => {
          setError(null)
          setBusy(true)
          try {
            const result = await generateSectionImage(businessId, sectionId, target)
            if (!result.ok) {
              setError(result.error)
              return
            }
            if (result.url) setJustUploaded(result.url)
            setFresh({ id: result.assetId, drawn: true })
            setKept(false)
            setRemoved(false)
            await onUploaded(result.assetId)
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Generation failed.')
          } finally {
            setBusy(false)
          }
        }}
      >
        {shown ? 'Generate a new picture' : 'Generate a picture'}
      </button>
      ) : null}
      {isDraft && assetId ? (
        <button
          type="button"
          className="btn btn-ghost"
          disabled={busy}
          onClick={async () => {
            setError(null)
            setBusy(true)
            const result = await approveDraftImage(businessId, assetId)
            setBusy(false)
            if (result.ok) setKept(true)
            else setError(result.error)
          }}
        >
          Keep this picture
        </button>
      ) : null}
      {shown ? (
        <button
          type="button"
          className="btn btn-ghost"
          disabled={busy}
          onClick={async () => {
            setJustUploaded(null)
            setFresh(null)
            setRemoved(true)
            await onRemove()
          }}
        >
          Remove picture
        </button>
      ) : null}
      {error ? <p className="ed-error">{error}</p> : null}
    </div>
  )
}

type CardRow = Record<string, unknown>

/** Pictures on a section's cards (a category, a dish, a product). Each card
 *  is its own picture with the same controls; factual cards upload only. */
function CardPictures({
  businessId,
  section,
  listKey,
  policy,
  rows,
  onChange,
}: {
  businessId: string
  section: EditorSection
  listKey: 'items' | 'categories'
  policy: PicturePolicy
  rows: unknown
  onChange: (rows: CardRow[]) => void | Promise<void>
}) {
  const list: CardRow[] = Array.isArray(rows)
    ? rows.filter((r): r is CardRow => Boolean(r) && typeof r === 'object' && Boolean((r as CardRow).name))
    : []
  if (!list.length) return null
  const all: CardRow[] = Array.isArray(rows) ? (rows as CardRow[]) : []
  const setAt = (index: number, assetId: string | null) => {
    const next = all.map((r, i) => {
      if (i !== index) return r
      const copy = { ...r }
      if (assetId) copy.image_asset_id = assetId
      else delete copy.image_asset_id
      return copy
    })
    return onChange(next)
  }
  return (
    <details className="ed-field">
      <summary className="ed-label">
        {listKey === 'categories' ? 'Category pictures' : 'Pictures on the cards'} ({list.length})
      </summary>
      {all.map((row, index) =>
        row && typeof row === 'object' && row.name ? (
          <ImageField
            key={`${listKey}-${index}-${String(row.image_asset_id ?? '')}`}
            businessId={businessId}
            sectionId={section.id}
            policy={policy}
            label={String(row.name)}
            target={{ list_key: listKey, index }}
            currentUrl={section.assets?.[`${listKey}.${index}`]?.url}
            currentAssetId={typeof row.image_asset_id === 'string' ? row.image_asset_id : undefined}
            draft={section.assets?.[`${listKey}.${index}`]?.draft}
            onUploaded={(assetId) => setAt(index, assetId)}
            onRemove={() => setAt(index, null)}
          />
        ) : null
      )}
    </details>
  )
}

/** A gallery holds the business's own photos: upload, replace or remove. */
function GalleryPictures({
  businessId,
  section,
  ids,
  onChange,
}: {
  businessId: string
  section: EditorSection
  ids: string[]
  onChange: (ids: string[]) => void | Promise<void>
}) {
  return (
    <div className="ed-field">
      <span className="ed-label">Photos</span>
      {ids.map((id, index) => (
        <ImageField
          key={id}
          businessId={businessId}
          sectionId={section.id}
          policy="real_photo"
          label={`Photo ${index + 1}`}
          currentUrl={section.assets?.[`image_asset_id_${index}`]?.url}
          currentAssetId={id}
          onUploaded={(assetId) => onChange(ids.map((x, i) => (i === index ? assetId : x)))}
          onRemove={() => onChange(ids.filter((_, i) => i !== index))}
        />
      ))}
      {ids.length < 20 ? (
        <ImageField
          key={`add-${ids.length}`}
          businessId={businessId}
          sectionId={section.id}
          policy="real_photo"
          label="Add a photo"
          onUploaded={(assetId) => onChange([...ids, assetId])}
          onRemove={() => undefined}
        />
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------- compositions */

type CompBlock = Record<string, unknown> & { kind?: string }

const BLOCK_NAMES: Record<string, string> = {
  words: 'Words',
  picture: 'Picture',
  quote: 'Big sentence',
  number: 'Number',
  list: 'List',
  action: 'Button',
  label: 'Small label',
}

/** The words each kind of block shows, in the order an owner reads them. */
const BLOCK_FIELDS: Record<string, { key: string; label: string; multiline?: boolean }[]> = {
  words: [
    { key: 'eyebrow', label: 'Small line above' },
    { key: 'title', label: 'Heading' },
    { key: 'price', label: 'Price' },
    { key: 'body', label: 'Text', multiline: true },
    { key: 'cta_label', label: 'Link text' },
  ],
  quote: [{ key: 'title', label: 'Sentence', multiline: true }],
  number: [
    { key: 'value', label: 'Number' },
    { key: 'label', label: 'What it counts' },
  ],
  action: [{ key: 'cta_label', label: 'Button text' }],
  label: [{ key: 'label', label: 'Label' }],
  picture: [{ key: 'caption', label: 'Caption (optional)' }],
}

/**
 * A composed section's own panel: each block's words and pictures in reading
 * order, and the arrangement itself — the other way round, or another one.
 * Only words and pictures are edited here; where each block sits is the
 * arrangement's (the grammar on the server holds it whatever is saved).
 */
function CompositionEditor({
  businessId,
  section,
  items,
  policy,
  working,
  onSave,
  onArrange,
}: {
  businessId: string
  section: EditorSection
  items: unknown
  policy?: PicturePolicy
  working: boolean
  onSave: (items: CompBlock[]) => void | Promise<void>
  onArrange: (action: 'flip' | 'next') => void
}) {
  const blocks: CompBlock[] = Array.isArray(items)
    ? (items as unknown[]).filter((b): b is CompBlock => Boolean(b) && typeof b === 'object')
    : []
  const order = blocks
    .map((block, index) => ({ block, index }))
    .sort((a, b) => Number(a.block.m_order || 0) - Number(b.block.m_order || 0))
  const setField = (index: number, key: string, value: unknown) =>
    onSave(blocks.map((b, i) => (i === index ? { ...b, [key]: value } : b)))
  const setPoint = (index: number, at: number, key: string, value: string) => {
    const points = Array.isArray(blocks[index].points) ? [...(blocks[index].points as Record<string, string>[])] : []
    points[at] = { ...points[at], [key]: value }
    return setField(index, 'points', points)
  }
  return (
    <div className="ed-comp">
      <div className="ed-comp__arrange" role="group" aria-label="Arrangement">
        <button type="button" className="btn btn-ghost" disabled={working} onClick={() => onArrange('flip')}>
          Flip sides
        </button>
        <button type="button" className="btn btn-ghost" disabled={working} onClick={() => onArrange('next')}>
          Another arrangement
        </button>
      </div>
      <p className="ed-help">
        LOCAH arranged this section for your business. Change the words and pictures here, or ask for
        another arrangement — the same words and pictures, placed differently.
      </p>
      {order.map(({ block, index }) => {
        const kind = String(block.kind || '')
        const fields = (BLOCK_FIELDS[kind] || []).filter(
          (f) => kind !== 'words' || f.key !== 'price' || typeof block.price === 'string'
        )
        return (
          <fieldset className="ed-comp__block" key={`${kind}-${index}`}>
            <legend className="ed-sublabel">{BLOCK_NAMES[kind] || kind}</legend>
            {kind === 'picture' && policy ? (
              <ImageField
                businessId={businessId}
                sectionId={section.id}
                policy={policy}
                label="Picture"
                target={{ list_key: 'items', index }}
                currentUrl={section.assets?.[`items.${index}`]?.url}
                currentAssetId={typeof block.image_asset_id === 'string' ? block.image_asset_id : undefined}
                draft={section.assets?.[`items.${index}`]?.draft}
                onUploaded={(assetId) => setField(index, 'image_asset_id', assetId)}
                onRemove={() => setField(index, 'image_asset_id', '')}
              />
            ) : null}
            {fields.map((f) => {
              const id = `${section.id}-b${index}-${f.key}`
              const value = String(block[f.key] ?? '')
              const common = {
                id,
                className: `ed-input${f.multiline ? ' ed-input--area ed-input--short' : ''}`,
                defaultValue: value,
                onBlur: (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => {
                  if (e.target.value !== value) void setField(index, f.key, e.target.value)
                },
              }
              return (
                <div key={f.key}>
                  <label className="ed-sublabel" htmlFor={id}>
                    {f.label}
                  </label>
                  {f.multiline ? <textarea {...common} /> : <input {...common} />}
                </div>
              )
            })}
            {kind === 'list'
              ? ((Array.isArray(block.points) ? block.points : []) as Record<string, string>[]).map((point, at) => (
                  <div className="ed-comp__point" key={at}>
                    <label className="ed-sublabel" htmlFor={`${section.id}-b${index}-p${at}`}>
                      {`Point ${at + 1}`}
                    </label>
                    <input
                      id={`${section.id}-b${index}-p${at}`}
                      className="ed-input"
                      defaultValue={point.title || ''}
                      onBlur={(e) => {
                        if (e.target.value !== (point.title || '')) void setPoint(index, at, 'title', e.target.value)
                      }}
                    />
                    <textarea
                      aria-label={`Point ${at + 1} text`}
                      className="ed-input ed-input--area ed-input--short"
                      defaultValue={point.body || ''}
                      onBlur={(e) => {
                        if (e.target.value !== (point.body || '')) void setPoint(index, at, 'body', e.target.value)
                      }}
                    />
                  </div>
                ))
              : null}
          </fieldset>
        )
      })}
    </div>
  )
}

type Tab = 'sections' | 'design' | 'ask'

const DESKTOP_WIDTH = 1280
const PHONE_WIDTH = 390

function bySort(sections: EditorSection[]): EditorSection[] {
  return [...sections].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
}

/** Adding a section: what this business may add, and why it may not add the rest. */
function AddSection({
  businessId,
  onAdd,
  busy,
}: {
  businessId: string
  onAdd: (type: SectionType) => void
  busy: boolean
}) {
  const [open, setOpen] = useState(false)
  const [types, setTypes] = useState<SectionType[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!open || types) return
    let gone = false
    void listSectionTypes(businessId).then((res) => {
      if (gone) return
      if (res.ok) setTypes(res.data.section_types || [])
      else setError(res.error)
    })
    return () => {
      gone = true
    }
  }, [open, types, businessId])
  const offered = (types || []).filter((t) => t.can_start && t.id !== 'hero')
  return (
    <div className="ed-add">
      <button
        type="button"
        className="btn btn-ghost ed-add__open"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? 'Close' : '+ Add a section'}
      </button>
      {open ? (
        <div className="ed-add__list">
          {error ? <p className="ed-error">{error}</p> : null}
          {!types && !error ? <p className="ed-help">Loading what you can add…</p> : null}
          {offered.map((type) => (
            <button
              key={type.id}
              type="button"
              className="ed-add__item"
              disabled={busy || !type.available}
              onClick={() => {
                onAdd(type)
                setOpen(false)
              }}
            >
              <strong>{SECTION_NAMES[type.id] || type.label}</strong>
              <span>
                {type.available
                  ? type.description || 'Add it to the end of this page.'
                  : `Turn on ${String(type.requires_module || 'its tool').replace(/-/g, ' ')} first.`}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function SiteEditor({
  businessId,
  pages,
  theme,
  previewPath,
  webUrl,
  publishHref,
}: {
  businessId: string
  pages: EditorPage[]
  theme: Record<string, unknown>
  previewPath: string | null
  webUrl: string
  publishHref: string
}) {
  const router = useRouter()
  const [pageIdx, setPageIdx] = useState(0)
  const [tab, setTab] = useState<Tab>('sections')
  const [openSection, setOpenSection] = useState<string | null>(pages[0]?.sections[0]?.id ?? null)
  // Only what the owner has typed since the page loaded; everything else is
  // the server's own content, so a refresh never shows stale words.
  const [content, setContent] = useState<Record<string, Record<string, unknown>>>({})
  const [status, setStatus] = useState<{ msg: string; error: boolean } | null>(null)
  const [device, setDevice] = useState<'desktop' | 'mobile'>('desktop')
  const [nonce, setNonce] = useState(0)
  const [path, setPath] = useState(previewPath)
  const [working, setWorking] = useState(false)
  const [dragId, setDragId] = useState<string | null>(null)
  const [overId, setOverId] = useState<string | null>(null)
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)
  const iframeRef = useRef<HTMLIFrameElement>(null)
  /** How far down the preview the owner has scrolled (told by EditorBridge). */
  const scrollAt = useRef(0)
  // "Desktop" means a desktop: the page is laid out at a real desktop width
  // and scaled down to fit this pane, so an owner judges the layout visitors
  // on a laptop get — not the tablet layout a 700px frame would trigger.
  const frameRef = useRef<HTMLDivElement>(null)
  const [pane, setPane] = useState({ w: 0, h: 0 })
  useEffect(() => {
    const el = frameRef.current
    if (!el) return
    const measure = () => setPane({ w: el.clientWidth, h: el.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  const roomW = Math.max(0, pane.w - 24)
  const roomH = Math.max(0, pane.h - 24)
  const layoutW = device === 'desktop' ? Math.max(DESKTOP_WIDTH, roomW) : PHONE_WIDTH
  const scale = roomW ? Math.min(1, roomW / layoutW) : 1

  const page = pages[Math.min(pageIdx, pages.length - 1)]
  const [order, setOrder] = useState<EditorSection[]>(() => bySort(page?.sections || []))
  // The server's sections are the truth: adopt them whenever they arrive
  // (first load, another page, or after a change was saved and re-read).
  useEffect(() => {
    setOrder(bySort(page?.sections || []))
  }, [page])

  useEffect(() => {
    const id = setInterval(async () => {
      const res = await refreshPreviewToken(businessId)
      if (res.ok) {
        setPath(res.previewPath)
        setNonce((n) => n + 1)
      }
    }, TOKEN_REFRESH_MS)
    return () => clearInterval(id)
  }, [businessId])

  // The preview reloads after a save so the owner sees the change land on the
  // real page rather than in a mock of it.
  const reloadPreview = useCallback(() => setNonce((n) => n + 1), [])
  const say = useCallback((msg: string, error = false) => setStatus({ msg, error }), [])

  const previewSrc = (() => {
    if (!path) return null
    const [base, query] = path.split('?')
    const pagePath = page && page.slug !== 'home' ? `${base}/${page.slug}` : base
    return `${webUrl}${pagePath}?${query}&v=${nonce}`
  })()

  useEffect(() => {
    scrollAt.current = 0
    setOpenSection(pages[pageIdx]?.sections[0]?.id ?? null)
    // Only when the owner switches page — not on every re-read of the same one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageIdx])

  // Pointing at the real page: a click on a section in the preview opens it
  // here, and opening one here brings it into view there (EditorBridge).
  const focusInPreview = useCallback((sectionId: string | null) => {
    iframeRef.current?.contentWindow?.postMessage({ type: 'locah-editor:focus', sectionId }, '*')
  }, [])
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return
      const data = event.data as { type?: string; sectionId?: string; y?: number } | null
      if (data?.type === 'locah-editor:scroll' && typeof data.y === 'number') scrollAt.current = data.y
      if (data?.type === 'locah-editor:select' && typeof data.sectionId === 'string') {
        setTab('sections')
        setOpenSection(data.sectionId)
        document.getElementById(`ed-sec-${data.sectionId}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }
      if (data?.type === 'locah-editor:ready') {
        // A reload after a save: back to where the owner was looking, not the top.
        if (scrollAt.current > 0) {
          iframeRef.current?.contentWindow?.postMessage({ type: 'locah-editor:restore', y: scrollAt.current }, '*')
        }
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])

  const open = (sectionId: string | null) => {
    setOpenSection(sectionId)
    setMenuFor(null)
    focusInPreview(sectionId)
  }

  const commit = async (section: EditorSection, key: string, next: unknown) => {
    const merged = { ...(content[section.id] ?? section.content), [key]: next }
    setContent((prev) => ({ ...prev, [section.id]: merged }))
    say('Saving…')
    const res = await saveSectionContent(businessId, section.id, merged)
    if (res.ok) {
      // Stays put rather than fading. "Did that save?" is the question an owner
      // asks, and a message that disappears after two seconds does not answer it.
      say('All changes saved to your draft')
      reloadPreview()
    } else {
      say(res.error || 'Could not save', true)
    }
  }

  /** One structural change: do it, say so, then read the page again. */
  const change = async (
    run: () => Promise<{ ok: true; data: unknown } | { ok: false; error: string }>,
    said: string,
    undo?: () => void
  ) => {
    setWorking(true)
    say('Saving…')
    const res = await run()
    setWorking(false)
    if (!res.ok) {
      undo?.()
      say(res.error, true)
      return false
    }
    say(said)
    reloadPreview()
    router.refresh()
    return true
  }

  const moveTo = (sectionId: string, toIndex: number) => {
    const from = order.findIndex((s) => s.id === sectionId)
    if (from < 0 || !page) return
    const next = [...order]
    const [moved] = next.splice(from, 1)
    next.splice(Math.max(0, Math.min(next.length, toIndex)), 0, moved)
    if (next.every((s, i) => s.id === order[i]?.id)) return
    const before = order
    setOrder(next)
    void change(
      () => reorderSections(businessId, page.id, next.map((s) => s.id)),
      'New order saved to your draft',
      () => setOrder(before)
    )
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'sections', label: 'Sections' },
    { id: 'design', label: 'Design' },
    { id: 'ask', label: 'Ask LOCAH' },
  ]

  return (
    <div className="ed">
      <aside className="ed__rail">
        <div className="ed__railhead">
          <label className="ed-label" htmlFor="ed-page">
            Page
          </label>
          <select
            id="ed-page"
            className="ed-select"
            value={pageIdx}
            onChange={(e) => setPageIdx(Number(e.target.value))}
          >
            {pages.map((p, i) => (
              <option key={p.id} value={i}>
                {p.title}
              </option>
            ))}
          </select>
          <div className="ed-tabs" role="tablist" aria-label="What to change">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                id={`ed-tab-${t.id}`}
                aria-selected={tab === t.id}
                aria-controls={`ed-panel-${t.id}`}
                className="ed-tabs__tab"
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div
          className="ed__sections"
          role="tabpanel"
          id={`ed-panel-${tab}`}
          aria-labelledby={`ed-tab-${tab}`}
        >
          {tab === 'design' ? (
            <DesignPanel businessId={businessId} theme={theme} onChanged={() => { reloadPreview(); router.refresh() }} onStatus={say} />
          ) : null}

          {tab === 'ask' ? (
            <AssistantPanel
              businessId={businessId}
              pageId={page?.id}
              pageTitle={page?.title}
              onChanged={() => {
                setContent({})
                say('LOCAH changed your draft')
                reloadPreview()
                router.refresh()
              }}
            />
          ) : null}

          {tab === 'sections' ? (
            <>
              <p className="ed-help ed-sections__hint">
                Click a part of your page on the right to open it here. Drag <span aria-hidden="true">⠿</span> to
                move a section.
              </p>
              {order.map((section, index) => {
                const isOpen = openSection === section.id
                const fields = FIELDS[section.section_type_id] || []
                const list = LISTS[section.section_type_id]
                const current = content[section.id] ?? section.content ?? {}
                const bound = Boolean(section.module_binding)
                const hidden = section.is_visible === false
                const isHero = section.section_type_id === 'hero'
                return (
                  <div
                    className="ed-sec"
                    key={section.id}
                    id={`ed-sec-${section.id}`}
                    data-open={isOpen}
                    data-hidden={hidden || undefined}
                    data-dragging={dragId === section.id || undefined}
                    data-over={overId === section.id && dragId !== section.id ? 'true' : undefined}
                    onDragOver={(e) => {
                      if (!dragId) return
                      e.preventDefault()
                      e.dataTransfer.dropEffect = 'move'
                      if (overId !== section.id) setOverId(section.id)
                    }}
                    onDrop={(e) => {
                      e.preventDefault()
                      const moved = dragId
                      setDragId(null)
                      setOverId(null)
                      if (moved && moved !== section.id) moveTo(moved, index)
                    }}
                  >
                    <div className="ed-sec__bar">
                      <span
                        className="ed-sec__grip"
                        draggable={!working}
                        role="img"
                        aria-label={`Drag to move ${sectionName(section)}`}
                        title="Drag to move"
                        onDragStart={(e) => {
                          setDragId(section.id)
                          e.dataTransfer.effectAllowed = 'move'
                          e.dataTransfer.setData('text/plain', section.id)
                        }}
                        onDragEnd={() => {
                          setDragId(null)
                          setOverId(null)
                        }}
                      >
                        ⠿
                      </span>
                      <button
                        type="button"
                        className="ed-sec__head"
                        onClick={() => open(isOpen ? null : section.id)}
                        aria-expanded={isOpen}
                      >
                        <span>
                          {sectionName(section)}
                          {hidden ? <em className="ed-sec__tag">Hidden</em> : null}
                        </span>
                      </button>
                      <div className="ed-sec__tools">
                        <button
                          type="button"
                          className="ed-icon"
                          aria-label={`Move ${sectionName(section)} up`}
                          title="Move up"
                          disabled={working || index === 0}
                          onClick={() => moveTo(section.id, index - 1)}
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          className="ed-icon"
                          aria-label={`Move ${sectionName(section)} down`}
                          title="Move down"
                          disabled={working || index === order.length - 1}
                          onClick={() => moveTo(section.id, index + 1)}
                        >
                          ↓
                        </button>
                        <button
                          type="button"
                          className="ed-icon"
                          aria-label={`More for ${sectionName(section)}`}
                          aria-expanded={menuFor === section.id}
                          title="More"
                          onClick={() => {
                            setMenuFor(menuFor === section.id ? null : section.id)
                            setConfirmRemove(null)
                          }}
                        >
                          ⋯
                        </button>
                      </div>
                    </div>

                    {menuFor === section.id ? (
                      <div className="ed-sec__menu">
                        {!isHero ? (
                          <button
                            type="button"
                            className="ed-sec__menuitem"
                            disabled={working}
                            onClick={() => {
                              setMenuFor(null)
                              const before = order
                              setOrder(order.map((s) => (s.id === section.id ? { ...s, is_visible: hidden } : s)))
                              void change(
                                () => setSectionVisible(businessId, section.id, hidden),
                                hidden ? 'Shown again on your draft' : 'Hidden on your draft — nothing is deleted',
                                () => setOrder(before)
                              )
                            }}
                          >
                            {hidden ? 'Show on the page' : 'Hide from the page'}
                          </button>
                        ) : null}
                        {!bound ? (
                          <button
                            type="button"
                            className="ed-sec__menuitem"
                            disabled={working}
                            onClick={() => {
                              setMenuFor(null)
                              void change(() => duplicateSection(businessId, section.id), 'A copy was added below it')
                            }}
                          >
                            Make a copy
                          </button>
                        ) : null}
                        {!isHero && !bound ? (
                          confirmRemove === section.id ? (
                            <div className="ed-sec__confirm">
                              <span>Remove this section and its words?</span>
                              <button
                                type="button"
                                className="ed-sec__menuitem is-danger"
                                disabled={working}
                                onClick={() => {
                                  setMenuFor(null)
                                  setConfirmRemove(null)
                                  void change(() => removeSection(businessId, section.id), 'Removed from your draft')
                                }}
                              >
                                Yes, remove it
                              </button>
                              <button type="button" className="ed-sec__menuitem" onClick={() => setConfirmRemove(null)}>
                                Keep it
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="ed-sec__menuitem is-danger"
                              onClick={() => setConfirmRemove(section.id)}
                            >
                              Remove…
                            </button>
                          )
                        ) : null}
                        {isHero ? <p className="ed-help">The top of the page always stays — you can reword it or change its picture.</p> : null}
                        {bound ? (
                          <p className="ed-help">
                            This section belongs to one of your tools, so it can be hidden but not removed.
                          </p>
                        ) : null}
                      </div>
                    ) : null}

                    {isOpen ? (
                      <div className="ed-sec__body">
                        {fields.length === 0 && !section.image_policy?.self && !section.image_policy?.items &&
                        section.section_type_id !== 'composition' ? (
                          <p className="ed-help">
                            This section arranges itself from your business details. There is nothing
                            to type here.
                          </p>
                        ) : null}

                        {fields.map((f) => (
                          <div className="ed-field" key={f.key}>
                            <label className="ed-label" htmlFor={`${section.id}-${f.key}`}>
                              {f.label}
                            </label>
                            {f.multiline ? (
                              <textarea
                                id={`${section.id}-${f.key}`}
                                className="ed-input ed-input--area"
                                defaultValue={String(current[f.key] ?? '')}
                                onBlur={(e) => {
                                  if (e.target.value !== String(current[f.key] ?? '')) {
                                    void commit(section, f.key, e.target.value)
                                  }
                                }}
                              />
                            ) : (
                              <input
                                id={`${section.id}-${f.key}`}
                                className="ed-input"
                                defaultValue={String(current[f.key] ?? '')}
                                onBlur={(e) => {
                                  if (e.target.value !== String(current[f.key] ?? '')) {
                                    void commit(section, f.key, e.target.value)
                                  }
                                }}
                              />
                            )}
                            {f.help ? <p className="ed-help">{f.help}</p> : null}
                          </div>
                        ))}

                        {list ? (
                          <ListEditor
                            field={list}
                            sectionId={section.id}
                            value={current[list.key]}
                            onCommit={(rows) => void commit(section, list.key, rows)}
                          />
                        ) : null}

                        {section.image_policy?.self && section.section_type_id !== 'gallery' ? (
                          <ImageField
                            businessId={businessId}
                            sectionId={section.id}
                            policy={section.image_policy.self}
                            currentUrl={section.assets?.image_asset_id?.url}
                            currentAssetId={typeof current.image_asset_id === 'string' ? current.image_asset_id : undefined}
                            draft={section.assets?.image_asset_id?.draft}
                            onUploaded={(assetId) => commit(section, 'image_asset_id', assetId)}
                            onRemove={() => commit(section, 'image_asset_id', null)}
                          />
                        ) : null}

                        {section.section_type_id === 'gallery' && section.image_policy?.self ? (
                          <GalleryPictures
                            businessId={businessId}
                            section={section}
                            ids={Array.isArray(current.image_asset_ids) ? current.image_asset_ids.map(String) : []}
                            onChange={(ids) => commit(section, 'image_asset_ids', ids)}
                          />
                        ) : null}

                        {section.section_type_id === 'composition' ? (
                          <CompositionEditor
                            businessId={businessId}
                            section={section}
                            items={current.items}
                            policy={section.image_policy?.items}
                            working={working}
                            onSave={(items) => commit(section, 'items', items)}
                            onArrange={(action) =>
                              void change(
                                () => arrangeSection(businessId, section.id, action),
                                action === 'flip'
                                  ? 'Flipped on your draft'
                                  : 'Another arrangement on your draft — the same words and pictures'
                              )
                            }
                          />
                        ) : null}

                        {section.image_policy?.items && section.section_type_id !== 'composition'
                          ? (['items', 'categories'] as const).map((listKey) => (
                              <CardPictures
                                key={listKey}
                                businessId={businessId}
                                section={section}
                                listKey={listKey}
                                policy={section.image_policy!.items!}
                                rows={current[listKey]}
                                onChange={(rows) => commit(section, listKey, rows)}
                              />
                            ))
                          : null}

                        {bound ? (
                          <p className="ed-help">
                            The items shown here come from your Offerings, so they stay correct as you
                            add and remove them.
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                )
              })}
              {page ? (
                <AddSection
                  businessId={businessId}
                  busy={working}
                  onAdd={(type) =>
                    void change(
                      () => addSection(businessId, page.id, type.id),
                      `${SECTION_NAMES[type.id] || type.label} added at the end of this page — open it to make it yours`
                    )
                  }
                />
              ) : null}
            </>
          ) : null}
        </div>

        <div className="ed__railfoot">
          {status ? (
            <p className={`ed-status${status.error ? ' is-error' : ''}`} role="status">
              {status.msg}
            </p>
          ) : (
            <p className="ed-status">Changes save to your draft. Your live site changes only when you publish.</p>
          )}
          <a className="btn btn-primary ed__publish" href={publishHref}>
            Review &amp; publish
          </a>
        </div>
      </aside>

      <div className="ed__stage">
        <div className="ed__stagebar">
          <span className="ed-help" style={{ margin: 0 }}>
            Your draft, exactly as visitors will see it
          </span>
          {previewSrc ? (
            <a href={previewSrc} target="_blank" rel="noreferrer" className="ed__full-preview">
              Open full-size preview ↗
            </a>
          ) : null}
          {scale < 0.98 ? (
            <span className="ed-help" style={{ margin: 0 }}>
              Shown at {Math.round(scale * 100)}%
            </span>
          ) : null}
          <div className="ed__devices" role="group" aria-label="Preview size">
            <button
              type="button"
              data-active={device === 'desktop'}
              onClick={() => setDevice('desktop')}
            >
              Desktop
            </button>
            <button
              type="button"
              data-active={device === 'mobile'}
              onClick={() => setDevice('mobile')}
            >
              Phone
            </button>
          </div>
        </div>
        <div className="ed__frame" ref={frameRef} data-device={device}>
          {previewSrc ? (
            <div
              className="ed__canvas"
              style={{ width: Math.round(layoutW * scale), height: roomH || undefined }}
            >
              <iframe
                ref={iframeRef}
                key={previewSrc}
                src={previewSrc}
                title="Website preview"
                style={{
                  width: layoutW,
                  height: roomH ? Math.round(roomH / scale) : 800,
                  transform: scale < 1 ? `scale(${scale})` : undefined,
                }}
              />
            </div>
          ) : (
            <p className="ed-help" style={{ padding: '2rem' }}>
              The preview could not be opened. Your draft is safe — try reloading this page.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
