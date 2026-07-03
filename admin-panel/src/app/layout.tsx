import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Saneo — Admin",
  robots: "noindex, nofollow",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="bg-zinc-950 text-zinc-100 min-h-screen">{children}</body>
    </html>
  );
}
