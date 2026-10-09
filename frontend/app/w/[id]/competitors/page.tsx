"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { num, pct } from "@/lib/format";
import { useAction, useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Field, Loading } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { DigitInput } from "@/components/DigitInput";

interface Competitor {
  id: string; handle: string; name: string; kind: string; followers: number | null; posts_per_week: number | null;
  engagement_rate: number | null; best_hook: string | null;
}
interface Analysis {
  patterns: { name: string; ratio?: number; why?: string }[]; gaps: string[];
  suggestions: { text: string; tag: string | null; idea_id: string }[]; at: string;
}
interface CPost { id: string; url: string; views: number | null; likes: number | null; caption: string; hook_type: string | null; ratio_to_avg: number | null }

const EMPTY_POST = { url: "", views: "", likes: "", comments: "", caption: "", offer_price: "" };

function Posts({ wsId, comp, onChange }: { wsId: string; comp: Competitor; onChange: () => void }) {
  const posts = useLoad<{ posts: CPost[] }>(`/workspaces/${wsId}/competitors/${comp.id}/posts`);
  const [row, setRow] = useState(EMPTY_POST);
  const { run, busy, error } = useAction();
  const toInt = (v: string) => (v ? Number(v) : null);
  return (
    <div className="card">
      <h3>@{comp.handle}</h3>
      <div className="table-wrap"><table>
        <thead><tr><th>{fa.competitors.caption}</th><th>{fa.competitors.views}</th><th>{fa.competitors.likes}</th><th>×</th><th>{fa.competitors.bestHook}</th></tr></thead>
        <tbody>{posts.data?.posts.map((p) => (
          <tr key={p.id}><td>{p.caption.slice(0, 80)}</td><td>{num(p.views)}</td><td>{num(p.likes)}</td>
            <td>{p.ratio_to_avg ? `×${num(p.ratio_to_avg)}` : "—"}</td><td>{p.hook_type ? fa.competitors.hooks[p.hook_type] : "—"}</td></tr>
        ))}</tbody>
      </table></div>
      <h3 style={{ marginTop: 12 }}>{fa.competitors.addPosts}</h3>
      <div className="grid2">
        <Field label={fa.competitors.url}><DigitInput type="text" className="ltr" value={row.url} onChange={(e) => setRow({ ...row, url: e.target.value })} /></Field>
        <Field label={fa.competitors.caption}><input type="text" value={row.caption} onChange={(e) => setRow({ ...row, caption: e.target.value })} /></Field>
        <Field label={fa.competitors.views}><DigitInput numeric value={row.views} onChange={(e) => setRow({ ...row, views: e.target.value })} /></Field>
        <Field label={fa.competitors.likes}><DigitInput numeric value={row.likes} onChange={(e) => setRow({ ...row, likes: e.target.value })} /></Field>
        <Field label={fa.competitors.comments}><DigitInput numeric value={row.comments} onChange={(e) => setRow({ ...row, comments: e.target.value })} /></Field>
        <Field label={fa.competitors.price}><input type="text" value={row.offer_price} onChange={(e) => setRow({ ...row, offer_price: e.target.value })} /></Field>
      </div>
      <button className="btn small" disabled={busy} onClick={() => run(async () => {
        await api(`/workspaces/${wsId}/competitors/${comp.id}/posts`, "POST", { posts: [{
          url: row.url || null, caption: row.caption, views: toInt(row.views), likes: toInt(row.likes),
          comments: toInt(row.comments), offer_price: row.offer_price || null }] });
        setRow(EMPTY_POST);
        await posts.reload();
        onChange();
      })}>{fa.common.add}</button>
      <Field label={fa.competitors.screenshots}>
        <input type="file" accept="image/png,image/jpeg" multiple onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (!files.length) return;
          void run(async () => {
            const form = new FormData();
            files.forEach((f) => form.append("files", f));
            await api(`/workspaces/${wsId}/competitors/${comp.id}/screenshots`, "POST", form);
            await posts.reload();
            onChange();
          });
        }} />
      </Field>
      <ErrorLine text={error} />
    </div>
  );
}

