"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { dateFa, num } from "@/lib/format";
import { useAction, useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Field } from "@/components/ui";
import { DigitInput } from "@/components/DigitInput";

interface Agency { id: string; name: string; white_label: { display_name?: string; primary_color?: string; link_domain?: string } }
interface Client { id: string; name: string; plan: string; pending: number; registrations_month: number; open_questions: number }
interface AuditLead { slug: string; handle: string; phone: string; total: number | null; wants_service: boolean; created_at: string }

function AgencyView({ agency }: { agency: Agency }) {
  const overview = useLoad<{ clients: Client[] }>(`/agencies/${agency.id}/overview`);
  const verticals = useLoad<{ verticals: Record<string, string> }>("/verticals");
  const audits = useLoad<{ audits: AuditLead[] }>("/audits");
  const [label, setLabel] = useState(agency.white_label);
  const [client, setClient] = useState({ name: "", vertical: "sports_board" });
  const { run, busy, error } = useAction();
  return (
    <>
      <div className="card table-wrap">
        <h2>{fa.agency.clients}</h2>
        {overview.data?.clients.length === 0 ? <Empty /> : null}
        <table><thead><tr><th>{fa.workspaces.name}</th><th>{fa.agency.pending}</th><th>{fa.agency.regsMonth}</th><th>{fa.agency.openQuestions}</th></tr></thead>
          <tbody>{overview.data?.clients.map((c) => (
            <tr key={c.id}><td><Link href={`/w/${c.id}`}>{c.name}</Link></td><td>{num(c.pending)}</td><td>{num(c.registrations_month)}</td><td>{num(c.open_questions)}</td></tr>
          ))}</tbody></table>
        <div className="row" style={{ marginTop: 12 }}>
          <input type="text" placeholder={fa.workspaces.name} value={client.name} style={{ maxWidth: 240 }} onChange={(e) => setClient({ ...client, name: e.target.value })} />
          <select value={client.vertical} style={{ maxWidth: 200 }} onChange={(e) => setClient({ ...client, vertical: e.target.value })}>
            {Object.entries(verticals.data?.verticals ?? {}).map(([id, title]) => <option key={id} value={id}>{title}</option>)}
          </select>
          <button className="btn small" disabled={busy || client.name.length < 2} onClick={() => run(async () => {
            await api("/workspaces", "POST", { name: client.name, vertical: client.vertical, agency_id: agency.id });
            setClient({ ...client, name: "" });
            await overview.reload();
          })}>{fa.agency.newClient}</button>
        </div>
      </div>
      <div className="grid2">
        <div className="card">
          <h2>{fa.agency.whiteLabel}</h2>
          <Field label={fa.agency.displayName}><input type="text" value={label.display_name ?? ""} onChange={(e) => setLabel({ ...label, display_name: e.target.value })} /></Field>
          <Field label={fa.agency.color}><input type="color" value={label.primary_color ?? "#8b5e3c"} onChange={(e) => setLabel({ ...label, primary_color: e.target.value })} /></Field>
          <Field label={fa.agency.domain}><DigitInput type="text" className="ltr" value={label.link_domain ?? ""} onChange={(e) => setLabel({ ...label, link_domain: e.target.value })} /></Field>
          <button className="btn" disabled={busy} onClick={() => run(() => api(`/agencies/${agency.id}/white-label`, "PATCH", label))}>{fa.common.save}</button>
          <p className="muted ltr">{typeof window !== "undefined" ? `${window.location.origin}/audit?a=${agency.id}` : ""}</p>
        </div>
        <div className="card table-wrap">
          <h2>{fa.audit.leads}</h2>
          <table><tbody>{audits.data?.audits.map((a) => (
            <tr key={a.slug}><td><Link href={`/audit/${a.slug}`}>@{a.handle}</Link></td><td className="ltr">{a.phone}</td>
              <td>{num(a.total)}</td><td>{a.wants_service ? <span className="chip ok">{fa.audit.wants}</span> : null}</td><td>{dateFa(a.created_at)}</td></tr>
          ))}</tbody></table>
        </div>
      </div>
      <ErrorLine text={error} />
    </>
  );
}

export default function AgencyPage() {
  const mine = useLoad<{ agencies: Agency[] }>("/agencies");
  const [name, setName] = useState("");
  const { run, busy, error } = useAction();
  const agency = mine.data?.agencies[0];
  return (
    <main className="main" style={{ maxWidth: 1100, margin: "0 auto" }}>
      <div className="spread"><h1>{fa.agency.title}</h1><Link href="/">{fa.nav.workspaces}</Link></div>
      <ErrorLine text={mine.error ?? error} />
      {agency ? <AgencyView agency={agency} /> : mine.data ? (
        <div className="card row">
          <input type="text" placeholder={fa.agency.name} value={name} style={{ maxWidth: 280 }} onChange={(e) => setName(e.target.value)} />
          <button className="btn" disabled={busy || name.length < 2} onClick={() => run(async () => {
            await api("/agencies", "POST", { name });
            await mine.reload();
          })}>{fa.agency.create}</button>
        </div>
      ) : null}
    </main>
  );
}
