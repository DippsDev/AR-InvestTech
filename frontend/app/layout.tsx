import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AR-InvestTech",
  description: "US30 Scalping System",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full">
        {children}
      </body>
    </html>
  );
}
