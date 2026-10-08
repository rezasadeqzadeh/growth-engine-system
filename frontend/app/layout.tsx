import type { Metadata } from "next";
import type { ReactNode } from "react";
import { fa } from "@/lib/fa";
import "./globals.css";

export const metadata: Metadata = { title: fa.product };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
