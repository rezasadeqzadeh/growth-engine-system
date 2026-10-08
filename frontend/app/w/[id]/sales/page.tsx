"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { dateTimeFa, num, pct, toman } from "@/lib/format";
import { useAction, useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Field, Tabs } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

type Section = "offers" | "registrations" | "coupons" | "links" | "keywords" | "leads" | "ideas";

interface Offer { id: string; slug: string; title: string; price_toman: number; capacity: number | null; seats_left: number | null; starts_at: string | null; url: string; active: boolean }
interface Reg { id: string; offer: string; name: string; phone: string; city: string; status: string; amount_toman: number; tag: string | null; coupon: string | null; source_link: string | null; paid_at: string | null }

function Offers({ wsId }: { wsId: string }) {
  const list = useLoad<{ offers: Offer[] }>(`/workspaces/${wsId}/offers`);
  const [f, setF] = useState({ title: "", slug: "", price: "", capacity: "", starts: "", description: "" });
  const { run, busy, error } = useAction();
  return (
    <>
      <div className="card table-wrap"><table>
        <thead><tr><th>{fa.sales.offerTitle}</th><th>{fa.sales.startsAt}</th><th>{fa.sales.price}</th><th>{fa.sales.seatsLeft}</th><th /></tr></thead>
        <tbody>{list.data?.offers.map((o) => (
          <tr key={o.id}><td>{o.title}</td><td>{o.starts_at ? dateTimeFa(o.starts_at) : "—"}</td><td>{toman(o.price_toman)}</td>
            <td>{o.seats_left === null ? "—" : num(o.seats_left)}</td><td><a href={o.url} target="_blank" rel="noreferrer">{fa.sales.open}</a></td></tr>
        ))}</tbody>
      </table></div>
      <div className="card grid2">
        <Field label={fa.sales.offerTitle}><input type="text" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label={fa.sales.slug}><input type="text" className="ltr" value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value.toLowerCase() })} /></Field>
        <Field label={fa.sales.price}><input type="number" min={0} value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></Field>
        <Field label={fa.sales.capacity}><input type="number" min={1} value={f.capacity} onChange={(e) => setF({ ...f, capacity: e.target.value })} /></Field>
        <Field label={fa.sales.startsAt}><input type="datetime-local" value={f.starts} onChange={(e) => setF({ ...f, starts: e.target.value })} /></Field>
        <Field label={fa.sales.description}><textarea rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div><button className="btn" disabled={busy || !f.title || !f.slug} onClick={() => run(async () => {
          await api(`/workspaces/${wsId}/offers`, "POST", { title: f.title, slug: f.slug, price_toman: Number(f.price || 0),
            capacity: f.capacity ? Number(f.capacity) : null, starts_at: f.starts ? new Date(f.starts).toISOString() : null,
            description: f.description });
          setF({ title: "", slug: "", price: "", capacity: "", starts: "", description: "" });
          await list.reload();
        })}>{fa.common.add}</button><ErrorLine text={error} /></div>
      </div>
    </>
  );
}

function Registrations({ wsId }: { wsId: string }) {
  const list = useLoad<{ registrations: Reg[] }>(`/workspaces/${wsId}/registrations`);
  if (list.data?.registrations.length === 0) return <Empty />;
  return (
    <div className="card table-wrap"><table>
      <thead><tr><th>{fa.sales.offerTitle}</th><th>{fa.team.name}</th><th>{fa.login.phone}</th><th>{fa.sales.city}</th>
        <th>{fa.sales.price}</th><th>{fa.sales.source}</th><th /></tr></thead>
      <tbody>{list.data?.registrations.map((r) => (
        <tr key={r.id}><td>{r.offer}</td><td>{r.name}</td><td className="ltr">{r.phone}</td><td>{r.city}</td><td>{toman(r.amount_toman)}</td>
          <td>{r.coupon ? `${fa.dashboard.coupon} ${r.coupon}` : r.tag ? `#${r.tag}` : r.source_link ?? fa.dashboard.direct}</td>
          <td><span className={`chip ${r.status === "paid" ? "ok" : r.status === "failed" ? "bad" : ""}`}>{fa.sales.status[r.status]}</span></td></tr>
      ))}</tbody>
    </table></div>
  );
}

