import type { Metadata } from "next";
import { AuthProvider } from "@/lib/auth-context";
import { ThreadsProvider } from "@/lib/threads-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "EGP Clinical Assistant",
  description: "Elective Genomics Programme clinical genomics assistant",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <ThreadsProvider>{children}</ThreadsProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
