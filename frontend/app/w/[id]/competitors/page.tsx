"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { num, pct } from "@/lib/format";
import { useAction, useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Field, Loading } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { DigitInput } from "@/components/DigitInput";

interface Competitor {
  id: string; handle: string; name: string; kind: string; followers: number | null; posts_per_week: number | null;
  engagement_rate: number | null; best_hook: string | null; last_collected_at: string | null;
  fetch_status: string; fetch_error: string | null; profile_picture_url: string | null;
}
interface Detail extends Competitor {
  biography: string; website: string | null; media_count: number | null;
  insight: { summary: string; best_types: { type: string; why: string }[]; best_topics: { topic: string; why: string }[]; at: string } | null;
}
interface BestItem {
  content_type: string; topic?: string; posts: number; avg_ratio: number; score: number; reactions: number; pages: string[];
  examples: (CPost & { handle: string })[];
}
const BUSY = ["queued", "fetching", "analyzing"];
interface Analysis {
  patterns: { name: string; ratio?: number; why?: string }[]; gaps: string[];
  suggestions: { text: string; tag: string | null; idea_id: string }[]; at: string;
}
interface CPost {
  id: string; url: string; posted_at: string | null; format: string | null; views: number | null; likes: number | null;
  comments: number | null; caption: string; hook_type: string | null; content_type: string | null; topic: string | null;
  ratio_to_avg: number | null; media_url: string | null;
}
const link = (url: string) => (url.startsWith("http") ? url : null);

const EMPTY_POST = { url: "", views: "", likes: "", comments: "", caption: "", offer_price: "" };

