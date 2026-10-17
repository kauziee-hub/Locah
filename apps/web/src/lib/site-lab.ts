import { readFile } from 'node:fs/promises'
import path from 'node:path'
import type { PublicWebsitePayload } from '@/lib/public-website'

/**
 * One page of a site-lab fixture: `<fixture>.json` is its home,
 * `<fixture>~<page>.json` an inner page. Links between its pages stay inside
 * the lab. Null when the lab is off (no LOCAH_SITE_LAB_DIR) or the file is
 * missing — the lab is local only.
 *
 * `from`/`to` (section indexes, inclusive) render only part of the page, so a
 * fixed-size screenshot can show any sections (the vision critic's renderer).
 */
export async function readLabPage(
  fixture: string,
  page?: string,
  slice?: { from?: string; to?: string }
): Promise<PublicWebsitePayload | null> {
  const dir = process.env.LOCAH_SITE_LAB_DIR
  if (!dir || !/^[a-z0-9-]{2,40}$/.test(fixture)) return null
  if (page !== undefined && !/^[a-z0-9-]{1,40}$/.test(page)) return null
  try {
    const data = JSON.parse(
      await readFile(path.join(dir, page ? `${fixture}~${page}.json` : `${fixture}.json`), 'utf8')
    ) as PublicWebsitePayload
    const from = Number(slice?.from ?? NaN)
    const to = Number(slice?.to ?? NaN)
    const sections =
      Number.isInteger(from) || Number.isInteger(to)
        ? data.page.sections.slice(Number.isInteger(from) ? from : 0, Number.isInteger(to) ? to + 1 : undefined)
        : data.page.sections
    return {
      ...data,
      page: { ...data.page, sections },
      business: { ...data.business, slug: `site-lab/${fixture}` },
    }
  } catch {
    return null
  }
}
