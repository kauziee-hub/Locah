/** "12, 2nd Avenue, Anna Nagar, Chennai 600040" from a saved address, in the order people write it. */
export function addressLine(address: Record<string, unknown> | null | undefined): string {
  if (!address) return ''
  const pick = (...keys: string[]) => {
    for (const k of keys) {
      const v = address[k]
      if (typeof v === 'string' && v.trim()) return v.trim()
    }
    return ''
  }
  const city = [pick('city'), pick('postal_code', 'pincode', 'pin')].filter(Boolean).join(' ')
  return [pick('line1', 'line_1', 'street'), pick('locality', 'area'), city].filter(Boolean).join(', ')
}

const ZONES: Record<string, string> = {
  'Asia/Kolkata': 'India time', 'Asia/Dubai': 'Dubai time', 'Asia/Singapore': 'Singapore time',
  'Europe/London': 'UK time', 'America/New_York': 'US Eastern time', 'Australia/Sydney': 'Sydney time', UTC: 'UTC',
}

export function zoneWords(tz: string): string {
  return ZONES[tz] ?? tz
}
