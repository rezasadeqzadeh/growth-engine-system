"use client";

import { useState } from "react";
import { api, setToken } from "@/lib/api";
import { fa } from "@/lib/fa";
import { useAction } from "@/components/hooks";
import { ErrorLine, Field } from "@/components/ui";

export default function LoginPage() {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [sent, setSent] = useState(false);
  const [signup, setSignup] = useState(false);
  const { run, busy, error } = useAction();

  const send = () => run(async () => {
    await api("/auth/otp/send", "POST", signup ? { phone, first_name: first, last_name: last } : { phone });
    setSent(true);
  });
  const verify = () => run(async () => {
    const res = await api<{ token: string }>("/auth/otp/verify", "POST", { phone, code });
    setToken(res.token);
    window.location.href = "/";
  });

  return (
    <main className="main" style={{ maxWidth: 420, margin: "40px auto" }}>
      <div className="card">
        <h1>{fa.login.title}</h1>
        <Field label={fa.login.phone}>
          <input type="tel" className="ltr" inputMode="numeric" placeholder="09xxxxxxxxx" value={phone}
            onChange={(e) => setPhone(e.target.value.trim())} />
        </Field>
        {signup && !sent ? (
          <>
            <Field label={fa.login.firstName}><input type="text" value={first} onChange={(e) => setFirst(e.target.value)} /></Field>
            <Field label={fa.login.lastName}><input type="text" value={last} onChange={(e) => setLast(e.target.value)} /></Field>
          </>
        ) : null}
        {sent ? (
          <>
            <Field label={fa.login.code}>
              <input type="text" className="ltr" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value.trim())} />
            </Field>
            <button className="btn" disabled={busy || !code} onClick={verify}>{fa.login.verify}</button>
            {process.env.NODE_ENV !== "production" ? <p className="muted">{fa.login.devHint}</p> : null}
          </>
        ) : (
          <button className="btn" disabled={busy || !phone} onClick={send}>{signup ? fa.login.signup : fa.login.sendCode}</button>
        )}
        <ErrorLine text={error} />
        {!sent && !signup ? (
          <p><button className="btn ghost small" onClick={() => setSignup(true)}>{fa.login.signupTitle}</button></p>
        ) : null}
      </div>
    </main>
  );
}
