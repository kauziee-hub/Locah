/**
 * Responsive widths for a hotlinked Unsplash photograph.
 *
 * The photo pipeline stores Unsplash's own URL (its guidelines ask for
 * hotlinking), asked for at 2400px — about 700KB, on a phone too. Unsplash's
 * image CDN resizes on request when `w` changes, keeping the tracking `ixid`
 * parameter, so the browser can pick the width it needs. Every other source
 * (our storage, a Pixabay copy, an owner upload) keeps its single URL.
 */

const WIDTHS = [480, 828, 1200, 1600, 2400]

export function srcSetFor(url: string | null | undefined): string | undefined {
  if (!url) return undefined
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return undefined
  }
  if (parsed.hostname !== 'images.unsplash.com') return undefined
  return WIDTHS.map((width) => {
    const at = new URL(parsed.toString())
    at.searchParams.set('w', String(width))
    return `${at.toString()} ${width}w`
  }).join(', ')
}
