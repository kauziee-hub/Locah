import type { CSSProperties, ReactNode } from 'react'
import type { PublicWebsitePayload } from '@/lib/public-website'
import { LANG_LOCALE, siteWords, type SiteLang } from '@/lib/site-words'
import { SiteWordsProvider } from './SiteWords'
import { siteDna } from './experience/experience'
import { siteFontVariables } from './site-fonts'
import { siteThemeVars } from './WebsitePageView'

/**
 * A tenant page outside the home page (checkout, booking, a bill, a payment
 * link…): the business's own colours, never LOCAH's, its design DNA (the same
 * faces, accent and buttons as its site), a slim bar with its name to go back
 * by, and the visitor's language for the words inside (P1-10E6) — so the
 * moment of buying still looks like the business it is bought from.
 */
export function SiteFrame({
  site,
  lang,
  style,
  className,
  children,
}: {
  site: PublicWebsitePayload | null
  lang: SiteLang
  style?: CSSProperties
  className?: string
  children: ReactNode
}) {
  const theme = site ? siteThemeVars(site) : { styleVars: {}, paletteMode: 'light' }
  const dna = site ? siteDna((site.theme || {}) as Record<string, unknown>) : {}
  const t = siteWords(lang)
  const name = site?.business.display_name || ''
  const home = site ? `/${site.business.slug}` : ''
  return (
    <div
      data-locah-site=""
      className={[siteFontVariables, className].filter(Boolean).join(' ')}
      lang={LANG_LOCALE[lang]}
      data-palette={theme.paletteMode}
      data-display={dna.display}
      data-body={dna.body}
      data-headline={dna.headline}
      data-button={dna.button}
      data-concept={dna.concept}
      data-cardstyle={dna.cardstyle}
      data-shape={dna.shape}
      data-space={dna.space}
      style={{ ...theme.styleVars, minHeight: '100vh', ...style }}
    >
      {name ? (
        <header className="ls-frame__bar">
          <a className="ls-frame__name" href={home}>
            {name}
          </a>
          <a className="ls-frame__back" href={home}>
            {t('Back to {business}', { business: name })}
          </a>
        </header>
      ) : null}
      <SiteWordsProvider lang={lang}>{children}</SiteWordsProvider>
    </div>
  )
}
