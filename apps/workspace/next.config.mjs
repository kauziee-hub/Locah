/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Lets a local production build run beside `next dev` without sharing .next.
  distDir: process.env.NEXT_DIST_DIR || '.next',
  // Catalogue import sends the file through a server action: a 2 MB sheet or an
  // 8 MB PDF / photo, base64-encoded (Products & services → Import).
  experimental: { serverActions: { bodySizeLimit: '12mb' } },
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
