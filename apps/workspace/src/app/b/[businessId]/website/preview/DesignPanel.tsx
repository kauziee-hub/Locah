'use client'

/**
 * Design — the owner's own colours, lettering, sizes and corners.
 *
 * Personalise, not redesign: these are the choices an owner should be able to
 * make about their own site without being able to break it. Each one is saved
 * as a small edit that the API lays over the stored theme, so the composition,
 * motion and art direction the site was built with are never touched — and
 * "As designed" always gives the original back.
 */

import React, { useEffect, useState } from 'react'
import { loadStyleOptions, matchReference, saveThemeEdit, undoReference, type StyleOptions } from './structure-actions'

type Theme = Record<string, unknown>

const PALETTES: { name: string; primary: string; accent: string }[] = [
  { name: 'Forest & turmeric', primary: '#2f5d1f', accent: '#c8922a' },
  { name: 'Maroon & gold', primary: '#7b1e2b', accent: '#b8860b' },
  { name: 'Navy & coral', primary: '#1b2a52', accent: '#e2674a' },
  { name: 'Teal & amber', primary: '#0f766e', accent: '#c98a12' },
  { name: 'Charcoal & saffron', primary: '#2b2d30', accent: '#e07b00' },
  { name: 'Plum & rose', primary: '#6b2d5c', accent: '#c2587a' },
  { name: 'Royal blue & sky', primary: '#1f3fb0', accent: '#2a8fd4' },
  { name: 'Coffee & sand', primary: '#4b3325', accent: '#a9794d' },
  { name: 'Emerald & lime', primary: '#0f7a55', accent: '#6a9a1f' },
  { name: 'Black & gold', primary: '#141414', accent: '#b8860b' },
]

const GROUNDS: { id: string; label: string; edit: Record<string, string | null> }[] = [
  // A ground comes with its alternate band and muted words, or a dark page keeps light bands.
  {
    id: 'designed',
    label: 'As designed',
    edit: { background_color: null, text_color: null, surface_alt_color: null, muted_color: null },
  },
  {
    id: 'white',
    label: 'White',
    edit: { background_color: '#ffffff', text_color: '#1a1a1a', surface_alt_color: '#f5f5f4', muted_color: '#6b6b6b', palette_mode: 'light' },
  },
  {
    id: 'cream',
    label: 'Cream',
    edit: { background_color: '#faf5ec', text_color: '#1f1a14', surface_alt_color: '#f2eadb', muted_color: '#6f665a', palette_mode: 'light' },
  },
  {
    id: 'dark',
    label: 'Dark',
    edit: { background_color: '#151515', text_color: '#f5f1ea', surface_alt_color: '#202020', muted_color: '#a8a39b', palette_mode: 'dark' },
  },
]

const SIZE_LABELS: Record<string, string> = {
  small: 'Small',
  regular: 'Standard',
  large: 'Large',
  xlarge: 'Largest',
}
const CORNER_LABELS: Record<string, string> = { sharp: 'Sharp', soft: 'Soft', round: 'Round' }
const HEX = /^#[0-9a-fA-F]{6}$/

function ownerStyleOf(theme: Theme): Record<string, string> {
  const raw = theme.owner_style
  return raw && typeof raw === 'object' ? (raw as Record<string, string>) : {}
}

function Segmented({
  label,
  value,
  options,
  onPick,
  busy,
}: {
  label: string
  value: string
  options: { id: string; label: string }[]
  onPick: (id: string) => void
  busy: boolean
}) {
  return (
    <div className="ed-field">
      <span className="ed-label">{label}</span>
      <div className="ed-seg" role="group" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.id}
            type="button"
            className="ed-seg__btn"
            data-active={value === option.id}
            aria-pressed={value === option.id}
            disabled={busy}
            onClick={() => onPick(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function ColourField({
  label,
  help,
  value,
  onCommit,
  busy,
}: {
  label: string
  help: string
  value: string
  onCommit: (hex: string) => void
  busy: boolean
}) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const id = `ed-colour-${label.replace(/\W+/g, '-').toLowerCase()}`
  return (
    <div className="ed-field">
      <label className="ed-label" htmlFor={id}>
        {label}
      </label>
      <div className="ed-colour">
        <input
          type="color"
          aria-label={`${label} — pick a colour`}
          value={HEX.test(draft) ? draft : '#000000'}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={(e) => {
            if (e.target.value !== value) onCommit(e.target.value)
          }}
        />
        <input
          id={id}
          className="ed-input"
          value={draft}
          spellCheck={false}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value.trim())}
          onBlur={() => {
            const next = draft.startsWith('#') ? draft : `#${draft}`
            if (HEX.test(next) && next.toLowerCase() !== value.toLowerCase()) onCommit(next)
            else setDraft(value)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          }}
        />
      </div>
      <p className="ed-help">{help}</p>
    </div>
  )
}

