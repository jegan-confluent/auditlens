import Link from "next/link";
import HeaderStatus from "../components/HeaderStatus";
import NavLinks from "../components/NavLinks";
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
            <Link href="/dashboard" className="brand" aria-label="AuditLens dashboard">
              <img src="/logo.png" alt="" className="brand-logo" />
              <span>
                <span className="brand-name">AuditLens</span>
                <span className="brand-tagline">Kafka-native audit intelligence</span>
              </span>
            </Link>
            <nav className="nav">
              <NavLinks />
            </nav>
            <HeaderStatus />
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
