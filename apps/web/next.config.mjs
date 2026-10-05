/** @type {import('next').NextConfig} */
const nextConfig = {
  // Lets a local production build run beside `next dev` without sharing .next.
  distDir: process.env.NEXT_DIST_DIR || '.next',
  reactStrictMode: true,
  // Once a browser has seen this site over https it refuses plain http for a year,
  // so a mistyped or old http link can never be served insecurely. No
  // includeSubDomains: each subdomain proves its own certificate first.
  async headers() {
    if (process.env.NODE_ENV !== 'production') return []
    return [
      {
        source: '/:path*',
        headers: [{ key: 'Strict-Transport-Security', value: 'max-age=31536000' }],
      },
    ]
  },
  transpilePackages: [
    '@platform/ui',
    '@platform/contracts',
    '@platform/config',
    '@platform/validation',
    '@platform/api-client',
    '@platform/auth',
    '@platform/permissions',
    '@platform/observability',
  ],
}

export default nextConfig
