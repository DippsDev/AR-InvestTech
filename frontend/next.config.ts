import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: "export",
  // Multiple lockfiles exist (repo root + frontend). Pin the workspace so
  // Turbopack does not resolve modules as [project]/frontend/... and break RSC.
  outputFileTracingRoot: path.join(__dirname),
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
