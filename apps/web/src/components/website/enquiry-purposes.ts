import type { Words } from '@/lib/site-words'

/** What an enquiry is for — the form's own title for each (shared by the
 *  enquire page, which sets it as the page's one heading, and the form). */
export const PURPOSES = ['enquiry', 'site_visit', 'test_drive', 'callback', 'quote_request', 'membership']

export const purposeTitles = (t: Words): Record<string, string> => ({
  enquiry: t('Send an enquiry'),
  site_visit: t('Book a site visit'),
  test_drive: t('Book a test drive'),
  callback: t('Ask for a call back'),
  quote_request: t('Get a quote'),
  membership: t('Ask to join'),
})
