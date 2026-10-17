/**
 * Typographic glue for a tenant site: a number keeps its unit ("2 pm",
 * "500 g"), ₹ keeps its amount, and a heading never ends on a single word
 * alone on its line. Only spaces become no-break spaces, in text nodes — no
 * word is changed, so the copy stays the owner's.
 *
 * It runs for every visitor (SiteMotion calls `typeset` before deciding on
 * motion), and the motion runtime glues each heading again before splitting
 * its words; both passes are idempotent.
 */

const NBSP = '\u00a0'
/** A number and its unit ("2 pm", "500 g", "3 days"), and the rupee sign. */
const UNIT = /(\d)[^\S\u00a0]+(am|pm|kg|g|km|min|mins|days?|hrs?)\b/gi
const RUPEE = /₹[^\S\u00a0]+/g
/** A pair of last words longer than this would not fit a phone as one unit. */
const WIDOW_PAIR_MAX = 15
const HEADINGS = 'h1, h2, .fx-cta__title'

export function textNodes(el: HTMLElement): Text[] {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n as Text)
  return nodes
}

function glueUnits(nodes: Text[]) {
  for (const node of nodes) {
    const text = node.nodeValue || ''
    const glued = text.replace(UNIT, `$1${NBSP}$2`).replace(RUPEE, `₹${NBSP}`)
    if (glued !== text) node.nodeValue = glued
  }
}

/** Glue inside one element; a heading also keeps its last two words together. */
export function glue(el: HTMLElement) {
  const nodes = textNodes(el)
  glueUnits(nodes)
  if (!el.matches(HEADINGS)) return
  const words = (el.textContent || '').trim().split(/[^\S\u00a0]+/)
  if (words.length < 3 || words.slice(-2).join(' ').length > WIDOW_PAIR_MAX) return
  // Already glued (a second pass): the last two words are one unit.
  if (/\u00a0\S+\s*$/.test(el.textContent || '')) return
  // The last breakable space with a word after it, in whichever text node
  // (the accent's span, or the plain text around it) it falls.
  let wordAfter = false
  for (let i = nodes.length - 1; i >= 0; i--) {
    const text = nodes[i].nodeValue || ''
    let last: RegExpExecArray | null = null
    const space = /[^\S\u00a0]+/g
    for (let m = space.exec(text); m; m = space.exec(text)) {
      if (wordAfter || /\S/.test(text.slice(m.index + m[0].length))) last = m
    }
    if (last) {
      nodes[i].nodeValue = text.slice(0, last.index) + NBSP + text.slice(last.index + last[0].length)
      return
    }
    if (/\S/.test(text)) wordAfter = true
  }
}

/** The whole site: units everywhere in its sections, widows in its headings. */
export function typeset(root: HTMLElement) {
  root.querySelectorAll<HTMLElement>('section, footer').forEach((part) => glueUnits(textNodes(part)))
  root.querySelectorAll<HTMLElement>(HEADINGS).forEach(glue)
}
