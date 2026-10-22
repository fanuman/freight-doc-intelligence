import type { Metadata } from "next";
import { Barlow, Barlow_Condensed } from "next/font/google";
import type { ReactNode } from "react";
import "./globals.css";

// Two cuts of one family, chosen to feel like road signs and container lettering. Next.js downloads them once
// at build time and serves them from our own domain (no request to Google when a person opens the app).
const body = Barlow({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-body", display: "swap" });
const display = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["600", "700"],
  variable: "--font-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: "FreightLens",
  description: "Upload freight quotes and invoices, review what the model could not settle, and compare each invoice with its quote.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={`${body.variable} ${display.variable}`}>
      <body>{children}</body>
    </html>
  );
}
