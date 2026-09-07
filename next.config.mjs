/** @type {import('next').NextConfig} */
const nextConfig = {
  // 完全な静的書き出し。Vercel Functions をひとつも作らない(SPEC N-01)
  output: 'export',
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};
export default nextConfig;
