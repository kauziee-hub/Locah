'use client'

import { useRouter } from 'next/navigation'
import { useState, useTransition } from 'react'
import { makeVariants, saveOffering } from './offering-actions'
import type { Axis, Kind, KindField, Offering, OptionGroup, Pack, Preorder, PriceFormula, RateLite, Variant } from './types'
import { inr } from './types'

type Attr = Record<string, string | boolean>

function toForm(f: KindField, v: unknown): string | boolean {
  if (f.type === 'bool') return Boolean(v)
  if (f.type === 'list') return Array.isArray(v) ? v.join('\n') : String(v ?? '')
  return v === undefined || v === null ? '' : String(v)
}

/**
 * One editor for every kind of offering (Capability Universe §6.3). The kind
 * decides the questions: pack sizes for goods sold by weight, choices and
 * add-ons for menu items, options for variants, and each kind's own details.
 * The server checks everything again and prices every order itself.
 */
export function OfferingEditor({
  businessId,
  kind,
  offering,
  variants,
  rates = [],
}: {
  businessId: string
  kind: Kind
  offering: Offering | null
  variants: Variant[]
  /** The owner's rate board, for items priced from a daily rate (OK-15). */
  rates?: RateLite[]
}) {
  const router = useRouter()
  const isNew = offering === null
  const [title, setTitle] = useState(offering?.title ?? '')
  const [description, setDescription] = useState(offering?.description ?? '')
  const [status, setStatus] = useState(offering?.status === 'active' ? 'active' : 'draft')
  const defaultPriceType = kind.flow === 'enquiry' ? 'starting_from' : 'fixed'
  const [priceType, setPriceType] = useState(offering?.price_formula ? 'rate' : offering?.price_type ?? defaultPriceType)
  const [formula, setFormula] = useState<FormulaForm>(() => toFormula(offering?.price_formula ?? null, rates))
  const canRate = kind.flow === 'cart' && !kind.packs
  const [price, setPrice] = useState(offering?.price_amount != null ? String(offering.price_amount) : '')
  const [taxCode, setTaxCode] = useState(offering?.hsn_sac ?? '')
  const [taxRate, setTaxRate] = useState(offering?.tax_rate != null ? String(offering.tax_rate) : '')
  const [sku, setSku] = useState(offering?.sku ?? '')
  const [barcode, setBarcode] = useState(offering?.barcode ?? '')
  const [attrs, setAttrs] = useState<Attr>(() =>
    Object.fromEntries(kind.fields.map((f) => [f.key, toForm(f, offering?.attributes?.[f.key] ?? (f.key === 'price_per' ? 'kg' : undefined))])),
  )
  const [packs, setPacks] = useState<Pack[]>(offering?.sell_units ?? (kind.packs ? [{ label: '500 g', qty: 500 }, { label: '1 kg', qty: 1000 }] : []))
  const [groups, setGroups] = useState<OptionGroup[]>(offering?.option_groups ?? [])
  const [axes, setAxes] = useState<Axis[]>(offering?.variant_options ?? [])
  const [ahead, setAhead] = useState<AheadForm>(() => toAhead(offering?.preorder ?? null))
  const [track, setTrack] = useState(offering?.track_inventory ?? kind.packs)
  const gramStock = kind.packs || offering?.stock_unit === 'g' || offering?.stock_unit === 'ml'
  const [reorder, setReorder] = useState(
    offering?.low_stock_threshold != null ? String(gramStock ? offering.low_stock_threshold / 1000 : offering.low_stock_threshold) : '',
  )
  const [pending, start] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  const per = String(attrs.price_per || 'kg')
  const combos = axes.reduce((n, a) => n * Math.max(a.values.length, 1), axes.length ? 1 : 0)

  const body = () => {
    const attributes: Record<string, unknown> = {}
    for (const f of kind.fields) {
      const v = attrs[f.key]
      if (v === '' || v === undefined || v === false) continue
      attributes[f.key] = f.type === 'list' ? String(v).split('\n').map((s) => s.trim()).filter(Boolean) : v
    }
    const payload: Record<string, unknown> = {
      title: title.trim(),
      description: description.trim() || null,
      status,
      // "Live — shown to customers" means shown: an item made live is public
      // (drafts from the conversation used to stay private and invisible).
      ...(status === 'active' ? { visibility: 'public' } : {}),
      attributes,
      hsn_sac: taxCode.trim() || null,
      tax_rate: taxRate === '' ? null : Number(taxRate),
    }
    if (priceType === 'rate') {
      payload.price_formula = fromFormula(formula)
    } else if (kind.flow !== 'give') {
      payload.price_type = kind.packs ? 'fixed' : priceType
      payload.price_amount = price === '' || priceType === 'free' || priceType === 'enquiry' ? null : Number(price)
      if (offering?.price_formula) payload.price_formula = null
    }
    if (kind.tax_code === 'HSN') {
      payload.sku = sku.trim() || null
      payload.barcode = barcode.trim() || null
    }
    if (kind.packs) payload.sell_units = packs
    if (kind.options) payload.option_groups = groups
    if (kind.flow === 'cart') payload.preorder = fromAhead(ahead)
    if (kind.variants) payload.variant_options = axes.filter((a) => a.name.trim() && a.values.length)
    if (kind.stockable) {
      payload.track_inventory = track
      payload.low_stock_threshold = reorder === '' ? null : Math.round(Number(reorder) * (gramStock ? 1000 : 1))
    }
    if (isNew) payload.offering_type = kind.key
    else payload.version = offering?.version
    return payload
  }

  const save = () => {
    setError(null)
    setSaved(null)
    if (!title.trim()) return setError('Give it a name.')
    if (priceType === 'rate' && !(Number(formula.quantity) > 0)) return setError('Enter how much of the rate one piece uses, for example its weight.')
    start(async () => {
      const r = await saveOffering(businessId, offering?.id ?? null, body())
      if (!r.ok) return setError(r.message)
      if (isNew && r.data?.id) {
        router.push(`/b/${businessId}/offerings/${r.data.id}?saved=1`)
      } else {
        setSaved(status === 'active' ? 'Saved. It is live.' : 'Saved as a draft.')
        router.refresh()
      }
    })
  }

  return (
    <div className="bos-works bos-offering">
      <section className="bos-card" aria-labelledby="basics-h">
        <h2 id="basics-h">Basics</h2>
        <div className="bos-form-grid">
          <label>
            <span className="bos-label">Name</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} />
          </label>
          {kind.tax_code === 'HSN' ? (
            <>
              <label>
                <span className="bos-label">Your code (SKU)</span>
                <input value={sku} onChange={(e) => setSku(e.target.value)} maxLength={64} />
              </label>
              <label>
                <span className="bos-label">Barcode</span>
                <input value={barcode} onChange={(e) => setBarcode(e.target.value)} inputMode="numeric" maxLength={64} />
              </label>
            </>
          ) : null}
        </div>
        <label className="bos-offering__desc">
          <span className="bos-label">Description</span>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} maxLength={5000} />
        </label>
      </section>

      {kind.fields.length ? (
        <section className="bos-card" aria-labelledby="details-h">
          <h2 id="details-h">{kind.label} details</h2>
          <div className="bos-form-grid">
            {kind.fields.map((f) => (
              <FieldInput key={f.key} field={f} value={attrs[f.key]} onChange={(v) => setAttrs((a) => ({ ...a, [f.key]: v }))} />
            ))}
          </div>
        </section>
      ) : null}

      {kind.flow !== 'give' ? (
        <section className="bos-card" aria-labelledby="price-h">
          <h2 id="price-h">Price</h2>
          {!kind.packs ? (
            <fieldset className="bos-choices" style={{ border: 0, padding: 0, margin: '0 0 .8rem' }}>
              <legend className="sr-only">How it is priced</legend>
              {[
                ['fixed', 'Fixed price'],
                ...(canRate && (rates.length || priceType === 'rate') ? [['rate', 'From a rate']] : []),
                ['starting_from', 'Starts from'],
                ['free', 'Free'],
                ['enquiry', 'Ask for price'],
              ].map(([k, label]) => (
                <label key={k} className="bos-choice">
                  <input type="radio" name="price_type" checked={priceType === k} onChange={() => setPriceType(k)} />
                  {label}
                </label>
              ))}
            </fieldset>
          ) : null}
          {priceType === 'rate' ? (
            <FormulaEditor form={formula} setForm={setFormula} rates={rates} current={offering?.price_formula ?? null} />
          ) : canRate && kind.tax_code === 'HSN' && !rates.length ? (
            <p className="bos-hint">
              Priced by weight from a rate you enter each day, like gold or silver?{' '}
              <a href={`/b/${businessId}/offerings/rates`}>Add your rates</a> first.
            </p>
          ) : null}
          <div className="bos-form-grid">
            {priceType !== 'free' && priceType !== 'enquiry' && priceType !== 'rate' ? (
              <label>
                <span className="bos-label">{kind.packs ? `Price per ${per} (₹)` : 'Price (₹)'}</span>
                <input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
              </label>
            ) : null}
            <label>
              <span className="bos-label">{kind.tax_code} code</span>
              <input value={taxCode} onChange={(e) => setTaxCode(e.target.value)} inputMode="numeric" maxLength={8}
                placeholder={kind.tax_code === 'HSN' ? '4, 6 or 8 digits' : '6 digits, starts with 99'} />
            </label>
            <label>
              <span className="bos-label">GST rate (%)</span>
              <input inputMode="decimal" value={taxRate} onChange={(e) => setTaxRate(e.target.value)} placeholder="As advised by your CA" />
            </label>
          </div>
        </section>
      ) : null}

      {kind.packs ? (
        <PacksEditor packs={packs} setPacks={setPacks} unit={per === 'litre' ? 'ml' : 'g'} price={price === '' ? null : Number(price)} />
      ) : null}
      {kind.options ? <GroupsEditor groups={groups} setGroups={setGroups} what={kind.key === 'menu_item' ? 'choices and add-ons' : 'choices such as the cut'} /> : null}
      {kind.flow === 'cart' ? <AheadEditor form={ahead} setForm={setAhead} /> : null}
      {kind.variants ? (
        <section className="bos-card" aria-labelledby="var-h">
          <h2 id="var-h">Sizes, colours and other options</h2>
          <p className="bos-hint">Add an option and its values. Each combination becomes a variant with its own stock.</p>
          {axes.map((a, i) => (
            <div key={i} className="bos-rowedit">
              <input aria-label="Option name" placeholder="Size" value={a.name}
                onChange={(e) => setAxes((xs) => xs.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <input aria-label="Values" placeholder="S, M, L" value={a.values.join(', ')}
                onChange={(e) => setAxes((xs) => xs.map((x, j) => (j === i ? { ...x, values: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) } : x)))} />
              <button type="button" className="btn-quiet" onClick={() => setAxes((xs) => xs.filter((_, j) => j !== i))}>Remove</button>
            </div>
          ))}
          {axes.length < 3 ? (
            <button type="button" className="btn-ghost" onClick={() => setAxes((xs) => [...xs, { name: '', values: [] }])}>Add an option</button>
          ) : null}
          {!isNew && offering?.variant_options?.length ? (
            <VariantsPanel businessId={businessId} offeringId={offering.id} variants={variants} combos={combos} />
          ) : null}
        </section>
      ) : null}

      {kind.stockable ? (
        <section className="bos-card" aria-labelledby="stock-h">
          <h2 id="stock-h">Stock</h2>
          <label className="bos-toggle">
            <input type="checkbox" checked={track} onChange={(e) => setTrack(e.target.checked)} />
            <span className="bos-toggle__track" aria-hidden />
            <span>Keep count of stock{gramStock ? ` (counted in ${per === 'litre' ? 'millilitres' : 'grams'})` : ''}</span>
          </label>
          {track ? (
            <label style={{ display: 'block', marginTop: '.6rem', maxWidth: 260 }}>
              <span className="bos-label">Tell me when stock falls to{gramStock ? ` (${per === 'litre' ? 'litres' : 'kg'})` : ''}</span>
              <input inputMode="decimal" value={reorder} onChange={(e) => setReorder(e.target.value)} />
            </label>
          ) : null}
        </section>
      ) : null}

      <div className="bos-savebar">
        <label className="bos-toggle">
          <input type="checkbox" checked={status === 'active'} onChange={(e) => setStatus(e.target.checked ? 'active' : 'draft')} />
          <span className="bos-toggle__track" aria-hidden />
          <span>{status === 'active' ? 'Live — shown to customers' : 'Draft — only you can see it'}</span>
        </label>
        <button type="button" onClick={save} disabled={pending}>{pending ? 'Saving…' : isNew ? 'Add' : 'Save'}</button>
        <p className={`bos-status${error ? ' bos-error' : ''}`} role="status" aria-live="polite">{error ?? saved ?? ''}</p>
      </div>
    </div>
  )
}

