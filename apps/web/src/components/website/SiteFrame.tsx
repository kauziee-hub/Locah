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
  const nav = (site?.navigation || []).filter((item) => typeof item.path === 'string' && item.path)
  const place = site?.business.place || {}
  const phone = place.phone || site?.business.contact?.phone || ''
  /** A site path ("/menu", "/#shop") as a link from outside its pages. */
  const link = (path: string) => (path === '/' ? home : `${home}${path.startsWith('/') ? path : `/${path}`}`)
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
          {/* The site's own pages stay one tap away: a checkout without them
              read as a separate app (certification critic). */}
          {nav.length ? (
            <nav className="ls-frame__nav" aria-label={t('Explore')}>
              {nav.map((item) => (
                <a key={`${item.label}-${item.path}`} href={link(item.path)}>
                  {t(item.label)}
                </a>
              ))}
            </nav>
          ) : null}
          <a className="ls-frame__back" href={home}>
            {t('Back to {business}', { business: name })}
          </a>
        </header>
      ) : null}
      <SiteWordsProvider lang={lang}>{children}</SiteWordsProvider>
      {name ? (
        <footer className="ls-frame__foot">
          <div className="ls-frame__foot-inner">
            <div>
              <p className="ls-foot__name">{name}</p>
              {place.address ? <p className="ls-frame__line">{place.address}</p> : null}
              {place.hours_summary ? <p className="ls-frame__line">{place.hours_summary}</p> : null}
              {phone ? (
                <p className="ls-frame__line">
                  <a href={`tel:${phone.replace(/[^+\d]/g, '')}`}>{phone}</a>
                </p>
              ) : null}
            </div>
            {nav.length ? (
              <div className="ls-foot__col">
                <p className="ls-foot__heading">{t('Explore')}</p>
                {nav.map((item) => (
                  <a key={`f-${item.label}-${item.path}`} href={link(item.path)}>
                    {t(item.label)}
                  </a>
                ))}
              </div>
            ) : null}
          </div>
          <div className="ls-foot__bar">
            <span>
              &copy; {new Date().getFullYear()} {name}
            </span>
            <a className="ls-foot__by" href="/">
              {t('Powered by LOCAH')}
            </a>
          </div>
        </footer>
      ) : null}
    </div>
  )
}
