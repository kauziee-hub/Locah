import type { Words } from '@/lib/site-words'

/** The chat opens with a greeting in the visitor's language — which is also
 *  how the business's WhatsApp knows to answer in it (P1-10E6).
 *  Pure and server-free, so client sections (plans, basket) can use it too. */
export function whatsappHref(number: string, businessName?: string, t?: Words) {
  const digits = number.replace(/\D/g, '')
  const hello = t ? t('Hi {business}, ', { business: businessName || '' }) : `Hi ${businessName}, `
  const text = businessName ? `?text=${encodeURIComponent(hello)}` : ''
  return `https://wa.me/${digits}${text}`
}
