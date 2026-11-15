import React from "react";
import "./globals.css";

export const metadata = {
  title: "Ecovuna Desk",
  description: "Grounded agricultural extension intelligence for African field teams.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
