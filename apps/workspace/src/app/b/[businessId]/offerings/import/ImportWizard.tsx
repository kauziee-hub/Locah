'use client'

import Link from 'next/link'
import { useMemo, useState, useTransition } from 'react'
import { checkImport, commitImport, loadImport, makeImportLive, readImport } from './import-actions'
import type { CheckResult, CheckedRow, CommitResult, ImportBatch, MappedRow, RecentImport, SheetRead } from './types'

const ACCEPT = '.csv,.xlsx,.pdf,.jpg,.jpeg,.png,.webp'
const SHEET_LIMIT = 2_000_000
const DOCUMENT_LIMIT = 8_000_000
const PAGE = 200
const TEMPLATE =
  'Name,Category,Price,Description,Duration (minutes),SKU,Stock\n' +
  'Filter Coffee,Drinks,40,Strong South Indian coffee,,,\n' +
  'Haircut,Services,300,,45,,\n'

type Step = 'upload' | 'map' | 'check' | 'review'
type Filter = 'all' | 'error' | 'duplicate'

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1] ?? '')
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function isSheet(name: string): boolean {
  return /\.(csv|xlsx|tsv|txt)$/i.test(name)
}

function mapRows(sheet: SheetRead, mapping: (string | null)[], edits: Record<number, MappedRow>): MappedRow[] {
  return sheet.rows.map((row, i) => {
    const item: MappedRow = Object.fromEntries(sheet.fields.map((f) => [f.key, '']))
    mapping.forEach((field, c) => {
      if (field && row[c] && !item[field]) item[field] = row[c]
    })
    return { ...item, ...edits[i] }
  })
}

