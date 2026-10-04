/** Enquiry stages and sources in the owner's words (stored values never shown). */
export const STAGE_WORDS: Record<string, string> = {
  new: 'New', contacted: 'Contacted', qualified: 'Interested', won: 'Won', lost: 'Lost',
}
/** What moving to a stage is called on its button. */
export const MOVE_WORDS: Record<string, string> = {
  new: 'Reopen', contacted: 'Mark as contacted', qualified: 'Mark as interested', won: 'Mark as won', lost: 'Mark as lost',
}
export const SOURCE_WORDS: Record<string, string> = {
  manual: 'Added by your team', website_enquiry: 'Website', marketplace: 'Marketplace', import: 'Imported',
  whatsapp: 'WhatsApp',
}
