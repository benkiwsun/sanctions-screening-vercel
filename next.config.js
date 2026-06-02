/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The Python serverless functions live under /api and are routed by Vercel.
  // During `next dev` (without `vercel dev`) the /api routes are unavailable;
  // use `vercel dev` for an integrated local frontend + Python backend.
};

module.exports = nextConfig;
