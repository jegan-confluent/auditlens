import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  output: "standalone",
  // Pin the workspace root to this directory so Next.js doesn't walk up
  // the filesystem looking for a package-lock.json (and pick a stray
  // outer one on dev machines that have multiple JS projects). Without
  // this, `next build` emits "inferred your workspace root, but it may
  // not be correct" on every run and the standalone bundle can copy
  // files from outside the repo.
  outputFileTracingRoot: path.join(__dirname),
};

export default nextConfig;