export function DesignPanel({
  businessId,
  theme: initial,
  onChanged,
  onStatus,
}: {
  businessId: string
  theme: Theme
  /** The preview should reload: the draft's look just changed. */
  onChanged: () => void
  onStatus: (msg: string, error?: boolean) => void
}) {
  const [theme, setTheme] = useState<Theme>(initial)
  const [options, setOptions] = useState<StyleOptions | null>(null)
  const [busy, setBusy] = useState(false)
  const [reference, setReference] = useState<string | null>(null)
  useEffect(() => setTheme(initial), [initial])
  useEffect(() => {
    let gone = false
    void loadStyleOptions(businessId).then((res) => {
      if (!gone && res.ok) setOptions(res.data)
    })
    return () => {
      gone = true
    }
  }, [businessId])

  const style = ownerStyleOf(theme)
  const primary = String(theme.primary_color || '#1f3d34')
  const accent = String(theme.accent_color || primary)
  const ground = GROUNDS.find((g) => g.edit.background_color && g.edit.background_color === theme.background_color)
  const personalised = Object.keys(style).length > 0

  const apply = async (edit: Record<string, unknown>, said: string) => {
    setBusy(true)
    onStatus('Saving…')
    const res = await saveThemeEdit(businessId, edit)
    setBusy(false)
    if (!res.ok) {
      onStatus(res.error, true)
      return
    }
    setTheme(res.data.theme || {})
    onStatus(said)
    onChanged()
  }
  const setStyle = (key: string, value: string | null, said: string) =>
    apply({ owner_style: { [key]: value } }, said)

  const matched = Boolean(theme.reference_undo)
  const matchFrom = async (file: File | undefined) => {
    if (!file) return
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setReference('Send a JPG, PNG or WebP picture.')
      return
    }
    if (file.size > 6 * 1024 * 1024) {
      setReference('That picture is over 6 MB — send a smaller screenshot.')
      return
    }
    setBusy(true)
    setReference('Looking at the design…')
    const bytes = new Uint8Array(await file.arrayBuffer())
    let binary = ''
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
    const res = await matchReference(businessId, btoa(binary), file.type)
    setBusy(false)
    if (!res.ok) {
      setReference(res.error)
      return
    }
    setReference(res.data.reply)
    if (res.data.matched && res.data.theme) {
      setTheme(res.data.theme)
      onStatus('Design matched on your draft')
      onChanged()
    }
  }

  return (
    <div className="ed-design">
      <section className="ed-design__group" aria-labelledby="ed-d-ref">
        <h3 className="ed-design__title" id="ed-d-ref">
          Match a design you like
        </h3>
        <p className="ed-help" style={{ marginTop: 0 }}>
          Seen a website or poster you love? Add a screenshot. LOCAH takes its colours, lettering and shapes for
          your site — your layout, pictures and words stay your own.
        </p>
        <label className={`btn btn-ghost ed-upload${busy ? ' is-busy' : ''}`}>
          {busy ? 'Working…' : 'Add a screenshot'}
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              void matchFrom(file)
            }}
          />
        </label>
        {reference ? (
          <p className="ed-help" role="status">
            {reference}
          </p>
        ) : null}
        {matched ? (
          <button
            type="button"
            className="btn btn-ghost ed-design__reset"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              const res = await undoReference(businessId)
              setBusy(false)
              if (!res.ok) {
                setReference(res.error)
                return
              }
              setReference(res.data.reply)
              if (res.data.theme) setTheme(res.data.theme)
              onStatus('Back to how it looked before the match')
              onChanged()
            }}
          >
            Undo the match
          </button>
        ) : null}
      </section>

      <section className="ed-design__group" aria-labelledby="ed-d-colours">
        <h3 className="ed-design__title" id="ed-d-colours">
          Colours
        </h3>
        <ColourField
          label="Main colour"
          help="Buttons, links and the things you want pressed."
          value={primary}
          busy={busy}
          onCommit={(hex) => apply({ primary_color: hex }, 'Main colour saved to your draft')}
        />
        <ColourField
          label="Accent colour"
          help="Highlights, prices and coloured words in a headline."
          value={accent}
          busy={busy}
          onCommit={(hex) => apply({ accent_color: hex }, 'Accent colour saved to your draft')}
        />
        <div className="ed-field">
          <span className="ed-label">Ready-made pairs</span>
          <div className="ed-swatches">
            {PALETTES.map((pair) => (
              <button
                key={pair.name}
                type="button"
                className="ed-swatch"
                title={pair.name}
                aria-label={`Use ${pair.name}`}
                data-active={primary.toLowerCase() === pair.primary && accent.toLowerCase() === pair.accent}
                disabled={busy}
                onClick={() =>
                  apply({ primary_color: pair.primary, accent_color: pair.accent }, `${pair.name} saved to your draft`)
                }
              >
                <span style={{ background: pair.primary }} />
                <span style={{ background: pair.accent }} />
              </button>
            ))}
          </div>
        </div>
        <Segmented
          label="Page background"
          value={ground?.id || 'designed'}
          busy={busy}
          options={GROUNDS.map((g) => ({ id: g.id, label: g.label }))}
          onPick={(id) => {
            const chosen = GROUNDS.find((g) => g.id === id)
            if (chosen) void apply(chosen.edit, 'Background saved to your draft')
          }}
        />
      </section>

      <section className="ed-design__group" aria-labelledby="ed-d-type">
        <h3 className="ed-design__title" id="ed-d-type">
          Lettering
        </h3>
        <div className="ed-fonts" role="group" aria-label="Lettering style">
          <button
            type="button"
            className="ed-font"
            data-active={!style.font}
            aria-pressed={!style.font}
            disabled={busy}
            onClick={() => setStyle('font', null, 'Back to the designed lettering')}
          >
            <strong>As designed</strong>
            <span>The faces LOCAH chose for your site</span>
          </button>
          {(options?.fonts || []).map((font) => (
            <button
              key={font.id}
              type="button"
              className="ed-font"
              data-active={style.font === font.id}
              aria-pressed={style.font === font.id}
              disabled={busy}
              onClick={() => setStyle('font', font.id, `“${font.label}” lettering saved to your draft`)}
            >
              <strong>{font.label}</strong>
              <span>{font.note}</span>
            </button>
          ))}
        </div>
        <Segmented
          label="Heading size"
          value={style.heading_size || 'regular'}
          busy={busy}
          options={(options?.sizes || Object.keys(SIZE_LABELS)).map((id) => ({ id, label: SIZE_LABELS[id] || id }))}
          onPick={(id) => setStyle('heading_size', id === 'regular' ? null : id, 'Heading size saved to your draft')}
        />
        <Segmented
          label="Reading text size"
          value={style.text_size || 'regular'}
          busy={busy}
          options={(options?.sizes || Object.keys(SIZE_LABELS)).map((id) => ({ id, label: SIZE_LABELS[id] || id }))}
          onPick={(id) => setStyle('text_size', id === 'regular' ? null : id, 'Text size saved to your draft')}
        />
      </section>

      <section className="ed-design__group" aria-labelledby="ed-d-shape">
        <h3 className="ed-design__title" id="ed-d-shape">
          Shape
        </h3>
        <Segmented
          label="Corners of buttons, cards and pictures"
          value={style.corners || 'designed'}
          busy={busy}
          options={[
            { id: 'designed', label: 'As designed' },
            ...(options?.corners || Object.keys(CORNER_LABELS)).map((id) => ({ id, label: CORNER_LABELS[id] || id })),
          ]}
          onPick={(id) => setStyle('corners', id === 'designed' ? null : id, 'Corners saved to your draft')}
        />
      </section>

      {personalised ? (
        <button
          type="button"
          className="btn btn-ghost ed-design__reset"
          disabled={busy}
          onClick={() => apply({ owner_style: null }, 'Lettering, sizes and corners are back as designed')}
        >
          Back to the original lettering, sizes and corners
        </button>
      ) : null}
      <p className="ed-help">
        Layout and motion stay as LOCAH designed them, so a change here can never break your site.
      </p>
    </div>
  )
}
