import Link from "next/link";
import "./globals.css";

export const metadata = {
  title: "AuditLens",
  description: "AuditLens product frontend"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <header className="topbar">
            <Link href="/dashboard" className="brand">AuditLens</Link>
            <nav className="nav">
              <Link href="/dashboard">Dashboard</Link>
              <Link href="/events">Events</Link>
              <Link href="/system">System</Link>
            </nav>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
