/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // In local development, proxy /api/* to a locally-running Python backend
    // (uvicorn) so `npm run dev` works without the full Vercel toolchain.
    // In production this is a no-op: Vercel routes /api/* to the serverless
    // function via vercel.json before Next.js rewrites are evaluated.
    if (process.env.NODE_ENV === "development") {
      const target = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";
      return [{ source: "/api/:path*", destination: `${target}/api/:path*` }];
    }
    return [];
  },
};

module.exports = nextConfig;
