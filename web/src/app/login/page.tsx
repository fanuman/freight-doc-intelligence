"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { EyeIcon, EyeOffIcon, ScanIcon, SigmaIcon, UserCheckIcon } from "@/components/Icons";
import { Wordmark } from "@/components/Logo";
import { errorMessage, signIn, signUp } from "@/lib/api";

const POINTS = [
  { icon: <ScanIcon size={22} />, title: "Reads the paperwork", text: "PDFs, spreadsheets and e-mails, whatever layout the carrier uses." },
  { icon: <SigmaIcon size={22} />, title: "Does the arithmetic itself", text: "Every total is recomputed by code, never taken from the model." },
  { icon: <UserCheckIcon size={22} />, title: "Asks a person when unsure", text: "Hard cases wait for a reviewer, and every decision is recorded." },
];

export default function LoginPage() {
  const router = useRouter();
  const [creating, setCreating] = useState(false); // false = sign in, true = create a company account
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (creating) await signUp(company.trim(), email.trim(), password);
      else await signIn(email.trim(), password);
      router.push("/");
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  function choose(createAccount: boolean) {
    setCreating(createAccount);
    setError(null);
  }

  return (
    <div className="auth">
      <aside className="auth-brand">
        <Wordmark size={40} onDark />
        <div className="auth-pitch">
          <h1>Check every freight invoice against its quote.</h1>
          <ul className="points">
            {POINTS.map((point) => (
              <li key={point.title}>
                <span className="point-icon">{point.icon}</span>
                <span>
                  <strong>{point.title}</strong>
                  <span>{point.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <svg className="auth-route" viewBox="0 0 520 120" aria-hidden="true">
          <path className="auth-route-line" d="M20 96 C 140 96, 160 24, 270 40 S 410 100, 500 28" />
          <circle cx="20" cy="96" r="6" className="auth-port" />
          <circle cx="500" cy="28" r="6" className="auth-port" />
          <circle cx="270" cy="40" r="4" className="auth-port-small" />
        </svg>
        <p className="auth-fine">All documents in this demo are synthetic.</p>
      </aside>

      <main className="auth-form-side">
        <div className="auth-card">
          <div className="auth-mobile-logo">
            <Wordmark size={34} />
          </div>
          <div className="segmented" data-pos={creating ? "1" : "0"} role="tablist" aria-label="Sign in or create an account">
            <button type="button" role="tab" aria-selected={!creating} onClick={() => choose(false)}>
              Sign in
            </button>
            <button type="button" role="tab" aria-selected={creating} onClick={() => choose(true)}>
              Create account
            </button>
          </div>

          <form onSubmit={handleSubmit}>
            <h2>{creating ? "Set up your company" : "Welcome back"}</h2>

            {creating && (
              <>
                <label htmlFor="company">Company name</label>
                <input id="company" required maxLength={200} value={company} onChange={(e) => setCompany(e.target.value)} />
              </>
            )}

            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />

            <label htmlFor="password">Password{creating ? " (at least 12 characters)" : ""}</label>
            <div className="password">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                required
                minLength={creating ? 12 : 1}
                maxLength={128}
                autoComplete={creating ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOffIcon size={18} /> : <EyeIcon size={18} />}
              </button>
            </div>

            {error && (
              <p className="callout callout-bad" role="alert">
                {error}
              </p>
            )}
            <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
              {busy ? "One moment…" : creating ? "Create account" : "Sign in"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
