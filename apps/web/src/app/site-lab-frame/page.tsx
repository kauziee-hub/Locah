import { notFound } from 'next/navigation'

export const dynamic = 'force-dynamic'
export const metadata = { robots: { index: false, follow: false } }

/**
 * A site-lab page inside a phone-sized frame. Desktop Chrome will not open a
 * window narrower than about 500px, so a headless "phone" screenshot of the
 * page itself is laid out wider than a phone; inside a 390px frame the page
 * gets a true phone viewport. Local only, like the lab itself.
 */
export default function SiteLabFrame({ searchParams }: { searchParams?: { src?: string; w?: string; h?: string } }) {
  const src = searchParams?.src || ''
  if (!process.env.LOCAH_SITE_LAB_DIR || !/^\/site-lab\/[a-z0-9-~/]+(\?[a-z0-9=&]*)?$/.test(src)) notFound()
  const width = Math.min(Math.max(Number(searchParams?.w) || 390, 320), 480)
  const height = Math.min(Math.max(Number(searchParams?.h) || 844, 480), 1200)
  return (
    <div style={{ margin: 0, padding: 0, background: '#000', width, height, overflow: 'hidden' }}>
      <iframe title="phone" src={src} style={{ width, height, border: 0, display: 'block' }} />
    </div>
  )
}
