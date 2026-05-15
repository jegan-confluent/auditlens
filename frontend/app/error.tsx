"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (process.env.NODE_ENV === "development") console.error(error);
  }, [error]);

  return (
    <main className="page" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "60vh", gap: 16 }}>
      <h2 style={{ fontSize: "1.5rem", fontWeight: 600 }}>Something went wrong</h2>
      <p className="muted" style={{ maxWidth: 400, textAlign: "center" }}>
        {error.message || "An unexpected error occurred. Please try again."}
      </p>
      <button className="settings-save-btn" onClick={reset}>Try again</button>
    </main>
  );
}