function FieldInput({ field: f, value, onChange }: { field: KindField; value: string | boolean | undefined; onChange: (v: string | boolean) => void }) {
  const label = `${f.label}${f.unit ? ` (${f.unit})` : ''}${f.required ? '' : ' — optional'}`
  const id = `f-${f.key}`
  if (f.type === 'bool') {
    return (
      <label className="bos-toggle">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <span className="bos-toggle__track" aria-hidden />
        <span>{f.label}</span>
      </label>
    )
  }
  return (
    <label htmlFor={id} className={f.type === 'list' || f.type === 'long_text' ? 'bos-form-wide' : ''}>
      <span className="bos-label">{label}</span>
      {f.type === 'choice' ? (
        <select id={id} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
          <option value="">{f.required ? 'Choose…' : 'Not set'}</option>
          {f.choices.map((c) => <option key={c}>{c}</option>)}
        </select>
      ) : f.type === 'list' || f.type === 'long_text' ? (
        <textarea id={id} rows={3} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input
          id={id}
          type={f.type === 'date' ? 'date' : f.type === 'time' ? 'time' : 'text'}
          inputMode={f.type === 'int' || f.type === 'year' || f.type === 'money' ? 'numeric' : undefined}
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {f.help ? <small className="bos-fieldhelp">{f.help}</small> : null}
    </label>
  )
}

function PacksEditor({ packs, setPacks, unit, price }: { packs: Pack[]; setPacks: (p: Pack[]) => void; unit: string; price: number | null }) {
  const quick = unit === 'ml' ? [[250, '250 ml'], [500, '500 ml'], [1000, '1 litre']] : [[250, '250 g'], [500, '500 g'], [1000, '1 kg']]
  return (
    <section className="bos-card" aria-labelledby="packs-h">
      <h2 id="packs-h">Pack sizes</h2>
      <p className="bos-hint">Customers pick a pack; the price follows from your price per {unit === 'ml' ? 'litre' : 'kg'}.</p>
      {packs.map((p, i) => (
        <div key={i} className="bos-rowedit">
          <input aria-label="Pack name" value={p.label} onChange={(e) => setPacks(packs.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
          <label className="bos-rowedit__unit">
            <input aria-label={`Weight in ${unit}`} inputMode="numeric" value={String(p.qty)}
              onChange={(e) => setPacks(packs.map((x, j) => (j === i ? { ...x, qty: Number(e.target.value.replace(/\D/g, '')) || 0 } : x)))} />
            <span>{unit}</span>
          </label>
          <span className="bos-rowedit__price">{price !== null ? inr(Math.round(price * p.qty / 10) / 100) : ''}</span>
          <button type="button" className="btn-quiet" onClick={() => setPacks(packs.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <div className="bos-choices" style={{ marginTop: '.5rem' }}>
        {quick.filter(([, l]) => !packs.some((p) => p.label === l)).map(([q, l]) => (
          <button key={String(l)} type="button" className="btn-ghost" onClick={() => setPacks([...packs, { label: String(l), qty: Number(q) }])}>+ {l}</button>
        ))}
        <button type="button" className="btn-ghost" onClick={() => setPacks([...packs, { label: '', qty: 0 }])}>+ Other size</button>
      </div>
    </section>
  )
}

function GroupsEditor({ groups, setGroups, what }: { groups: OptionGroup[]; setGroups: (g: OptionGroup[]) => void; what: string }) {
  const update = (i: number, g: Partial<OptionGroup>) => setGroups(groups.map((x, j) => (j === i ? { ...x, ...g } : x)))
  return (
    <section className="bos-card" aria-labelledby="groups-h">
      <h2 id="groups-h">Choices</h2>
      <p className="bos-hint">Add {what}. A choice can add to the price.</p>
      {groups.map((g, i) => g.text ? (
        <fieldset key={i} className="bos-group">
          <legend className="sr-only">Text box {i + 1}</legend>
          <div className="bos-rowedit">
            <input aria-label="What the customer writes" placeholder="Message on the cake" value={g.name} onChange={(e) => update(i, { name: e.target.value })} />
            <label className="bos-toggle">
              <input type="checkbox" checked={g.required} onChange={(e) => update(i, { required: e.target.checked })} />
              <span className="bos-toggle__track" aria-hidden />
              <span>Must fill in</span>
            </label>
            <label className="bos-rowedit__unit">
              <span>Up to</span>
              <input aria-label="Most letters" inputMode="numeric" value={String(g.max_length ?? 40)}
                onChange={(e) => update(i, { max_length: Math.max(1, Math.min(200, Number(e.target.value.replace(/\D/g, '')) || 1)) })} />
              <span>letters</span>
            </label>
            <button type="button" className="btn-quiet" onClick={() => setGroups(groups.filter((_, j) => j !== i))}>Remove</button>
          </div>
        </fieldset>
      ) : (
        <fieldset key={i} className="bos-group">
          <legend className="sr-only">Choice group {i + 1}</legend>
          <div className="bos-rowedit">
            <input aria-label="Group name" placeholder="Size, Cut, Add-ons…" value={g.name} onChange={(e) => update(i, { name: e.target.value })} />
            <label className="bos-toggle">
              <input type="checkbox" checked={g.required} onChange={(e) => update(i, { required: e.target.checked })} />
              <span className="bos-toggle__track" aria-hidden />
              <span>Must choose</span>
            </label>
            <label className="bos-rowedit__unit">
              <span>Up to</span>
              <input aria-label="How many can be picked" inputMode="numeric" value={String(g.max)}
                onChange={(e) => update(i, { max: Math.max(1, Number(e.target.value.replace(/\D/g, '')) || 1) })} />
            </label>
            <button type="button" className="btn-quiet" onClick={() => setGroups(groups.filter((_, j) => j !== i))}>Remove group</button>
          </div>
          {g.choices.map((c, ci) => (
            <div key={ci} className="bos-rowedit bos-rowedit--choice">
              <input aria-label="Choice" value={c.label}
                onChange={(e) => update(i, { choices: g.choices.map((x, j) => (j === ci ? { ...x, label: e.target.value } : x)) })} />
              <label className="bos-rowedit__unit">
                <span>+ ₹</span>
                <input aria-label="Adds to price" inputMode="decimal" value={String(c.price_delta)}
                  onChange={(e) => update(i, { choices: g.choices.map((x, j) => (j === ci ? { ...x, price_delta: e.target.value } : x)) })} />
              </label>
              <button type="button" className="btn-quiet" onClick={() => update(i, { choices: g.choices.filter((_, j) => j !== ci) })}>Remove</button>
            </div>
          ))}
          <button type="button" className="btn-quiet" onClick={() => update(i, { choices: [...g.choices, { label: '', price_delta: 0 }] })}>+ Add a choice</button>
        </fieldset>
      ))}
      <div className="bos-choices">
        <button type="button" className="btn-ghost" onClick={() => setGroups([...groups, { name: '', required: false, max: 1, choices: [{ label: '', price_delta: 0 }] }])}>
          Add a group of choices
        </button>
        <button type="button" className="btn-ghost" onClick={() => setGroups([...groups, { name: '', required: false, max: 1, choices: [], text: true, max_length: 40 }])}>
          Add a box the customer writes in
        </button>
      </div>
    </section>
  )
}

function VariantsPanel({ businessId, offeringId, variants, combos }: { businessId: string; offeringId: string; variants: Variant[]; combos: number }) {
  const [pending, start] = useTransition()
  const [msg, setMsg] = useState<string | null>(null)
  const missing = Math.max(combos - variants.length, 0)
  return (
    <div className="bos-variants">
      <p className="bos-hint">
        {variants.length} variant{variants.length === 1 ? '' : 's'} of {combos} combinations.
      </p>
      {variants.length ? (
        <ul className="bos-pills">{variants.map((v) => <li key={v.id} className="bos-pill">{v.name}</li>)}</ul>
      ) : null}
      {missing > 0 ? (
        <button type="button" disabled={pending} onClick={() => start(async () => {
          const r = await makeVariants(businessId, offeringId)
          setMsg(r.ok ? 'Variants made. Set stock for each on the Stock page.' : r.message)
        })}>
          {pending ? 'Making…' : `Make the ${missing} missing variant${missing === 1 ? '' : 's'}`}
        </button>
      ) : null}
      {msg ? <p className="bos-status" role="status">{msg}</p> : null}
    </div>
  )
}

type AheadForm = {
  mode: '' | 'required' | 'optional'
  lead: string
  leadUnit: 'hours' | 'days'
  cutoff: string
  times: string
  maxDays: string
  limit: string
  advanceType: '' | 'percent' | 'fixed'
  advance: string
  cancel: string
  orderUntil: string
  readyFrom: string
  readyUntil: string
}

function toAhead(p: Preorder | null): AheadForm {
  const days = p && p.lead_hours >= 24 && p.lead_hours % 24 === 0
  return {
    mode: p?.mode ?? '',
    lead: p ? String(days ? p.lead_hours / 24 : p.lead_hours) : '1',
    leadUnit: !p || days ? 'days' : 'hours',
    cutoff: p?.cutoff ?? '',
    times: (p?.ready_times ?? ['17:00']).join(', '),
    maxDays: String(p?.max_days ?? 30),
    limit: p?.daily_limit ? String(p.daily_limit) : '',
    advanceType: p?.advance?.type ?? '',
    advance: p?.advance ? String(Number(p.advance.value)) : '',
    cancel: p?.cancel_hours != null ? String(p.cancel_hours) : '',
    orderUntil: p?.window?.order_until ?? '',
    readyFrom: p?.window?.ready_from ?? '',
    readyUntil: p?.window?.ready_until ?? '',
  }
}

function fromAhead(f: AheadForm): Record<string, unknown> | null {
  if (!f.mode) return null
  const lead = Number(f.lead || 0)
  return {
    mode: f.mode,
    lead_hours: Math.round(f.leadUnit === 'days' ? lead * 24 : lead),
    cutoff: f.cutoff || null,
    ready_times: f.times.split(',').map((t) => t.trim()).filter(Boolean),
    max_days: Number(f.maxDays || 30),
    daily_limit: f.limit ? Number(f.limit) : null,
    advance: f.advanceType && f.advance ? { type: f.advanceType, value: Number(f.advance) } : null,
    cancel_hours: f.cancel === '' ? null : Number(f.cancel),
    window: { order_until: f.orderUntil || null, ready_from: f.readyFrom || null, ready_until: f.readyUntil || null },
  }
}

/** Ordering ahead (MD §21.1 bakeries and home kitchens; Founder: Orders — pre-orders). */
function AheadEditor({ form, setForm }: { form: AheadForm; setForm: (f: AheadForm) => void }) {
  const set = (k: keyof AheadForm, v: string) => setForm({ ...form, [k]: v })
  return (
    <section className="bos-card" aria-labelledby="ahead-h">
      <h2 id="ahead-h">Order ahead</h2>
      <p className="bos-hint">For cakes, festival boxes and anything made for a day. Customers pick the day on your website and WhatsApp; LOCAH checks the notice and your limits.</p>
      <fieldset className="bos-choices" style={{ border: 0, padding: 0, margin: '0 0 .8rem' }}>
        <legend className="sr-only">Does it need a day?</legend>
        {([['', 'Ready now — no day needed'], ['required', 'Made to order — needs a day'], ['optional', 'Customers may choose a day']] as const).map(([k, label]) => (
          <label key={k} className="bos-choice">
            <input type="radio" name="ahead_mode" checked={form.mode === k} onChange={() => set('mode', k)} />
            {label}
          </label>
        ))}
      </fieldset>
      {form.mode ? (
        <div className="bos-form-grid">
          <label>
            <span className="bos-label">Notice needed</span>
            <span className="bos-rowedit__unit">
              <input aria-label="Notice needed" inputMode="numeric" value={form.lead} onChange={(e) => set('lead', e.target.value.replace(/[^\d]/g, ''))} />
              <select aria-label="Notice unit" value={form.leadUnit} onChange={(e) => set('leadUnit', e.target.value)}>
                <option value="hours">hours</option>
                <option value="days">days</option>
              </select>
            </span>
          </label>
          <label>
            <span className="bos-label">Order by (for the next day)</span>
            <input type="time" aria-label="Order by" value={form.cutoff} onChange={(e) => set('cutoff', e.target.value)} />
          </label>
          <label>
            <span className="bos-label">Ready at (times customers can pick)</span>
            <input aria-label="Ready at" value={form.times} onChange={(e) => set('times', e.target.value)} placeholder="11:00, 17:00" />
          </label>
          <label>
            <span className="bos-label">How many you can make a day</span>
            <input aria-label="How many a day" inputMode="numeric" value={form.limit} onChange={(e) => set('limit', e.target.value.replace(/[^\d]/g, ''))} placeholder="No limit" />
          </label>
          <label>
            <span className="bos-label">Advance</span>
            <span className="bos-rowedit__unit">
              <select aria-label="Advance type" value={form.advanceType} onChange={(e) => set('advanceType', e.target.value)}>
                <option value="">No advance</option>
                <option value="percent">% of the price</option>
                <option value="fixed">₹ per piece</option>
              </select>
              {form.advanceType ? (
                <input aria-label="Advance amount" inputMode="decimal" value={form.advance} onChange={(e) => set('advance', e.target.value.replace(/[^\d.]/g, ''))} />
              ) : null}
            </span>
          </label>
          <label>
            <span className="bos-label">Customers can cancel until (hours before)</span>
            <input aria-label="Cancel until" inputMode="numeric" value={form.cancel} onChange={(e) => set('cancel', e.target.value.replace(/[^\d]/g, ''))} placeholder="Ask you" />
          </label>
          <label>
            <span className="bos-label">Take orders up to (days ahead)</span>
            <input aria-label="Days ahead" inputMode="numeric" value={form.maxDays} onChange={(e) => set('maxDays', e.target.value.replace(/[^\d]/g, ''))} />
          </label>
          <details className="bos-offering__window">
            <summary>Festival or season window</summary>
            <div className="bos-form-grid">
              <label><span className="bos-label">Orders close on</span><input type="date" aria-label="Orders close on" value={form.orderUntil} onChange={(e) => set('orderUntil', e.target.value)} /></label>
              <label><span className="bos-label">Ready from</span><input type="date" aria-label="Ready from" value={form.readyFrom} onChange={(e) => set('readyFrom', e.target.value)} /></label>
              <label><span className="bos-label">Ready until</span><input type="date" aria-label="Ready until" value={form.readyUntil} onChange={(e) => set('readyUntil', e.target.value)} /></label>
            </div>
          </details>
        </div>
      ) : null}
    </section>
  )
}

type FormulaForm = {
  rate_key: string
  quantity: string
  making: 'none' | 'percent' | 'per_unit' | 'flat'
  making_value: string
  extra: string
  extra_label: string
}

function toFormula(f: PriceFormula | null, rates: RateLite[]): FormulaForm {
  return {
    rate_key: f?.rate_key ?? rates[0]?.key ?? '',
    quantity: f ? String(Number(f.quantity)) : '',
    making: f?.making?.type ?? 'none',
    making_value: f?.making ? String(Number(f.making.value)) : '',
    extra: f && Number(f.extra) ? String(Number(f.extra)) : '',
    extra_label: f?.extra_label ?? '',
  }
}

function fromFormula(f: FormulaForm): Record<string, unknown> {
  return {
    rate_key: f.rate_key,
    quantity: f.quantity,
    making: f.making === 'none' ? null : { type: f.making, value: f.making_value || '0' },
    extra: f.extra || '0',
    extra_label: f.extra_label.trim() || null,
  }
}

/** A preview only: the server works out the price from the rate board and keeps the working. */
function preview(f: FormulaForm, rate: RateLite | undefined): number | null {
  const q = Number(f.quantity)
  if (!rate || rate.value === null || !(q > 0)) return null
  const base = rate.value * q
  const m = Number(f.making_value) || 0
  const making = f.making === 'percent' ? (base * m) / 100 : f.making === 'per_unit' ? m * q : f.making === 'flat' ? m : 0
  return Math.round(base + making + (Number(f.extra) || 0))
}

function FormulaEditor({ form, setForm, rates, current }: {
  form: FormulaForm
  setForm: (f: FormulaForm) => void
  rates: RateLite[]
  current: PriceFormula | null
}) {
  const rate = rates.find((r) => r.key === form.rate_key)
  const unit = rate?.unit_label ?? 'g'
  const set = (k: keyof FormulaForm, v: string) => setForm({ ...form, [k]: v })
  const est = preview(form, rate)
  return (
    <div className="bos-formula">
      <div className="bos-form-grid">
        <label>
          <span className="bos-label">Rate</span>
          <select name="formula-rate" value={form.rate_key} onChange={(e) => set('rate_key', e.target.value)}>
            {rates.map((r) => (
              <option key={r.key} value={r.key}>{r.label}</option>
            ))}
          </select>
        </label>
        <label>
          <span className="bos-label">{unit === 'g' ? 'Weight (g)' : `Quantity (${unit})`}</span>
          <input name="formula-quantity" inputMode="decimal" value={form.quantity} onChange={(e) => set('quantity', e.target.value)} placeholder="10.000" />
        </label>
        <label>
          <span className="bos-label">Making charge</span>
          <select name="formula-making" value={form.making} onChange={(e) => set('making', e.target.value)}>
            <option value="none">None</option>
            <option value="percent">% of the metal value</option>
            <option value="per_unit">₹ per {unit}</option>
            <option value="flat">₹ for the piece</option>
          </select>
        </label>
        {form.making !== 'none' ? (
          <label>
            <span className="bos-label">{form.making === 'percent' ? 'Making (%)' : 'Making (₹)'}</span>
            <input name="formula-making-value" inputMode="decimal" value={form.making_value} onChange={(e) => set('making_value', e.target.value)} />
          </label>
        ) : null}
        <label>
          <span className="bos-label">Other charges (₹) — optional</span>
          <input name="formula-extra" inputMode="decimal" value={form.extra} onChange={(e) => set('extra', e.target.value)} />
        </label>
        <label>
          <span className="bos-label">Called — optional</span>
          <input name="formula-extra-label" value={form.extra_label} onChange={(e) => set('extra_label', e.target.value)} maxLength={40} placeholder="Stones" />
        </label>
      </div>
      <p className="bos-hint bos-formula__words" role="status" aria-live="polite">
        {rate?.value === null || !rate
          ? 'This rate has no value yet — the item cannot be sold until you enter today’s rate.'
          : est !== null
            ? `At today’s rate: ${inr(est)}. GST is added on the bill from the item’s HSN and rate.`
            : 'Enter the weight to see today’s price.'}
        {current?.last_words ? ` Now: ${current.last_words}.` : ''}
      </p>
    </div>
  )
}
