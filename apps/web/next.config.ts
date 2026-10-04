import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["127.0.0.1", "10.*.*.*", "192.168.*.*", "172.*.*.*"],
};

export default nextConfig;
