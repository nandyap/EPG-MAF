import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  outputFileTracingRoot: __dirname,
  experimental: {
    // Keep bundled output small for the Container Apps image.
    optimizePackageImports: ["react-markdown", "remark-gfm"],
  },
};

export default config;
