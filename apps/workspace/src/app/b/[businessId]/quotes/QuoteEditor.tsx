'use client'

import { useMemo, useState } from 'react'
import { Card } from '@/components/ui'
import { SafeForm } from '@/components/SafeForm'
import { SubmitButton } from '@/components/ActionForm'
import { money, qty as fmtQty, type QuoteCharge, type QuoteItem, type QuoteRow } from './shared'

type Customer = { id: string; display_name: string; email?: string | null; phone?: string | null }
type Offering = {
  id: string
  title: string
  price_amount?: number | null
  tax_rate?: number | null
  unit_of_measure?: string | null
  status?: string | null
}

type LineDraft = {
  key: string
  offering_id: string
  title: string
  description: string
  unit_label: string
  quantity: string
  unit_price: string
  tax_rate: string
  discount_type: string
  discount_value: string
  line_kind: string
  moq: string
  lead_time_days: string
  quantity_breaks: string
  boq_section: string
  size_matrix: string
}

type ChargeDraft = {
  key: string
  label: string
  amount: string
  taxable: boolean
  tax_rate: string
}

let seq = 0
const nextKey = () => `k${++seq}`

function emptyLine(): LineDraft {
  return {
    key: nextKey(),
    offering_id: '',
    title: '',
    description: '',
    unit_label: '',
    quantity: '1',
    unit_price: '',
    tax_rate: '0',
    discount_type: '',
    discount_value: '',
    line_kind: 'item',
    moq: '',
    lead_time_days: '',
    quantity_breaks: '',
    boq_section: '',
    size_matrix: '',
  }
}

function breaksText(rows: { min_qty: string; unit_price: string }[] | undefined): string {
  return (rows || []).map((row) => `${row.min_qty}:${row.unit_price}`).join(', ')
}

function sizesText(rows: { size: string; quantity: string }[] | undefined): string {
  return (rows || []).map((row) => `${row.size}:${row.quantity}`).join(', ')
}

function parsePairs(raw: string, left: string, right: string): Record<string, string>[] {
  return raw
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .flatMap((part) => {
      const [a, b] = part.split(':').map((piece) => piece.trim())
      if (!a || !b) return []
      return [{ [left]: a, [right]: b }]
    })
}

function lineFrom(item: QuoteItem): LineDraft {
  return {
    key: nextKey(),
    offering_id: item.offering_id || '',
    title: item.title || '',
    description: item.description || '',
    unit_label: item.unit_label || '',
    quantity: fmtQty(item.quantity),
    unit_price: item.unit_price,
    tax_rate: fmtQty(item.tax_rate),
    discount_type: item.discount_type || '',
    discount_value: item.discount_value || '',
    line_kind: item.line_kind || 'item',
    moq: item.moq || '',
    lead_time_days: item.lead_time_days === null || item.lead_time_days === undefined ? '' : String(item.lead_time_days),
    quantity_breaks: breaksText(item.quantity_breaks),
    boq_section: item.boq_section || '',
    size_matrix: sizesText(item.size_matrix),
  }
}

function chargeFrom(charge: QuoteCharge): ChargeDraft {
  return {
    key: nextKey(),
    label: charge.label,
    amount: charge.amount,
    taxable: charge.taxable,
    tax_rate: fmtQty(charge.tax_rate),
  }
}

/**
 * The quote editor.
 *
 * It gathers what is being offered and hands it to the API. It deliberately
 * shows no running total: the subtotal, the discount apportionment, the tax and
 * the deposit are computed by `QuoteService`, and a second implementation here
 * would be a second answer to "what does this cost" — on the one document where
 * the business is bound by the number. What it does instead is say plainly that
 * the totals shown belong to the last save, and that saving will recompute them.
 *
 * Lines are handed over as JSON in hidden fields because there is a variable
 * number of them; the server action parses and validates before forwarding.
 */
