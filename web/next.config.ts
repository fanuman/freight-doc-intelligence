import type { NextConfig } from "next";

// Where the FastAPI server lives. The browser never talks to it directly: it calls /api/..., and Next.js
// forwards the request. That keeps everything on one origin, so the API needs no CORS settings, and it is
// the same shape we will use when a load balancer routes /api to the backend after deployment.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Hides the round "N" badge that `npm run dev` draws in the corner (it never appears in a production build).
  devIndicators: false,
  // Makes `next build` also produce a small self-contained server (.next/standalone) for the container image.
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
};

export default nextConfig;
