"use client";

import Link from "next/link";
import { useState } from "react";
import { api, setToken } from "@/lib/api";
import { fa } from "@/lib/fa";
import type { Workspace } from "@/lib/types";
import { useAction, useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Field, Loading } from "@/components/ui";
import { DigitInput } from "@/components/DigitInput";

export default function Home() {
  const list = useLoad<{ workspaces: Workspace[] }>("/workspaces");
  const verticals = useLoad<{ verticals: Record<string, string> }>("/verticals");
  const [name, setName] = useState("");
  const [vertical, setVertical] = useState("sports_board");
  const [slug, setSlug] = useState("");
  const { run, busy, error } = useAction();

  const create = () => run(async () => {
    const ws = await api<Workspace>("/workspaces", "POST", { name, vertical, slug: slug || null });
    window.location.href = `/w/${ws.id}`;
  });

  return (
    <main className="main" style={{ maxWidth: 760, margin: "0 auto" }}>
      <div className="spread">
        <h1>{fa.workspaces.title}</h1>
        <div className="row">
          <Link href="/agency">{fa.nav.agency}</Link>
          <Link href="/audit">{fa.nav.audits}</Link>
          <button className="btn ghost small" onClick={() => { setToken(null); window.location.href = "/login"; }}>
            {fa.common.signOut}
          </button>
        </div>
      </div>
      {list.loading ? <Loading /> : null}
      <ErrorLine text={list.error} />
      {list.data && list.data.workspaces.length === 0 ? <Empty text={fa.workspaces.none} /> : null}
      {list.data?.workspaces.map((ws) => (
        <Link key={ws.id} href={`/w/${ws.id}`} className="card" style={{ display: "block", textDecoration: "none", color: "inherit" }}>
          <strong>{ws.name}</strong>
          <span className="muted"> · {verticals.data?.verticals[ws.vertical] ?? ws.vertical}</span>
        </Link>
      ))}
      <div className="card">
        <h2>{fa.workspaces.create}</h2>
        <Field label={fa.workspaces.name}><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={fa.workspaces.vertical}>
          <select value={vertical} onChange={(e) => setVertical(e.target.value)}>
            {Object.entries(verticals.data?.verticals ?? {}).map(([id, title]) => <option key={id} value={id}>{title}</option>)}
          </select>
        </Field>
        <Field label={fa.workspaces.slug}>
          <DigitInput type="text" className="ltr" value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} />
        </Field>
        <button className="btn" disabled={busy || name.length < 2} onClick={create}>{fa.workspaces.create}</button>
        <ErrorLine text={error} />
      </div>
    </main>
  );
}