export function QuoteEditor({
  businessId,
  quote,
  customers,
  offerings,
  action,
  submitLabel,
  cancelHref,
}: {
  businessId: string
  quote?: QuoteRow
  customers: Customer[]
  offerings: Offering[]
  action: (formData: FormData) => Promise<{ ok: true; data?: unknown } | { ok: false; message: string } | void>
  submitLabel: string
  cancelHref: string
}) {
  const [lines, setLines] = useState<LineDraft[]>(() =>
    quote?.items?.length ? quote.items.map(lineFrom) : [emptyLine()]
  )
  const [charges, setCharges] = useState<ChargeDraft[]>(() =>
    quote?.charges?.length ? quote.charges.map(chargeFrom) : []
  )
  const [dirty, setDirty] = useState(false)

  const offeringById = useMemo(
    () => new Map(offerings.map((o) => [o.id, o])),
    [offerings]
  )

  const touch = () => setDirty(true)

  function patchLine(key: string, patch: Partial<LineDraft>) {
    setLines((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)))
    touch()
  }

  /** Picking a catalogue item fills the line from it — the price stays editable,
   *  because a quote is allowed to differ from the list price. */
  function chooseOffering(key: string, offeringId: string) {
    const offering = offeringById.get(offeringId)
    patchLine(key, {
      offering_id: offeringId,
      ...(offering
        ? {
            title: '',
            unit_price:
              offering.price_amount !== null && offering.price_amount !== undefined
                ? String(offering.price_amount)
                : '',
            tax_rate: offering.tax_rate ? String(offering.tax_rate) : '0',
            unit_label: offering.unit_of_measure || '',
          }
        : {}),
    })
  }

  const itemsJson = JSON.stringify(
    lines.map((l) => ({
      offering_id: l.offering_id || null,
      title: l.offering_id ? null : l.title,
      description: l.description,
      unit_label: l.unit_label,
      quantity:
        l.line_kind === 'size_matrix'
          ? Math.max(Number(l.quantity) || 0, 1)
          : Number(l.quantity) || 0,
      unit_price: l.unit_price === '' ? null : Number(l.unit_price),
      tax_rate: Number(l.tax_rate) || 0,
      discount_type: l.discount_type || null,
      discount_value: l.discount_value === '' ? null : Number(l.discount_value),
      line_kind: l.line_kind || 'item',
      moq: l.moq === '' ? null : Number(l.moq),
      lead_time_days: l.lead_time_days === '' ? null : Number(l.lead_time_days),
      quantity_breaks: parsePairs(l.quantity_breaks, 'min_qty', 'unit_price'),
      boq_section: l.boq_section || null,
      size_matrix: parsePairs(l.size_matrix, 'size', 'quantity'),
    }))
  )

  const chargesJson = JSON.stringify(
    charges.map((c) => ({
      label: c.label,
      amount: Number(c.amount) || 0,
      taxable: c.taxable,
      tax_rate: Number(c.tax_rate) || 0,
    }))
  )

  const usable = lines.some((l) => {
    const named = Boolean(l.offering_id || l.title.trim())
    if (!named) return false
    if (l.line_kind === 'size_matrix') return l.size_matrix.trim().length > 0 || Number(l.quantity) > 0
    return Number(l.quantity) > 0
  })

  return (
    <SafeForm
      action={action}
      style={{ display: 'grid', gap: '1.5rem' }}
    >
      <input type="hidden" name="businessId" value={businessId} />
      {quote ? <input type="hidden" name="quoteId" value={quote.id} /> : null}
      {quote ? <input type="hidden" name="version" value={quote.version} /> : null}
      <input type="hidden" name="items_json" value={itemsJson} />
      <input type="hidden" name="charges_json" value={chargesJson} />
      <input type="hidden" name="currency" value={quote?.currency || 'INR'} />

      <Card style={{ display: 'grid', gap: '0.9rem' }}>
        <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Who and what</h2>
        <div style={{ display: 'grid', gap: '0.9rem', gridTemplateColumns: 'repeat(auto-fit, minmax(14rem, 1fr))' }}>
          <label style={FIELD}>
            <span style={LABEL}>Customer</span>
            <select
              name="customer_contact_id"
              defaultValue={quote?.customer_contact_id || ''}
              onChange={touch}
            >
              <option value="">No customer selected</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name}
                </option>
              ))}
            </select>
            {customers.length === 0 ? (
              <span style={HINT}>
                No customers yet. You can still write the quote and attach one later.
              </span>
            ) : null}
          </label>

          <label style={FIELD}>
            <span style={LABEL}>What this quote is for</span>
            <input
              name="title"
              defaultValue={quote?.title || ''}
              onChange={touch}
              maxLength={200}
              placeholder="e.g. Kitchen rewiring — ground floor"
            />
          </label>

          <label style={FIELD}>
            <span style={LABEL}>Valid until</span>
            <input
              type="date"
              name="valid_until"
              defaultValue={quote?.valid_until ? quote.valid_until.slice(0, 10) : ''}
              onChange={touch}
            />
            <span style={HINT}>After this date the customer can no longer accept it.</span>
          </label>
        </div>
      </Card>

      <Card style={{ display: 'grid', gap: '0.75rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '1rem', flexWrap: 'wrap' }}>
          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Lines</h2>
          <span style={HINT}>Pick from your catalogue, or write a one-off line.</span>
        </div>

        <div style={{ display: 'grid', gap: '0.85rem' }}>
          {lines.map((line, index) => (
            <div
              key={line.key}
              style={{
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius)',
                padding: '0.9rem',
                display: 'grid',
                gap: '0.7rem',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem' }}>
                <strong style={{ fontSize: '0.85rem', color: 'var(--color-muted)' }}>
                  Line {index + 1}
                </strong>
                {lines.length > 1 ? (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setLines((rows) => rows.filter((r) => r.key !== line.key))
                      touch()
                    }}
                  >
                    Remove
                  </button>
                ) : null}
              </div>

              <div style={{ display: 'grid', gap: '0.7rem', gridTemplateColumns: 'repeat(auto-fit, minmax(12rem, 1fr))' }}>
                <label style={FIELD}>
                  <span style={LABEL}>From catalogue</span>
                  <select
                    value={line.offering_id}
                    onChange={(e) => chooseOffering(line.key, e.target.value)}
                  >
                    <option value="">Write it myself</option>
                    {offerings.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.title}
                      </option>
                    ))}
                  </select>
                </label>

                {line.offering_id ? null : (
                  <label style={FIELD}>
                    <span style={LABEL}>Description</span>
                    <input
                      value={line.title}
                      onChange={(e) => patchLine(line.key, { title: e.target.value })}
                      placeholder="What is being supplied"
                      maxLength={200}
                    />
                  </label>
                )}

                <label style={FIELD}>
                  <span style={LABEL}>Quantity</span>
                  <input
                    type="number"
                    min="0.001"
                    step="0.001"
                    value={line.quantity}
                    onChange={(e) => patchLine(line.key, { quantity: e.target.value })}
                  />
                </label>

                <label style={FIELD}>
                  <span style={LABEL}>Unit price</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={line.unit_price}
                    onChange={(e) => patchLine(line.key, { unit_price: e.target.value })}
                    placeholder={line.offering_id ? 'Catalogue price' : '0.00'}
                  />
                </label>

                <label style={FIELD}>
                  <span style={LABEL}>Tax %</span>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={line.tax_rate}
                    onChange={(e) => patchLine(line.key, { tax_rate: e.target.value })}
                  />
                </label>

                <label style={FIELD}>
                  <span style={LABEL}>Line discount</span>
                  <div style={{ display: 'flex', gap: '0.4rem' }}>
                    <select
                      value={line.discount_type}
                      onChange={(e) => patchLine(line.key, { discount_type: e.target.value })}
                      style={{ flex: '0 0 7rem' }}
                    >
                      <option value="">None</option>
                      <option value="percent">%</option>
                      <option value="amount">Amount</option>
                    </select>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={line.discount_value}
                      onChange={(e) => patchLine(line.key, { discount_value: e.target.value })}
                      disabled={!line.discount_type}
                      placeholder="0"
                      style={{ minWidth: 0 }}
                    />
                  </div>
                </label>

                <label style={FIELD}>
                  <span style={LABEL}>Line kind</span>
                  <select
                    value={line.line_kind}
                    onChange={(e) => patchLine(line.key, { line_kind: e.target.value })}
                  >
                    <option value="item">Item</option>
                    <option value="boq">BOQ</option>
                    <option value="size_matrix">Size matrix</option>
                  </select>
                </label>

                <label style={FIELD}>
                  <span style={LABEL}>Minimum quantity</span>
                  <input
                    value={line.moq}
                    onChange={(e) => patchLine(line.key, { moq: e.target.value })}
                    placeholder="None"
                  />
                </label>

                <label style={FIELD}>
                  <span style={LABEL}>Lead time (days)</span>
                  <input
                    value={line.lead_time_days}
                    onChange={(e) => patchLine(line.key, { lead_time_days: e.target.value })}
                    placeholder="None"
                  />
                </label>

                <label style={FIELD}>
                  <span style={LABEL}>Quantity breaks</span>
                  <input
                    value={line.quantity_breaks}
                    onChange={(e) => patchLine(line.key, { quantity_breaks: e.target.value })}
                    placeholder="10:450, 50:400"
                  />
                </label>

                {line.line_kind === 'boq' ? (
                  <label style={FIELD}>
                    <span style={LABEL}>BOQ section</span>
                    <input
                      value={line.boq_section}
                      onChange={(e) => patchLine(line.key, { boq_section: e.target.value })}
                      placeholder="Flooring"
                    />
                  </label>
                ) : null}

                {line.line_kind === 'size_matrix' ? (
                  <label style={FIELD}>
                    <span style={LABEL}>Sizes</span>
                    <input
                      value={line.size_matrix}
                      onChange={(e) => patchLine(line.key, { size_matrix: e.target.value })}
                      placeholder="S:10, M:20, L:8"
                    />
                  </label>
                ) : null}
              </div>
            </div>
          ))}
        </div>

        <div>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setLines((rows) => [...rows, emptyLine()])
              touch()
            }}
          >
            Add a line
          </button>
        </div>
      </Card>

      <Card style={{ display: 'grid', gap: '0.75rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '1rem', flexWrap: 'wrap' }}>
          <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Extra charges</h2>
          <span style={HINT}>Delivery, installation, site visit — anything not a line item.</span>
        </div>

        {charges.length === 0 ? (
          <p style={{ color: 'var(--color-muted)', margin: 0 }}>None.</p>
        ) : (
          <div style={{ display: 'grid', gap: '0.7rem' }}>
            {charges.map((charge) => (
              <div
                key={charge.key}
                style={{
                  display: 'grid',
                  gap: '0.6rem',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(10rem, 1fr))',
                  alignItems: 'end',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius)',
                  padding: '0.75rem',
                }}
              >
                <label style={FIELD}>
                  <span style={LABEL}>Label</span>
                  <input
                    value={charge.label}
                    onChange={(e) => {
                      setCharges((rows) =>
                        rows.map((r) => (r.key === charge.key ? { ...r, label: e.target.value } : r))
                      )
                      touch()
                    }}
                    maxLength={120}
                  />
                </label>
                <label style={FIELD}>
                  <span style={LABEL}>Amount</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={charge.amount}
                    onChange={(e) => {
                      setCharges((rows) =>
                        rows.map((r) => (r.key === charge.key ? { ...r, amount: e.target.value } : r))
                      )
                      touch()
                    }}
                  />
                </label>
                <label style={FIELD}>
                  <span style={LABEL}>Tax %</span>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={charge.tax_rate}
                    disabled={!charge.taxable}
                    onChange={(e) => {
                      setCharges((rows) =>
                        rows.map((r) => (r.key === charge.key ? { ...r, tax_rate: e.target.value } : r))
                      )
                      touch()
                    }}
                  />
                </label>
                <label style={{ ...FIELD, flexDirection: 'row', alignItems: 'center', gap: '0.45rem' }}>
                  <input
                    type="checkbox"
                    checked={charge.taxable}
                    onChange={(e) => {
                      setCharges((rows) =>
                        rows.map((r) =>
                          r.key === charge.key ? { ...r, taxable: e.target.checked } : r
                        )
                      )
                      touch()
                    }}
                  />
                  <span style={LABEL}>Taxable</span>
                </label>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => {
                    setCharges((rows) => rows.filter((r) => r.key !== charge.key))
                    touch()
                  }}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        <div>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setCharges((rows) => [
                ...rows,
                { key: nextKey(), label: '', amount: '', taxable: false, tax_rate: '0' },
              ])
              touch()
            }}
          >
            Add a charge
          </button>
        </div>
      </Card>

      <Card style={{ display: 'grid', gap: '0.9rem' }}>
        <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Discount and deposit</h2>
        <div style={{ display: 'grid', gap: '0.9rem', gridTemplateColumns: 'repeat(auto-fit, minmax(13rem, 1fr))' }}>
          <label style={FIELD}>
            <span style={LABEL}>Discount on the whole quote</span>
            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <select
                name="discount_type"
                defaultValue={quote?.discount_type || ''}
                onChange={touch}
                style={{ flex: '0 0 7rem' }}
              >
                <option value="">None</option>
                <option value="percent">%</option>
                <option value="amount">Amount</option>
              </select>
              <input
                type="number"
                name="discount_value"
                min="0"
                step="0.01"
                defaultValue={quote?.discount_value || ''}
                onChange={touch}
                placeholder="0"
                style={{ minWidth: 0 }}
              />
            </div>
            <span style={HINT}>Spread across the lines when the quote is priced.</span>
          </label>

          <label style={FIELD}>
            <span style={LABEL}>Deposit to take up front</span>
            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <select
                name="deposit_type"
                defaultValue={quote?.deposit_type || ''}
                onChange={touch}
                style={{ flex: '0 0 7rem' }}
              >
                <option value="">None</option>
                <option value="percent">%</option>
                <option value="amount">Amount</option>
              </select>
              <input
                type="number"
                name="deposit_value"
                min="0"
                step="0.01"
                defaultValue={quote?.deposit_value || ''}
                onChange={touch}
                placeholder="0"
                style={{ minWidth: 0 }}
              />
            </div>
          </label>
        </div>
      </Card>

      <Card style={{ display: 'grid', gap: '0.9rem' }}>
        <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Payment plan</h2>
        <label style={FIELD}>
          <span style={LABEL}>Stages</span>
          <textarea
            name="payment_plan"
            rows={3}
            defaultValue={(quote?.payment_plan || [])
              .map((stage) =>
                [stage.label, stage.amount_type, stage.amount_value, stage.due_rule, stage.due_days ?? ''].join(' | ')
              )
              .join('\n')}
            onChange={touch}
            placeholder={'Token | percent | 20 | on_acceptance\nBalance | amount | 80000 | net_days | 15'}
          />
          <span style={HINT}>
            One stage a line: label | amount or percent | value | on_acceptance, net_days or milestone | days.
            The deposit above is the token Payments is handed when the customer accepts.
          </span>
        </label>
      </Card>

      <Card style={{ display: 'grid', gap: '0.9rem' }}>
        <h2 style={{ fontSize: '1.05rem', margin: 0 }}>Terms and notes</h2>
        <label style={FIELD}>
          <span style={LABEL}>Terms the customer sees</span>
          <textarea
            name="terms"
            rows={4}
            defaultValue={quote?.terms || ''}
            onChange={touch}
            maxLength={20000}
            placeholder="Payment terms, what is included, how long the work takes…"
          />
        </label>
        <label style={FIELD}>
          <span style={LABEL}>Notes the customer sees</span>
          <textarea name="notes" rows={2} defaultValue={quote?.notes || ''} onChange={touch} />
        </label>
        <label style={FIELD}>
          <span style={LABEL}>Internal notes</span>
          <textarea name="internal_notes" rows={2} onChange={touch} />
          <span style={HINT}>Only your team sees this. It never appears on the document.</span>
        </label>
      </Card>

      <div
        style={{
          display: 'flex',
          gap: '0.75rem',
          alignItems: 'center',
          flexWrap: 'wrap',
          position: 'sticky',
          bottom: 0,
          background: 'var(--color-background)',
          paddingBlock: '0.9rem',
          borderTop: '1px solid var(--color-border)',
        }}
      >
        <SubmitButton className="btn" disabled={!usable}>
          {submitLabel}
        </SubmitButton>
        <a href={cancelHref} className="btn btn-ghost">
          Cancel
        </a>
        {quote ? (
          <span style={{ marginLeft: 'auto', color: 'var(--color-muted)', fontSize: '0.88rem' }}>
            {dirty
              ? 'Unsaved changes — totals recalculate when you save.'
              : `Total ${money(quote.total, quote.currency)}`}
          </span>
        ) : (
          <span style={{ marginLeft: 'auto', color: 'var(--color-muted)', fontSize: '0.88rem' }}>
            Totals are calculated when you save.
          </span>
        )}
        {!usable ? (
          <span style={{ width: '100%', color: 'var(--color-muted)', fontSize: '0.85rem' }}>
            Add at least one line with a description and a quantity.
          </span>
        ) : null}
      </div>
    </SafeForm>
  )
}

const FIELD: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: '0.3rem' }
const LABEL: React.CSSProperties = { fontSize: '0.85rem', color: 'var(--color-muted)' }
const HINT: React.CSSProperties = { fontSize: '0.8rem', color: 'var(--color-muted)' }
