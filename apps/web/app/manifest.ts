import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Lookout",
    short_name: "Lookout",
    description: "A risky payment waits until someone you trust agrees. A practice wallet.",
    start_url: "/wallet",
    display: "standalone",
    background_color: "#100c09",
    theme_color: "#1c140e",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
    ],
  };
}