function Details({ wsId, comp, onChange }: { wsId: string; comp: Competitor; onChange: () => void }) {
  const detail = useLoad<Detail>(`/workspaces/${wsId}/competitors/${comp.id}`);
  const posts = useLoad<{ posts: CPost[] }>(`/workspaces/${wsId}/competitors/${comp.id}/posts`);
  const d = detail.data;
  const { reload: reloadDetail } = detail;
  const { reload: reloadPosts } = posts;
  useEffect(() => { void reloadDetail(); void reloadPosts(); }, [comp.fetch_status, reloadDetail, reloadPosts]);
  const [row, setRow] = useState(EMPTY_POST);
  const { run, busy, error } = useAction();
  const toInt = (v: string) => (v ? Number(v) : null);
  return (
    <div className="card">
      <div className="row" style={{ alignItems: "flex-start" }}>
        {d?.profile_picture_url ? <img src={d.profile_picture_url} alt="" width={64} height={64} style={{ borderRadius: "50%" }} /> : null}
        <div>
          <h3>{d?.name || `@${comp.handle}`} <a className="muted ltr" href={`https://www.instagram.com/${comp.handle}/`} target="_blank" rel="noreferrer">@{comp.handle}</a></h3>
          <p className="muted">
            {fa.competitors.followers}: {num(d?.followers)} · {fa.competitors.posts}: {num(d?.media_count)} · {fa.competitors.perWeek}: {num(d?.posts_per_week)}
            {" · "}{fa.competitors.engagement}: {d?.engagement_rate != null ? pct(d.engagement_rate * 100) : "—"}
          </p>
          {d?.biography ? <p style={{ whiteSpace: "pre-line" }}>{d.biography}</p> : null}
          {d?.website ? <a className="ltr" href={d.website} target="_blank" rel="noreferrer">{d.website}</a> : null}
        </div>
      </div>
      {d?.insight ? (
        <div style={{ marginTop: 12 }}>
          <h3>{fa.competitors.insight}</h3>
          <p>{d.insight.summary}</p>
          <div className="grid2">
            <div><strong>{fa.competitors.bestTypes}</strong>
              <ul>{d.insight.best_types.map((b, i) => <li key={i}><strong>{fa.competitors.types[b.type] ?? b.type}</strong>: {b.why}</li>)}</ul></div>
            <div><strong>{fa.competitors.bestTopics}</strong>
              <ul>{d.insight.best_topics.map((b, i) => <li key={i}><strong>{b.topic}</strong>: {b.why}</li>)}</ul></div>
          </div>
        </div>
      ) : null}
      <div className="table-wrap" style={{ marginTop: 12 }}><table>
        <thead><tr><th /><th>{fa.competitors.caption}</th><th>{fa.competitors.format}</th><th>{fa.competitors.contentType}</th>
          <th>{fa.competitors.topic}</th><th>{fa.competitors.likes}</th><th>{fa.competitors.comments}</th><th>{fa.competitors.views}</th>
          <th>×</th><th>{fa.competitors.bestHook}</th></tr></thead>
        <tbody>{posts.data?.posts.map((p) => (
          <tr key={p.id}>
            <td>{p.media_url ? <img src={p.media_url} alt="" width={48} height={48} style={{ objectFit: "cover", borderRadius: 4 }} /> : null}</td>
            <td>{link(p.url) ? <a href={p.url} target="_blank" rel="noreferrer">{p.caption.slice(0, 100) || "↗"}</a> : p.caption.slice(0, 100)}</td>
            <td>{p.format ? fa.competitors.formats[p.format] ?? p.format : "—"}</td>
            <td>{p.content_type ? fa.competitors.types[p.content_type] : "—"}</td><td>{p.topic ?? "—"}</td>
            <td>{num(p.likes)}</td><td>{num(p.comments)}</td><td>{num(p.views)}</td>
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
  const best = useLoad<{ types: BestItem[]; items: BestItem[] }>(`/workspaces/${ws.id}/competitors/best`);
  const { run, busy, error } = useAction();
  const working = data.data?.competitors.some((c) => BUSY.includes(c.fetch_status)) ?? false;
  const { reload } = data;
  const { reload: reloadBest } = best;
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(() => { void reload(); }, 10000);
    return () => { clearInterval(timer); void reloadBest(); };
  }, [working, reload, reloadBest]);
  if (data.loading && !data.data) return <Loading />;
  const analysis = data.data?.analysis;
  return (
    <>
      <div className="spread"><h1>{fa.competitors.title}</h1>
        <div className="row">
          <button className="btn ghost" disabled={busy} onClick={() => run(async () => {
            await api(`/workspaces/${ws.id}/competitors/fetch-all`, "POST");
            setNote(fa.competitors.fetchQueued);
            await data.reload();
          })}>{fa.competitors.fetchAll}</button>
          <button className="btn" disabled={busy} onClick={() => run(async () => {
            await api(`/workspaces/${ws.id}/competitors/analyze`, "POST");
            setNote(fa.competitors.analyzing);
          })}>{fa.competitors.analyze}</button>
        </div></div>
      <p className="muted">{fa.competitors.hint}</p>
      {note ? <p className="okText">{note}</p> : null}
      <ErrorLine text={data.error ?? error} />
      <div className="card table-wrap">
        <table>
          <thead><tr><th>{fa.competitors.handle}</th><th>{fa.competitors.kind}</th><th>{fa.competitors.perWeek}</th>
            <th>{fa.competitors.followers}</th><th>{fa.competitors.engagement}</th><th>{fa.competitors.bestHook}</th>
            <th>{fa.competitors.lastFetched}</th><th /></tr></thead>
          <tbody>{data.data?.competitors.map((c) => (
            <tr key={c.id}><td>@{c.handle}</td><td>{fa.competitors.kinds[c.kind]}</td><td>{num(c.posts_per_week)}</td>
              <td>{num(c.followers)}</td>
              <td>{c.engagement_rate !== null ? pct(c.engagement_rate * 100) : "—"}</td>
              <td>{c.best_hook ? fa.competitors.hooks[c.best_hook] : "—"}</td>
              <td>{fa.competitors.status[c.fetch_status] ?? c.fetch_status}
                {c.fetch_error ? <><br /><span className="error">{fa.competitors.fetchErrors[c.fetch_error] ?? c.fetch_error}</span></> : null}</td>
              <td className="row">
                <button className="btn ghost small" disabled={busy || BUSY.includes(c.fetch_status)} onClick={() => run(async () => {
                  await api(`/workspaces/${ws.id}/competitors/${c.id}/fetch`, "POST");
                  setNote(fa.competitors.fetchQueued);
                  await data.reload();
                })}>{fa.competitors.fetch}</button>
                <button className="btn ghost small" onClick={() => setOpen(open === c.id ? null : c.id)}>{open === c.id ? fa.competitors.hide : fa.competitors.details}</button>
              </td></tr>
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
        <Details key={c.id} wsId={ws.id} comp={c} onChange={() => { void data.reload(); void best.reload(); }} />
      ))}
      {best.data && best.data.items.length ? (
        <div className="card">
          <h2>{fa.competitors.best}</h2>
          <p className="muted">{fa.competitors.bestHint}</p>
          <p>{best.data.types.slice(0, 5).map((ty) => (
            <span key={ty.content_type} className="chip">{fa.competitors.types[ty.content_type]} ×{num(ty.avg_ratio)}</span>
          ))}</p>
          <div className="table-wrap"><table>
            <thead><tr><th>{fa.competitors.contentType}</th><th>{fa.competitors.topic}</th><th>×</th><th>{fa.competitors.posts}</th>
              <th>{fa.competitors.reactions}</th><th>{fa.competitors.pages}</th><th>{fa.competitors.caption}</th><th /></tr></thead>
            <tbody>{best.data.items.map((it) => (
              <tr key={`${it.content_type}:${it.topic}`}>
                <td>{fa.competitors.types[it.content_type]}</td><td>{it.topic}</td><td>×{num(it.avg_ratio)}</td><td>{num(it.posts)}</td>
                <td>{num(it.reactions)}</td><td className="ltr">{it.pages.map((h) => `@${h}`).join(" ")}</td>
                <td>{it.examples.map((ex) => (
                  <div key={ex.id}>{link(ex.url) ? <a href={ex.url} target="_blank" rel="noreferrer">{ex.caption.slice(0, 60) || "↗"}</a> : ex.caption.slice(0, 60)}</div>
                ))}</td>
                <td><button className="btn small" disabled={busy} onClick={() => run(async () => {
                  const idea = await api<{ idea_id: string; text: string }>(`/workspaces/${ws.id}/competitors/inspire`, "POST",
                    { content_type: it.content_type, topic: it.topic });
                  setNote(`${fa.competitors.inspired} ${idea.text}`);
                })}>{fa.competitors.inspire}</button></td>
              </tr>
            ))}</tbody>
          </table></div>
        </div>
      ) : null}
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
