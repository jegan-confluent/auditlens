import Link from "next/link";

export default function NotFound() {
  return (
    <main className="page" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "60vh", gap: 16 }}>
      <h2 style={{ fontSize: "1.5rem", fontWeight: 600 }}>404 — Page not found</h2>
      <p className="muted">The page you were looking for does not exist.</p>
      <Link href="/" className="settings-save-btn" style={{ textDecoration: "none" }}>Go to dashboard</Link>
    </main>
  );
}
