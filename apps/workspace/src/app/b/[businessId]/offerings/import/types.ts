export type ImportField = { key: string; label: string }

export type SheetRead = {
  source: 'csv' | 'xlsx' | 'document'
  file_hash: string
  headers: string[]
  rows: string[][]
  suggested_mapping: (string | null)[]
  fields: ImportField[]
  notes: string[]
  previous_import: { id: string; at: string | null; created: number } | null
  /** Lines the document reader was unsure of (PDF, photo or pasted menu only). */
  uncertain_rows?: number[]
}

export type MappedRow = Record<string, string>

export type CheckedRow = {
  index: number
  values: {
    name: string
    description: string
    category: string
    price: string | null
    kind: string
    duration: number | null
    sku: string | null
    stock: number | null
  }
  status: 'ready' | 'duplicate' | 'error'
  problems: string[]
  notes: string[]
  duplicate_of: { id: string; title: string; status: string } | null
  repeats_row: number | null
}

export type CheckResult = {
  default_kind: string
  kinds: { key: string; label: string; plural: string }[]
  stock_allowed: boolean
  rows: CheckedRow[]
  summary: { ready: number; duplicate: number; error: number; total: number }
}

export type CommitResult = {
  id: string
  created: number
  updated: number
  skipped: number
  errors: number
  rows: { index: number; result: string; problems?: string[]; offering_id?: string }[]
}

export type ImportBatch = {
  id: string
  filename: string
  source: string
  at: string | null
  summary: { rows: number; created: number; updated: number; skipped: number; errors: number }
  items: {
    id: string
    title: string
    status: string
    kind: string
    kind_label: string
    price_type: string
    price_amount: number | null
    can_go_live: boolean
    problem: string | null
  }[]
}

export type RecentImport = { id: string; filename: string; at: string | null; created: number; updated: number }
