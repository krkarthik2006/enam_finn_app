import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {title: "FINN — Your investment intelligence", description: "What changed, what it means, and who can help you understand it.", manifest: "/manifest.webmanifest", icons: {icon: "/icon.svg", apple: "/icon-192.png"}};
export const viewport: Viewport = {width: "device-width", initialScale: 1, themeColor: "#f7f8f4"};
export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>{children}</body></html>;
}
