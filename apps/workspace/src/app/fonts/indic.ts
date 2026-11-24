import localFont from 'next/font/local'

/**
 * Tamil and Devanagari faces behind General Sans (P1-10E6), so a customer's
 * Tamil or Hindi WhatsApp message, a product named in Tamil, and the Workspace
 * in Tamil or Hindi render in a real face. Latin text keeps General Sans.
 *
 * Self-hosted: cut by tools/fonts/build_fonts.py (Noto, OFL) to each script's
 * own block, so a screen downloads one only when that script is on it, and a
 * build never fetches a font.
 */
export const notoTamil = localFont({
  src: [{ path: './notosanstamil-normal.woff2', style: 'normal', weight: '100 900' }],
  display: 'swap',
  preload: false,
  adjustFontFallback: false,
  declarations: [{ prop: 'unicode-range', value: 'U+0B80-0BFF' }],
  variable: '--font-ws-tamil',
})

export const notoDevanagari = localFont({
  src: [{ path: './notosansdevanagari-normal.woff2', style: 'normal', weight: '100 900' }],
  display: 'swap',
  preload: false,
  adjustFontFallback: false,
  declarations: [{ prop: 'unicode-range', value: 'U+0900-097F, U+1CD0-1CF9, U+A8E0-A8FF' }],
  variable: '--font-ws-devanagari',
})
