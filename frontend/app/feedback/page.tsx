"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { type FeedbackPayload, type FeedbackType, submitFeedback } from "../../lib/api";

const TYPES: ReadonlyArray<{ value: FeedbackType; label: string; emoji: string }> = [
  { value: "bug",     label: "Bug report",      emoji: "🐛" },
  { value: "feature", label: "Feature request",  emoji: "✨" },
  { value: "general", label: "General",           emoji: "💬" },
];

const TYPE_COLORS: Record<FeedbackType, { bg: string; text: string }> = {
  bug:     { bg: "#E24B4A", text: "#fff" },
  feature: { bg: "#0F6E56", text: "#fff" },
  general: { bg: "#5F5E5A", text: "#fff" },
};

const TITLE_PLACEHOLDERS: Record<FeedbackType, string> = {
  bug:     "What went wrong?",
  feature: "What would you like to see?",
  general: "What's on your mind?",
};

const TITLE_MAX = 200;
const DESC_MAX = 5000;

type FormState = {
  type: FeedbackType;
  title: string;
  description: string;
  email: string;
};

export default function FeedbackPage() {
  return (
    <Suspense>
      <FeedbackForm />
    </Suspense>
  );
}

function FeedbackForm() {
  const searchParams = useSearchParams();
  const [form, setForm] = useState<FormState>({
    type: "bug",
    title: "",
    description: "",
    email: "",
  });
  const [pageContext, setPageContext] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const fromParam = searchParams.get("from");
    const ctx = fromParam || (typeof document !== "undefined" ? document.referrer : "");
    setPageContext(ctx);
  }, [searchParams]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const payload: FeedbackPayload = {
        type: form.type,
        title: form.title.trim(),
        description: form.description.trim(),
        email: form.email.trim() || undefined,
        page_context: pageContext || undefined,
      };
      await submitFeedback(payload);
      setSuccess(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Submission failed. Please try again.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  if (success) {
    return (
      <main className="feedback-page">
        <div className="feedback-card">
          <div className="feedback-success">
            <div className="feedback-success-icon">✓</div>
            <p className="feedback-success-msg">Feedback received. Thanks for taking the time.</p>
            <Link href="/dashboard" className="feedback-back-link">← Back to dashboard</Link>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="feedback-page">
      <div className="feedback-card">
        <div className="feedback-header">
          <h1 className="feedback-title">Share feedback</h1>
          <p className="feedback-subtitle">Bug report, feature request, or anything on your mind.</p>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          {/* Type chips */}
          <div className="feedback-field">
            <div className="feedback-type-chips" role="group" aria-label="Feedback type">
              {TYPES.map(({ value, label, emoji }) => {
                const isActive = form.type === value;
                const colors = TYPE_COLORS[value];
                return (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={isActive}
                    className={`feedback-type-chip${isActive ? " active" : ""}`}
                    style={isActive ? { background: colors.bg, color: colors.text, borderColor: colors.bg } : undefined}
                    onClick={() => { update("type", value); titleRef.current?.focus(); }}
                  >
                    <span aria-hidden>{emoji}</span>
                    {" "}
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Title */}
          <div className="feedback-field">
            <label className="feedback-label" htmlFor="fb-title">Title</label>
            <input
              ref={titleRef}
              id="fb-title"
              type="text"
              className="feedback-input"
              placeholder={TITLE_PLACEHOLDERS[form.type]}
              value={form.title}
              maxLength={TITLE_MAX}
              required
              onChange={(e) => update("title", e.target.value)}
            />
            {form.title.length > 150 ? (
              <span className="feedback-char-count">{form.title.length}/{TITLE_MAX}</span>
            ) : null}
          </div>

          {/* Description */}
          <div className="feedback-field">
            <label className="feedback-label" htmlFor="fb-desc">Description</label>
            <textarea
              id="fb-desc"
              className="feedback-textarea"
              placeholder="Give us as much detail as you'd like."
              value={form.description}
              maxLength={DESC_MAX}
              required
              rows={5}
              onChange={(e) => update("description", e.target.value)}
            />
            {form.description.length > 4000 ? (
              <span className="feedback-char-count">{form.description.length}/{DESC_MAX}</span>
            ) : null}
          </div>

          {/* Email */}
          <div className="feedback-field">
            <label className="feedback-label" htmlFor="fb-email">
              Email <span className="feedback-optional">(optional)</span>
            </label>
            <input
              id="fb-email"
              type="email"
              className="feedback-input"
              placeholder="So we can follow up if needed"
              value={form.email}
              onChange={(e) => update("email", e.target.value)}
            />
          </div>

          {/* Error */}
          {error ? <p className="feedback-error">{error}</p> : null}

          {/* Submit */}
          <button
            type="submit"
            className="feedback-submit"
            disabled={submitting}
          >
            {submitting ? (
              <><span className="feedback-spinner" aria-hidden /> Sending…</>
            ) : "Send feedback"}
          </button>
        </form>
      </div>
    </main>
  );
}
