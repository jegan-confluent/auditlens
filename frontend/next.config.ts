import type { NextConfig } from "next";
import path from "node:path";

// Inside the docker-compose network the api container is reachable as
// `api:8080`. When the operator visits the dashboard via Caddy (port 80
// or the 8088 fallback) Caddy already proxies /api/* and /health and
// /ready to api:8080 — these rewrites are redundant there.
//
// The reason they exist: when the dashboard is opened directly on
// :3000 (which compose binds to 127.0.0.1:3000 so the install wizard
// can probe it), every fetch in lib/api.ts that uses the relative
// "/api" base would hit the Next.js server instead of Caddy. Next.js
// has no /api/* routes, so every dashboard card (events, summary,
// system status, ready, …) would 404. With these rewrites the Next.js
// server proxies the same paths to the api container, so the dashboard
// works at :3000 as well as via Caddy.
//
// Rewrites only fire on the SERVER side — the browser still sees
// /api/* on its origin, no CORS preflight, no exposed backend URL.
const API_REWRITE_TARGET = process.env.AUDITLENS_API_URL || "http://api:8080";

const nextConfig: NextConfig = {
  output: "standalone",
  // Pin the workspace root to this directory so Next.js doesn't walk up
  // the filesystem looking for a package-lock.json (and pick a stray
  // outer one on dev machines that have multiple JS projects). Without
  // this, `next build` emits "inferred your workspace root, but it may
  // not be correct" on every run and the standalone bundle can copy
  // files from outside the repo.
  outputFileTracingRoot: path.join(__dirname),
  async rewrites() {
    return [
      // /api/<anything> → strip /api, forward to backend.
      {
        source: "/api/:path*",
        destination: `${API_REWRITE_TARGET}/:path*`,
      },
      // /health and /ready are unauthenticated probes the api exposes
      // at the root (no /api prefix). Mirror Caddy's behaviour so the
      // install wizard's localhost:3000 probes resolve identically.
      {
        source: "/health",
        destination: `${API_REWRITE_TARGET}/health`,
      },
      {
        source: "/ready",
        destination: `${API_REWRITE_TARGET}/ready`,
      },
    ];
  },
};

export default nextConfig;