function Coupons({ wsId }: { wsId: string }) {
  const list = useLoad<{ coupons: { id: string; code: string; influencer: string | null; discount_percent: number }[] }>(`/workspaces/${wsId}/coupons`);
  const [f, setF] = useState({ code: "", influencer: "", discount: "" });
  const { run, busy, error } = useAction();
  return (
    <div className="card">
      <table><tbody>{list.data?.coupons.map((c) => (
        <tr key={c.id}><td className="ltr">{c.code}</td><td>{c.influencer ?? "—"}</td><td>{pct(c.discount_percent)}</td></tr>
      ))}</tbody></table>
      <div className="row" style={{ marginTop: 12 }}>
        <input type="text" className="ltr" placeholder={fa.sales.code} value={f.code} style={{ maxWidth: 160 }} onChange={(e) => setF({ ...f, code: e.target.value })} />
        <input type="text" placeholder={fa.sales.influencer} value={f.influencer} style={{ maxWidth: 180 }} onChange={(e) => setF({ ...f, influencer: e.target.value })} />
        <input type="number" placeholder={fa.sales.discount} value={f.discount} style={{ maxWidth: 120 }} onChange={(e) => setF({ ...f, discount: e.target.value })} />
        <button className="btn small" disabled={busy || !f.code} onClick={() => run(async () => {
          await api(`/workspaces/${wsId}/coupons`, "POST", { code: f.code, influencer: f.influencer || null, discount_percent: Number(f.discount || 0) });
          setF({ code: "", influencer: "", discount: "" });
          await list.reload();
        })}>{fa.common.add}</button>
      </div>
      <ErrorLine text={error} />
    </div>
  );
}

function Links({ wsId }: { wsId: string }) {
  const list = useLoad<{ links: { id: string; url: string; target: string; tag: string | null; channel_type: string | null; influencer: string | null; label: string; clicks: number }[] }>(`/workspaces/${wsId}/links`);
  const [f, setF] = useState({ target: "", label: "", influencer: "" });
  const { run, busy, error } = useAction();
  return (
    <div className="card table-wrap">
      <table>
        <thead><tr><th>{fa.queue.trackedLink}</th><th>{fa.sales.label}</th><th>{fa.sales.target}</th><th>{fa.sales.clicks}</th></tr></thead>
        <tbody>{list.data?.links.map((l) => (
          <tr key={l.id}><td className="ltr">{l.url}</td><td>{l.label || (l.tag ? `#${l.tag}` : "") || l.influencer || (l.channel_type ? fa.channels.names[l.channel_type] : "")}</td>
            <td className="ltr" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" }}>{l.target}</td><td>{num(l.clicks)}</td></tr>
        ))}</tbody>
      </table>
      <div className="row" style={{ marginTop: 12 }}>
        <input type="text" className="ltr" placeholder={fa.sales.target} value={f.target} style={{ flex: 2 }} onChange={(e) => setF({ ...f, target: e.target.value })} />
        <input type="text" placeholder={fa.sales.label} value={f.label} style={{ flex: 1 }} onChange={(e) => setF({ ...f, label: e.target.value })} />
        <input type="text" placeholder={fa.sales.influencer} value={f.influencer} style={{ flex: 1 }} onChange={(e) => setF({ ...f, influencer: e.target.value })} />
        <button className="btn small" disabled={busy || f.target.length < 8} onClick={() => run(async () => {
          await api(`/workspaces/${wsId}/links`, "POST", { target_url: f.target, label: f.label, influencer: f.influencer || null });
          setF({ target: "", label: "", influencer: "" });
          await list.reload();
        })}>{fa.common.add}</button>
      </div>
      <ErrorLine text={error} />
    </div>
  );
}

