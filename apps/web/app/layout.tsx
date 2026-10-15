import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible, Manrope } from "next/font/google";
import "./globals.css";

const sans = Atkinson_Hyperlegible({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-sans",
});

const display = Manrope({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "Lookout",
  description: "Holds a PayPal payment while it checks for scam pressure and asks someone you trust before money moves.",
  applicationName: "Lookout",
  appleWebApp: {
    capable: true,
    title: "Lookout",
    statusBarStyle: "black-translucent",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#001c64",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable} h-full`}>
      <body className="min-h-full" style={{ fontFamily: "var(--font-sans), sans-serif" }}>
        {children}
      </body>
    </html>
  );
}
