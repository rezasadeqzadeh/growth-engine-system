"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, setToken } from "@/lib/api";
import { fa, fill } from "@/lib/fa";
import { DigitInput } from "@/components/DigitInput";
import { useAction } from "@/components/hooks";
import { ErrorLine, Field } from "@/components/ui";

// Matches RESEND_AFTER in backend/growth_engine/auth/otp.py.
const RESEND_SECONDS = 120;

/** Phone + SMS code. "signup" asks for the name first; "login" asks for it only
 *  if the phone has no account yet, and then signs up with the same code. */
export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [sent, setSent] = useState(false);
  const [needName, setNeedName] = useState(mode === "signup");
  const [left, setLeft] = useState(0);
  const { run, busy, error } = useAction();

  useEffect(() => {
    if (left <= 0) return;
    const timer = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(timer);
  }, [left]);

  const [note, setNote] = useState<string | null>(null);
  const send = () => run(async () => {
    const body: Record<string, string> = { phone };
    if (needName) Object.assign(body, { first_name: first, last_name: last });
    try {
      await api("/auth/otp/send", "POST", body);
      setNote(fill(fa.login.codeSent, { phone }));
      setLeft(RESEND_SECONDS);
    } catch (e) {
      // A code was sent a moment ago and is still valid: go to it instead of showing an error.
      if (e instanceof ApiError && e.code === "otp_too_soon") {
        setNote(fa.login.alreadySent);
        setLeft(Number(e.extra.retry_after) || RESEND_SECONDS);
      } else {
        throw e;
      }
    }
    setSent(true);
    setCode("");
  });

  const verify = () => run(async () => {
    const body: Record<string, string> = { phone, code };
    if (needName) Object.assign(body, { first_name: first, last_name: last });
    try {
      const res = await api<{ token: string }>("/auth/otp/verify", "POST", body);
      setToken(res.token);
      window.location.href = "/";
    } catch (e) {
      // A new phone: ask for the name and sign up with the same code (no second SMS).
      if (e instanceof ApiError && e.code === "account_not_found") {
        setNeedName(true);
        return;
      }
      throw e;
    }
  });

  const minutes = Math.floor(left / 60);
  const seconds = String(left % 60).padStart(2, "0");

  return (
    <main className="main" style={{ maxWidth: 420, margin: "40px auto" }}>
      <div className="card">
        <h1>{mode === "signup" ? fa.login.signupHeading : fa.login.title}</h1>
        <Field label={fa.login.phone}>
          <DigitInput type="tel" inputMode="numeric" placeholder="09xxxxxxxxx" value={phone} disabled={sent}
            onChange={(e) => setPhone(e.target.value.trim())} />
        </Field>
        {needName ? (
          <>
            {mode === "login" ? <p className="muted">{fa.login.newAccount}</p> : null}
            <Field label={fa.login.firstName}><input type="text" value={first} onChange={(e) => setFirst(e.target.value)} /></Field>
            <Field label={fa.login.lastName}><input type="text" value={last} onChange={(e) => setLast(e.target.value)} /></Field>
          </>
        ) : null}
        {sent ? (
          <>
            {note ? <p className="okText">{note}</p> : null}
            <Field label={fa.login.code}>
              <DigitInput type="text" inputMode="numeric" autoComplete="one-time-code" value={code}
                onChange={(e) => setCode(e.target.value.trim())} />
            </Field>
            <div className="spread">
              <button className="btn" disabled={busy || !code || (needName && !first)} onClick={verify}>
                {needName ? fa.login.signup : fa.login.verify}
              </button>
              {left > 0 ? (
                <span className="muted">{fill(fa.login.resendIn, { time: `${minutes}:${seconds}` })}</span>
              ) : (
                <button className="btn ghost small" disabled={busy} onClick={send}>{fa.login.resend}</button>
              )}
            </div>
            <p><button className="btn ghost small" onClick={() => { setSent(false); setLeft(0); }}>{fa.login.changePhone}</button></p>
            {process.env.NODE_ENV !== "production" ? <p className="muted">{fa.login.devHint}</p> : null}
          </>
        ) : (
          <button className="btn" disabled={busy || !phone || (needName && !first)} onClick={send}>
            {mode === "signup" ? fa.login.signup : fa.login.sendCode}
          </button>
        )}
        <ErrorLine text={error} />
        <p style={{ marginTop: 16 }}>
          {mode === "login"
            ? <Link href="/signup">{fa.login.signupTitle}</Link>
            : <Link href="/login">{fa.login.haveAccount}</Link>}
        </p>
      </div>
    </main>
  );
}
