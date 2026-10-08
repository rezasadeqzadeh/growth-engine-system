"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { useAction, useLoad } from "@/components/hooks";
import { ErrorLine, Field } from "@/components/ui";

export default function AuditForm() {
  const verticals = useLoad<{ verticals: Record<string, string> }>("/verticals");
  const [handle, setHandle] = useState("");
  const [vertical, setVertical] = useState("general");
  const [phone, setPhone] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const { run, busy, error } = useAction();
  const agency = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("a") : null;
  const submit = () => run(async () => {
    const form = new FormData();
    form.append("handle", handle);
    form.append("vertical", vertical);
    form.append("phone", phone);
    if (agency) form.append("agency_id", agency);
    files.forEach((f) => form.append("files", f));
    const res = await api<{ slug: string }>("/audits", "POST", form);
    window.location.href = `/audit/${res.slug}`;
  });
  return (
    <main className="main" style={{ maxWidth: 560, margin: "0 auto" }}>
      <div className="card">
        <h1>{fa.audit.title}</h1>
        <p className="muted">{fa.audit.lead}</p>
        <Field label={fa.audit.handle}><input type="text" className="ltr" placeholder="boshrouyeh_kooh" value={handle} onChange={(e) => setHandle(e.target.value)} /></Field>
        <Field label={fa.audit.vertical}>
          <select value={vertical} onChange={(e) => setVertical(e.target.value)}>
            {Object.entries(verticals.data?.verticals ?? {}).map(([id, title]) => <option key={id} value={id}>{title}</option>)}
          </select>
        </Field>
        <Field label={fa.audit.phone}><input type="tel" className="ltr" inputMode="numeric" placeholder="09xxxxxxxxx" value={phone} onChange={(e) => setPhone(e.target.value.trim())} /></Field>
        <Field label={fa.audit.screenshots}>
          <input type="file" accept="image/png,image/jpeg" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 6))} />
        </Field>
        <button className="btn" disabled={busy || !handle || !phone || files.length === 0} onClick={submit}>{fa.audit.submit}</button>
        <ErrorLine text={error} />
      </div>
    </main>
  );
}
