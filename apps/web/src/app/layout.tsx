import React from 'react'
import type { Metadata } from 'next'
import localFont from 'next/font/local'

// The design tokens must load before anything that reads them. `public.css`
// styles LOCAH's own surfaces (marketing, Marketplace); `website.css` styles
// published tenant sites, which read the `--site-*` contract instead of the
// LOCAH brand so a business's site looks like that business.
import '@platform/ui/tokens.css'
import '@platform/ui/public.css'
import './platform-overhaul.css'
import './locah-system.css'
import '@platform/ui/website.css'
// A site's creative direction (profile, type system, cards, nav) on top.
import '@platform/ui/site-studio.css'
import '@platform/ui/site-families.css'
// Motion, depth and scroll scenes — the experience layer on top.
import '@platform/ui/site-experience.css'
// Covers: first screens composed per business, each with its own movement.
import '@platform/ui/site-covers.css'
// The design DNA (type, texture, edges, header, cards) and premium sections.
import '@platform/ui/site-dna.css'
// Composed sections: blocks the layout engine arranged on a grid.
import '@platform/ui/site-compose.css'
// The owner's own style choices (sizes, corners) — last, so they win.
import '@platform/ui/site-owner.css'
import '@/components/website/reviews.css'

// Self-hosted from src/fonts (tools/fonts/build_fonts.py): a build never
// fetches a font.
const sans = localFont({
  src: [{ path: '../fonts/plusjakartasans-normal.woff2', style: 'normal', weight: '200 800' }],
  display: 'swap',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-general-sans',
})

const display = localFont({
  src: [{ path: '../fonts/instrumentserif-normal.woff2', style: 'normal', weight: '400' }],
  display: 'swap',
  adjustFontFallback: 'Times New Roman',
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-display-serif',
})

// LOCAH's own headline face (EK Type, Mumbai). Only LOCAH pages use it, so it
// is not preloaded: a published business website never downloads it.
const headline = localFont({
  src: [{ path: '../fonts/aneklatin-normal.woff2', style: 'normal', weight: '100 800' }],
  display: 'swap',
  preload: false,
  declarations: [{ prop: 'unicode-range', value: 'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+20B9, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD' }],
  variable: '--font-anek',
})

export const metadata: Metadata = {
  title: {
    default: 'LOCAH — Local Businesses. Limitless Possibilities.',
    template: '%s',
  },
  description:
    'LOCAH is the digital operating layer for local businesses: build your presence, get discovered, take orders and bookings, and run the whole business in one place.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable} ${headline.variable}`}>
      <body>{children}</body>
    </html>
  )
}
