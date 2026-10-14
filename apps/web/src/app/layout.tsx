import React from 'react'
import type { Metadata } from 'next'
import { Anek_Latin, Plus_Jakarta_Sans, Instrument_Serif } from 'next/font/google'

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
import '@/components/website/reviews.css'

const sans = Plus_Jakarta_Sans({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-general-sans',
})

const display = Instrument_Serif({
  subsets: ['latin'],
  weight: '400',
  display: 'swap',
  variable: '--font-display-serif',
})

// LOCAH's own headline face (EK Type, Mumbai). Only LOCAH pages use it, so it
// is not preloaded: a published business website never downloads it.
const headline = Anek_Latin({
  subsets: ['latin'],
  display: 'swap',
  axes: ['wdth'],
  preload: false,
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
