import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "制裁筛查与留痕系统",
  description: "全球制裁合规筛查系统 — Sanctions Compliance Screening",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
