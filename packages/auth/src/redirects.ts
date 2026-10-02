/**
 * Destination Intent — validated post-auth redirect targets (Doc 12 §6.6;
 * Doc 05 §14 DLK-002/DLK-003/DLK-008). Only platform-owned *relative* paths
 * are permitted: an absolute URL, a protocol-relative `//host`, a backslash
 * (which some browsers read as `/`), an encoded slash pair, a `..` segment or a
 * control character is refused, so nothing here can send someone off-platform.
 */

const BLOCKED_PATTERNS = [
  /^https?:\/\//i,
  /^\/\//,
  /^javascript:/i,
  /%2f%2f/i,
  /%5c/i,
  /\\/,
  /\.\./,
  // eslint-disable-next-line no-control-regex
  /[\u0000-\u001f\u007f]/,
]

/**
 * A Business's own website and its transaction pages (`/{slug}`,
 * `/{slug}/checkout`, `/{slug}/book`, `/{slug}/account`…): a shopper who signs
 * in at checkout returns to the same basket (Doc 05 AUTH-004, AUTH-008). The
 * slug shape is the platform's; the destination is re-authorised on arrival.
 */
const TENANT_PATH = /^\/[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?(?:\/[A-Za-z0-9\-._~%/]*)?(?:\?[^#]*)?$/

export function isValidDestinationIntent(destination: string | null | undefined): boolean {
  if (!destination || typeof destination !== 'string') {
    return false
  }
  const trimmed = destination.trim()
  if (!trimmed.startsWith('/') || trimmed.length > 2048) {
    return false
  }
  if (BLOCKED_PATTERNS.some((pattern) => pattern.test(trimmed))) {
    return false
  }
  if (trimmed === '/') {
    return true
  }
  const pathPrefixes = [
    '/login',
    '/auth/',
    '/workspace',
    '/admin',
    '/b/',
    '/me',
    // Business onboarding: someone who picks "I run a business" on the
    // homepage is sent to /login?destination=/start and must land back here.
    '/start',
    // Consumer surfaces: Marketplace and My Activity return where they began.
    '/marketplace',
    '/search',
    '/activity',
  ]
  return (
    pathPrefixes.some((prefix) => trimmed === prefix || trimmed.startsWith(prefix)) ||
    TENANT_PATH.test(trimmed)
  )
}

export function resolveDestinationIntent(
  destination: string | null | undefined,
  fallback = '/'
): string {
  return isValidDestinationIntent(destination) ? destination!.trim() : fallback
}

export function buildSignInRedirectUrl(
  signInPath: string,
  destination: string | null | undefined
): string {
  if (!isValidDestinationIntent(destination)) {
    return signInPath
  }
  const params = new URLSearchParams({ destination: destination!.trim() })
  return `${signInPath}?${params.toString()}`
}

export function readDestinationFromSearchParams(
  searchParams: URLSearchParams | { get(name: string): string | null }
): string | null {
  return searchParams.get('destination')
}
