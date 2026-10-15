import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Lookout",
    short_name: "Lookout",
    description: "A risky payment waits until someone you trust agrees. PayPal sandbox wallet.",
    start_url: "/wallet",
    display: "standalone",
    background_color: "#001c64",
    theme_color: "#001c64",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
    ],
  };
}