export default function CompetitorsPage() {
  const { ws } = useWorkspace();
  const data = useLoad<{ competitors: Competitor[]; analysis: Analysis | null }>(`/workspaces/${ws.id}/competitors`);
  const [form, setForm] = useState({ handle: "", kind: "direct", followers: "" });
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const { run, busy, error } = useAction();
  if (data.loading && !data.data) return <Loading />;
  const analysis = data.data?.analysis;
  return (
    <>
      <div className="spread"><h1>{fa.competitors.title}</h1>
        <button className="btn" disabled={busy} onClick={() => run(async () => {
          await api(`/workspaces/${ws.id}/competitors/analyze`, "POST");
          setNote(fa.competitors.analyzing);
        })}>{fa.competitors.analyze}</button></div>
      <p className="muted">{fa.competitors.hint}</p>
      {note ? <p className="okText">{note}</p> : null}
      <ErrorLine text={data.error ?? error} />
      <div className="card table-wrap">
        <table>
          <thead><tr><th>{fa.competitors.handle}</th><th>{fa.competitors.kind}</th><th>{fa.competitors.perWeek}</th>
            <th>{fa.competitors.engagement}</th><th>{fa.competitors.bestHook}</th><th /></tr></thead>
          <tbody>{data.data?.competitors.map((c) => (
            <tr key={c.id}><td>@{c.handle}</td><td>{fa.competitors.kinds[c.kind]}</td><td>{num(c.posts_per_week)}</td>
              <td>{c.engagement_rate !== null ? pct(c.engagement_rate * 100) : "—"}</td>
              <td>{c.best_hook ? fa.competitors.hooks[c.best_hook] : "—"}</td>
              <td><button className="btn ghost small" onClick={() => setOpen(open === c.id ? null : c.id)}>{fa.competitors.addPosts}</button></td></tr>
          ))}</tbody>
        </table>
        <div className="row" style={{ marginTop: 12 }}>
          <DigitInput type="text" className="ltr" placeholder={fa.competitors.handle} value={form.handle} style={{ maxWidth: 220 }}
            onChange={(e) => setForm({ ...form, handle: e.target.value })} />
          <select value={form.kind} style={{ maxWidth: 180 }} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {Object.entries(fa.competitors.kinds).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <DigitInput numeric placeholder={fa.competitors.followers} value={form.followers} style={{ maxWidth: 160 }}
            onChange={(e) => setForm({ ...form, followers: e.target.value })} />
          <button className="btn small" disabled={busy || !form.handle} onClick={() => run(async () => {
            await api(`/workspaces/${ws.id}/competitors`, "POST", { handle: form.handle, kind: form.kind,
              followers: form.followers ? Number(form.followers) : null });
            setForm({ handle: "", kind: "direct", followers: "" });
            await data.reload();
          })}>{fa.competitors.add}</button>
        </div>
      </div>
      {data.data?.competitors.filter((c) => c.id === open).map((c) => (
        <Posts key={c.id} wsId={ws.id} comp={c} onChange={() => data.reload()} />
      ))}
      {analysis ? (
        <div className="grid2">
          <div className="card">
            <h2>{fa.competitors.patterns}</h2>
            {analysis.patterns.map((p, i) => (
              <p key={i}><strong>{p.ratio ? `×${num(p.ratio)} ` : ""}{p.name}</strong>{p.why ? <><br /><span className="muted">{p.why}</span></> : null}</p>
            ))}
            <p className="muted">{fa.competitors.ratio}</p>
            <h3>{fa.competitors.gaps}</h3>
            <ul>{analysis.gaps.map((g, i) => <li key={i}>{g}</li>)}</ul>
          </div>
          <div className="card">
            <h2>{fa.competitors.suggestions}</h2>
            {analysis.suggestions.length === 0 ? <Empty /> : null}
            {analysis.suggestions.map((s) => (
              <div key={s.idea_id} style={{ marginBottom: 12 }}>
                <p>{s.text} {s.tag ? <span className="chip">#{s.tag}</span> : null}</p>
                <button className="btn small ghost" disabled={busy} onClick={() => run(async () => {
                  await api(`/workspaces/${ws.id}/competitors/order-video`, "POST", { idea_id: s.idea_id });
                  setNote(fa.competitors.ordered);
                })}>{fa.competitors.orderVideo}</button>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}