function Keywords({ wsId }: { wsId: string }) {
  const list = useLoad<{ keywords: { id: string; keyword: string; reply_text: string }[] }>(`/workspaces/${wsId}/keywords`);
  const [f, setF] = useState({ keyword: "", reply: "" });
  const { run, busy, error } = useAction();
  return (
    <div className="card">
      <p className="muted">{fa.sales.keywordHint}</p>
      {list.data?.keywords.map((k) => (
        <div key={k.id} className="spread" style={{ borderBottom: "1px solid var(--line)", padding: "6px 0" }}>
          <span><strong>{k.keyword}</strong> → {k.reply_text}</span>
          <button className="btn ghost small" onClick={() => run(async () => { await api(`/workspaces/${wsId}/keywords/${k.id}`, "DELETE"); await list.reload(); })}>{fa.common.delete}</button>
        </div>
      ))}
      <Field label={fa.sales.keyword}><input type="text" value={f.keyword} onChange={(e) => setF({ ...f, keyword: e.target.value })} /></Field>
      <Field label={fa.sales.reply}><textarea rows={3} value={f.reply} onChange={(e) => setF({ ...f, reply: e.target.value })} /></Field>
      <button className="btn small" disabled={busy || !f.keyword || !f.reply} onClick={() => run(async () => {
        await api(`/workspaces/${wsId}/keywords`, "POST", { keyword: f.keyword, reply_text: f.reply });
        setF({ keyword: "", reply: "" });
        await list.reload();
      })}>{fa.common.add}</button>
      <ErrorLine text={error} />
    </div>
  );
}

function Leads({ wsId }: { wsId: string }) {
  const list = useLoad<{ leads: { id: string; platform: string; name: string; keyword: string | null; at: string }[] }>(`/workspaces/${wsId}/leads`);
  if (list.data?.leads.length === 0) return <Empty />;
  return (
    <div className="card table-wrap"><table><tbody>{list.data?.leads.map((l) => (
      <tr key={l.id}><td>{l.name || "—"}</td><td>{fa.channels.names[l.platform]}</td><td>{l.keyword}</td><td>{dateTimeFa(l.at)}</td></tr>
    ))}</tbody></table></div>
  );
}

function Ideas({ wsId }: { wsId: string }) {
  const list = useLoad<{ ideas: { id: string; text: string; source: string; used: boolean; tag: string | null }[] }>(`/workspaces/${wsId}/ideas`);
  const [text, setText] = useState("");
  const { run, busy } = useAction();
  return (
    <div className="card">
      {list.data?.ideas.map((i) => (
        <p key={i.id} style={{ opacity: i.used ? 0.5 : 1 }}>{i.text} {i.tag ? <span className="chip">#{i.tag}</span> : null}</p>
      ))}
      <div className="row">
        <input type="text" value={text} style={{ flex: 1 }} onChange={(e) => setText(e.target.value)} />
        <button className="btn small" disabled={busy || text.length < 2} onClick={() => run(async () => {
          await api(`/workspaces/${wsId}/ideas`, "POST", { text });
          setText("");
          await list.reload();
        })}>{fa.common.add}</button>
      </div>
    </div>
  );
}

export default function SalesPage() {
  const { ws } = useWorkspace();
  const [section, setSection] = useState<Section>("offers");
  const items: { id: Section; label: string }[] = [
    { id: "offers", label: fa.sales.offers }, { id: "registrations", label: fa.sales.registrations },
    { id: "coupons", label: fa.sales.coupons }, { id: "links", label: fa.sales.links },
    { id: "keywords", label: fa.sales.keywords }, { id: "leads", label: fa.sales.leads }, { id: "ideas", label: fa.sales.ideas },
  ];
  return (
    <>
      <h1>{fa.sales.title}</h1>
      <Tabs items={items} value={section} onChange={setSection} />
      {section === "offers" ? <Offers wsId={ws.id} /> : null}
      {section === "registrations" ? <Registrations wsId={ws.id} /> : null}
      {section === "coupons" ? <Coupons wsId={ws.id} /> : null}
      {section === "links" ? <Links wsId={ws.id} /> : null}
      {section === "keywords" ? <Keywords wsId={ws.id} /> : null}
      {section === "leads" ? <Leads wsId={ws.id} /> : null}
      {section === "ideas" ? <Ideas wsId={ws.id} /> : null}
    </>
  );
}