function price(value: string | null): string {
  if (value === null || value === '') return 'Price on request'
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function when(at: string | null): string {
  return at ? new Date(at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : ''
}

/** Upload → match columns → check every row → import drafts → review and make live. */
export function ImportWizard({
  businessId,
  listTitle,
  recent,
}: {
  businessId: string
  listTitle: string
  recent: RecentImport[]
}) {
  const [step, setStep] = useState<Step>('upload')
  const [pending, start] = useTransition()
  const [error, setError] = useState<string | null>(null)
  const [filename, setFilename] = useState('')
  const [pasted, setPasted] = useState('')
  const [sheet, setSheet] = useState<SheetRead | null>(null)
  const [mapping, setMapping] = useState<(string | null)[]>([])
  const [kind, setKind] = useState<string | null>(null)
  const [checked, setChecked] = useState<CheckResult | null>(null)
  const [edits, setEdits] = useState<Record<number, MappedRow>>({})
  const [dirty, setDirty] = useState(false)
  const [excluded, setExcluded] = useState<Set<number>>(new Set())
  const [duplicateChoice, setDuplicateChoice] = useState<Record<number, string>>({})
  const [filter, setFilter] = useState<Filter>('all')
  const [shown, setShown] = useState(PAGE)
  const [done, setDone] = useState<CommitResult | null>(null)
  const [batch, setBatch] = useState<ImportBatch | null>(null)
  const [goLive, setGoLive] = useState<Set<string>>(new Set())
  const [liveNote, setLiveNote] = useState<string | null>(null)
  const base = `/b/${businessId}/offerings`
  const uncertain = useMemo(() => new Set(sheet?.uncertain_rows ?? []), [sheet])
  const asRead = useMemo(() => (sheet ? mapRows(sheet, mapping, {}) : []), [sheet, mapping])
  const isDocument = sheet?.source === 'document'
  const rowLabel = (i: number) => (isDocument ? `Line ${i + 1}` : `Row ${i + 2}`)

  function reset() {
    setStep('upload')
    setSheet(null)
    setChecked(null)
    setEdits({})
    setExcluded(new Set())
    setDuplicateChoice({})
    setDone(null)
    setBatch(null)
    setError(null)
    setDirty(false)
  }

  async function runCheck(s: SheetRead, m: (string | null)[], k: string | null, e: Record<number, MappedRow>) {
    const r = await checkImport(businessId, mapRows(s, m, e), k)
    if (!r.ok) return setError(r.message)
    setChecked(r.data!)
    setKind(r.data!.default_kind)
    setDirty(false)
    return r.data!
  }

  function afterRead(data: SheetRead) {
    setSheet(data)
    setMapping(data.suggested_mapping)
    setExcluded(new Set(data.uncertain_rows ?? []))
    start(async () => {
      // A first check suggests what these items are and lists the kinds to choose from.
      const c = await runCheck(data, data.suggested_mapping, null, {})
      if (c) setStep(data.source === 'document' ? 'check' : 'map')
    })
  }

  function onFile(file: File | undefined) {
    if (!file) return
    setError(null)
    const limit = isSheet(file.name) ? SHEET_LIMIT : DOCUMENT_LIMIT
    if (file.size > limit) {
      setError(isSheet(file.name)
        ? 'That sheet is larger than 2 MB. Split it into smaller sheets and import each one.'
        : 'That file is larger than 8 MB. Use a smaller photo, or one page at a time.')
      return
    }
    setFilename(file.name)
    start(async () => {
      const r = await readImport(businessId, { filename: file.name, content_base64: await fileToBase64(file) })
      if (!r.ok) return setError(r.message)
      afterRead(r.data!)
    })
  }

  function onPaste() {
    if (!pasted.trim()) return
    setError(null)
    setFilename('Pasted menu')
    start(async () => {
      const r = await readImport(businessId, { text: pasted })
      if (!r.ok) return setError(r.message)
      afterRead(r.data!)
    })
  }

  function edit(i: number, field: string, value: string) {
    setEdits((prev) => ({ ...prev, [i]: { ...prev[i], [field]: value } }))
    setDirty(true)
  }

  const counts = useMemo(() => {
    if (!checked) return { create: 0, update: 0 }
    let create = 0
    let update = 0
    for (const r of checked.rows) {
      if (r.status === 'ready' && !excluded.has(r.index)) create += 1
      if (r.status === 'duplicate') {
        const d = duplicateChoice[r.index] ?? 'skip'
        if (d === 'create') create += 1
        if (d === 'update') update += 1
      }
    }
    return { create, update }
  }, [checked, excluded, duplicateChoice])

  function onImport() {
    if (!sheet || !checked) return
    setError(null)
    const decisions: Record<string, string> = {}
    for (const r of checked.rows) {
      if (r.status === 'duplicate') decisions[String(r.index)] = duplicateChoice[r.index] ?? 'skip'
      else if (excluded.has(r.index)) decisions[String(r.index)] = 'skip'
    }
    start(async () => {
      const r = await commitImport(businessId, {
        filename: filename || 'import', file_hash: sheet.file_hash, source: sheet.source,
        rows: mapRows(sheet, mapping, edits), decisions, default_kind: kind,
      })
      if (!r.ok) return setError(r.message)
      setDone(r.data!)
      const b = await loadImport(businessId, r.data!.id)
      if (b.ok) {
        setBatch(b.data!)
        setGoLive(new Set(b.data!.items.filter((i) => i.can_go_live).map((i) => i.id)))
      }
      setStep('review')
    })
  }

  function onMakeLive() {
    if (!batch || goLive.size === 0) return
    setError(null)
    start(async () => {
      const r = await makeImportLive(businessId, batch.id, [...goLive])
      if (!r.ok) return setError(r.message)
      const b = await loadImport(businessId, batch.id)
      if (b.ok) setBatch(b.data!)
      setGoLive(new Set())
      setLiveNote(`${r.data!.live} ${r.data!.live === 1 ? 'item is' : 'items are'} live now.`)
    })
  }

  const errorBox = error ? <p className="bos-error" role="alert">{error}</p> : null

  // ------------------------------------------------------------------ 1. upload
  if (step === 'upload') {
    return (
      <div className="bos-import">
        <section className="bos-card" aria-labelledby="imp-file">
          <h2 id="imp-file">Choose your file</h2>
          <p className="bos-hint">
            A sheet with one item per row works best — CSV or Excel (.xlsx), with a header row. A PDF or a photo of
            your menu or price list also works: LOCAH reads it and you check every line before anything is added.
          </p>
          <label className={`bos-import__drop${pending ? ' is-busy' : ''}`}>
            <input type="file" accept={ACCEPT} disabled={pending}
                   onChange={(e) => onFile(e.target.files?.[0])} />
            <strong>{pending ? (filename ? `Reading ${filename}…` : 'Reading…') : 'Choose a file'}</strong>
            <span>CSV or XLSX up to 2 MB · PDF or photo up to 8 MB</span>
          </label>
          <p className="bos-fieldhelp" style={{ marginTop: '.6rem' }}>
            Starting from scratch?{' '}
            <a href={`data:text/csv;charset=utf-8,${encodeURIComponent(TEMPLATE)}`} download="locah-import-template.csv">
              Download a template
            </a>{' '}
            — Name is the only column you must fill.
          </p>
        </section>
        <section className="bos-card" aria-labelledby="imp-paste">
          <h2 id="imp-paste">Or paste your list</h2>
          <p className="bos-hint">Copy it from a message or a document — one item per line, with its price if you have one.</p>
          <label className="bos-label" htmlFor="imp-paste-text">Your list</label>
          <textarea id="imp-paste-text" rows={6} value={pasted} disabled={pending} maxLength={20000}
                    placeholder={'Filter coffee - 40\nMasala dosa - 120'}
                    onChange={(e) => setPasted(e.target.value)} />
          <div className="bos-field__actions">
            <button type="button" className="btn" disabled={pending || !pasted.trim()} onClick={onPaste}>
              {pending && filename === 'Pasted menu' ? 'Reading…' : 'Read this list'}
            </button>
          </div>
        </section>
        {errorBox}
        {recent.length ? (
          <section className="bos-section" aria-labelledby="imp-recent">
            <h2 className="bos-section__title" id="imp-recent">Earlier imports</h2>
            <ul className="bos-mini-list">
              {recent.map((r) => (
                <li key={r.id}>
                  <span>{r.filename}</span>
                  <span className="bos-hint" style={{ margin: 0 }}>
                    {when(r.at)} · {r.created} added{r.updated ? ` · ${r.updated} updated` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    )
  }

  // ------------------------------------------------------------------ 2. match columns
  if (step === 'map' && sheet && checked) {
    const hasName = mapping.includes('name')
    return (
      <div className="bos-import">
        {sheet.previous_import ? (
          <p className="bos-import__note" role="status">
            You imported this same file on {when(sheet.previous_import.at)} ({sheet.previous_import.created} added).
            Items already in your list are found and skipped unless you choose otherwise.
          </p>
        ) : null}
        {sheet.notes.map((n) => <p key={n} className="bos-import__note">{n}</p>)}
        <section className="bos-card" aria-labelledby="imp-map">
          <h2 id="imp-map">Match your columns</h2>
          <p className="bos-hint">
            {sheet.rows.length} {sheet.rows.length === 1 ? 'row' : 'rows'} found in {filename}. LOCAH guessed what
            each column holds — change any that are wrong, or leave a column out.
          </p>
          <label className="bos-label" htmlFor="imp-kind">These are</label>
          <select id="imp-kind" value={kind ?? ''} onChange={(e) => setKind(e.target.value)}>
            {checked.kinds.map((k) => <option key={k.key} value={k.key}>{k.plural}</option>)}
          </select>
          <p className="bos-fieldhelp">A row can say otherwise in a “Kind” column.</p>
          <div className="bos-grid-wrap" style={{ marginTop: '1rem' }}>
            <table className="bos-stock-table bos-import__map">
              <thead>
                <tr><th scope="col">Column in your file</th><th scope="col">For example</th><th scope="col">Use as</th></tr>
              </thead>
              <tbody>
                {sheet.headers.map((h, c) => (
                  <tr key={`${h}-${c}`}>
                    <th scope="row">{h}</th>
                    <td className="bos-import__sample">
                      {sheet.rows.slice(0, 3).map((r) => r[c]).filter(Boolean).join(' · ') || '—'}
                    </td>
                    <td>
                      <select aria-label={`Use ${h} as`} value={mapping[c] ?? ''}
                              onChange={(e) => {
                                const v = e.target.value || null
                                // Each field comes from one column: choosing it here frees it elsewhere.
                                setMapping((m) => m.map((x, i) => (i === c ? v : x === v ? null : x)))
                              }}>
                        <option value="">Leave out</option>
                        {sheet.fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        {errorBox}
        <div className="bos-savebar">
          <button type="button" className="btn btn-primary" disabled={pending || !hasName}
                  onClick={() => {
                    setError(null)
                    start(async () => {
                      const c = await runCheck(sheet, mapping, kind, edits)
                      if (c) setStep('check')
                    })
                  }}>
            {pending ? 'Checking…' : `Check ${sheet.rows.length} ${sheet.rows.length === 1 ? 'row' : 'rows'}`}
          </button>
          <button type="button" className="btn-ghost" disabled={pending} onClick={reset}>Choose another file</button>
          {!hasName ? <p className="bos-status bos-error">Choose which column has the item names.</p> : null}
        </div>
      </div>
    )
  }

  // ------------------------------------------------------------------ 3. check every row
  if (step === 'check' && sheet && checked) {
    const rows = checked.rows.filter((r) => filter === 'all' || r.status === filter)
    const total = counts.create + counts.update
    const editable = (r: CheckedRow) => r.status === 'error' || uncertain.has(r.index)
    const value = (r: CheckedRow, field: 'name' | 'price' | 'category') =>
      edits[r.index]?.[field] ?? asRead[r.index]?.[field] ?? ''
    return (
      <div className="bos-import">
        {sheet.notes.map((n) => <p key={n} className="bos-import__note">{n}</p>)}
        {isDocument && uncertain.size ? (
          <p className="bos-import__note bos-import__note--warn">
            LOCAH wasn&apos;t sure of {uncertain.size} {uncertain.size === 1 ? 'line' : 'lines'} — they are left out
            until you check them.
          </p>
        ) : null}
        <section className="bos-card" aria-labelledby="imp-check">
          <h2 id="imp-check">Check before importing</h2>
          <div className="bos-pills" role="group" aria-label="Show rows">
            {([['all', `All ${checked.summary.total}`], ['error', `Need a fix ${checked.summary.error}`],
              ['duplicate', `Already here ${checked.summary.duplicate}`]] as const).map(([key, label]) => (
              <button key={key} type="button" aria-pressed={filter === key}
                      className={`bos-pill${filter === key ? ' is-on' : ''}`}
                      onClick={() => { setFilter(key); setShown(PAGE) }}>
                {label}
              </button>
            ))}
            {isDocument ? null : (
              <button type="button" className="bos-pill" onClick={() => setStep('map')}>Change columns</button>
            )}
          </div>
          <div className="bos-grid-wrap" style={{ marginTop: '.8rem' }}>
            <table className="bos-stock-table bos-import__rows">
              <thead>
                <tr>
                  <th scope="col"><span className="sr-only">Include</span></th>
                  <th scope="col">{isDocument ? 'Line' : 'Row'}</th>
                  <th scope="col">Name</th>
                  <th scope="col">Category</th>
                  <th scope="col">Price</th>
                  <th scope="col">What happens</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, shown).map((r) => (
                  <tr key={r.index} className={r.status === 'error' ? 'is-error' : ''}>
                    <td>
                      {r.status === 'ready' ? (
                        <input type="checkbox" aria-label={`Import ${r.values.name}`} checked={!excluded.has(r.index)}
                               onChange={(e) => setExcluded((prev) => {
                                 const next = new Set(prev)
                                 if (e.target.checked) next.delete(r.index)
                                 else next.add(r.index)
                                 return next
                               })} />
                      ) : null}
                    </td>
                    <td className="bos-import__num">{rowLabel(r.index).split(' ')[1]}</td>
                    {editable(r) ? (
                      <>
                        <td><input aria-label={`${rowLabel(r.index)} name`} value={value(r, 'name')}
                                   onChange={(e) => edit(r.index, 'name', e.target.value)} /></td>
                        <td><input aria-label={`${rowLabel(r.index)} category`} value={value(r, 'category')}
                                   onChange={(e) => edit(r.index, 'category', e.target.value)} /></td>
                        <td><input aria-label={`${rowLabel(r.index)} price`} value={value(r, 'price')} inputMode="decimal"
                                   onChange={(e) => edit(r.index, 'price', e.target.value)} /></td>
                      </>
                    ) : (
                      <>
                        <td><strong>{r.values.name}</strong>{r.values.description ? <span className="bos-import__desc">{r.values.description}</span> : null}</td>
                        <td>{r.values.category || '—'}</td>
                        <td>{price(r.values.price)}</td>
                      </>
                    )}
                    <td>
                      <RowOutcome row={r} uncertain={uncertain.has(r.index)} rowLabel={rowLabel}
                                  choice={duplicateChoice[r.index] ?? 'skip'}
                                  onChoice={(d) => setDuplicateChoice((prev) => ({ ...prev, [r.index]: d }))} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length > shown ? (
            <button type="button" className="btn-ghost" style={{ marginTop: '.6rem' }}
                    onClick={() => setShown(rows.length)}>
              Show all {rows.length}
            </button>
          ) : null}
        </section>
        {errorBox}
        <div className="bos-savebar">
          {dirty ? (
            <button type="button" className="btn btn-primary" disabled={pending}
                    onClick={() => start(async () => { await runCheck(sheet, mapping, kind, edits) })}>
              {pending ? 'Checking…' : 'Check again'}
            </button>
          ) : (
            <button type="button" className="btn btn-primary" disabled={pending || total === 0} onClick={onImport}>
              {pending ? 'Importing…' : total === 0 ? 'Nothing to import' : `Import ${total} as drafts`}
            </button>
          )}
          <button type="button" className="btn-ghost" disabled={pending} onClick={reset}>Start over</button>
          <p className="bos-status" style={{ color: 'var(--color-muted)' }}>
            {checked.summary.error
              ? `${checked.summary.error} ${checked.summary.error === 1 ? 'row needs' : 'rows need'} a fix and won't be imported until fixed. `
              : ''}
            Nothing goes live until you choose.
          </p>
        </div>
      </div>
    )
  }

  // ------------------------------------------------------------------ 4. review and make live
  if (step === 'review' && done) {
    const failed = done.rows.filter((r) => r.result === 'error')
    return (
      <div className="bos-import">
        <section className="bos-card" aria-labelledby="imp-done">
          <h2 id="imp-done">Imported as drafts</h2>
          <p className="bos-hint" role="status">
            {done.created} added{done.updated ? `, ${done.updated} updated` : ''}
            {done.skipped ? `, ${done.skipped} skipped` : ''}
            {done.errors ? `, ${done.errors} not imported` : ''}. Nobody can see them yet.
          </p>
          {failed.length ? (
            <details>
              <summary>{failed.length} {failed.length === 1 ? 'row was' : 'rows were'} not imported</summary>
              <ul className="bos-import__problems">
                {failed.map((r) => <li key={r.index}>{rowLabel(r.index)}: {(r.problems ?? []).join('; ')}</li>)}
              </ul>
              <p className="bos-fieldhelp">Fix them in your file and import it again — what was added now is skipped.</p>
            </details>
          ) : null}
        </section>
        {batch && batch.items.length ? (
          <section className="bos-card" aria-labelledby="imp-live">
            <h2 id="imp-live">Choose what goes live</h2>
            <p className="bos-hint">Live items appear on your website and can be ordered or booked.</p>
            <ul className="bos-steps">
              {batch.items.map((i) => (
                <li key={i.id}>
                  <label className="bos-import__live">
                    <input type="checkbox" disabled={!i.can_go_live || pending} checked={goLive.has(i.id)}
                           onChange={(e) => setGoLive((prev) => {
                             const next = new Set(prev)
                             if (e.target.checked) next.add(i.id)
                             else next.delete(i.id)
                             return next
                           })} />
                    <span>
                      <strong>{i.title}</strong>
                      <span className="bos-import__meta">
                        {i.kind_label} · {i.price_type === 'enquiry' ? 'Price on request' : price(i.price_amount === null ? null : String(i.price_amount))}
                        {i.problem ? <> · <Link href={`${base}/${i.id}`}>{i.problem}</Link></> : null}
                      </span>
                    </span>
                  </label>
                  <span className={`bos-state${i.status === 'active' ? ' is-ready' : ' is-off'}`}>
                    {i.status === 'active' ? 'Live' : i.status === 'draft' ? 'Draft' : 'Archived'}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        {errorBox}
        <div className="bos-savebar">
          {batch && batch.items.some((i) => i.can_go_live) ? (
            <button type="button" className="btn btn-primary" disabled={pending || goLive.size === 0} onClick={onMakeLive}>
              {pending ? 'Making live…' : goLive.size ? `Make ${goLive.size} live` : 'Tick what should go live'}
            </button>
          ) : null}
          <Link className="btn-ghost" href={base}>Back to {listTitle}</Link>
          <button type="button" className="btn-ghost" disabled={pending} onClick={reset}>Import another file</button>
          {liveNote ? <p className="bos-status" role="status">{liveNote}</p> : null}
        </div>
      </div>
    )
  }

  return null
}

function RowOutcome({
  row,
  uncertain,
  rowLabel,
  choice,
  onChoice,
}: {
  row: CheckedRow
  uncertain: boolean
  rowLabel: (i: number) => string
  choice: string
  onChoice: (d: string) => void
}) {
  const notes = row.notes.length ? <span className="bos-import__desc">{row.notes.join(' ')}</span> : null
  if (row.status === 'error') {
    return (
      <>
        <span className="bos-tag bos-tag--bad">Needs a fix</span>
        <span className="bos-import__desc bos-error">{row.problems.join('; ')}</span>
      </>
    )
  }
  if (row.status === 'duplicate') {
    const same = row.duplicate_of
    return (
      <>
        <span className="bos-tag bos-tag--warn">
          {same ? `Already here${same.status === 'active' ? ' (live)' : ' (draft)'}` : `Repeats ${rowLabel(row.repeats_row ?? 0).toLowerCase()}`}
        </span>
        <select aria-label={`What to do with ${row.values.name}`} value={choice} onChange={(e) => onChoice(e.target.value)}>
          <option value="skip">Skip it</option>
          {same && same.status === 'draft' ? <option value="update">Update the draft</option> : null}
          <option value="create">Add it anyway</option>
        </select>
        {notes}
      </>
    )
  }
  return (
    <>
      {uncertain ? <span className="bos-tag bos-tag--warn">Check this line</span> : <span className="bos-tag bos-tag--good">Ready</span>}
      {notes}
    </>
  )
}
