"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa, fill } from "@/lib/fa";
import { dateTimeFa, num } from "@/lib/format";
import type { PostDetail, PostSummary, QcItem, Recipe, SubtitleLine, Variant } from "@/lib/types";
import { useAction, useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Field, Loading, Tabs } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

type StatusTab = "pending" | "scheduled" | "processing" | "published" | "rejected,failed";
const STATUS_TABS: { id: StatusTab; label: string }[] = [
  { id: "pending", label: fa.queue.pending },
  { id: "scheduled", label: fa.queue.scheduled },
  { id: "processing", label: fa.queue.processing },
  { id: "published", label: fa.queue.published },
  { id: "rejected,failed", label: `${fa.queue.rejected} / ${fa.queue.failed}` },
];

function QcList({ items }: { items: QcItem[] }) {
  return (
    <ul className="qc">
      {items.map((q) => (
        <li key={q.check}>
          <span className={`chip ${q.level === "ok" ? "ok" : q.level === "warn" ? "warn" : "bad"}`}>
            {q.level === "ok" ? "✓" : q.level === "warn" ? "!" : "✗"}
          </span>{" "}
          {fill(fa.qc[q.message] ?? q.message, q.params)}
        </li>
      ))}
    </ul>
  );
}

interface Draft { title: string; caption: string; tags: string }

const draftOf = (v: Variant): Draft => ({ title: v.title, caption: v.caption, tags: v.tags.map((t) => `#${t}`).join(" ") });
const tagsOf = (text: string): string[] => text.split(/[\s,،]+/).map((t) => t.replace(/^#/, "")).filter(Boolean);
const sameDraft = (a: Draft, b: Draft) => a.title === b.title && a.caption === b.caption
  && tagsOf(a.tags).join(" ") === tagsOf(b.tags).join(" ");
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function SubtitleEditor({ base, lines, busy, run, onSaved }: {
  base: string; lines: SubtitleLine[]; busy: boolean;
  run: (fn: () => Promise<unknown>) => Promise<unknown>; onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<SubtitleLine[]>(lines);
  useEffect(() => setDraft(lines), [lines]);
  const changed = draft.some((l, i) => l.text !== lines[i]?.text);
  return (
    <div style={{ marginTop: 16 }}>
      <h3>{fa.queue.editSubtitles}</h3>
      <p className="muted">{fa.queue.editSubtitlesHint}</p>
      {draft.map((l, i) => (
        <div key={`${l.start}-${l.end}`} className="row" style={{ alignItems: "center", marginBottom: 4 }}>
          <span className="muted ltr" style={{ minWidth: 92 }}>{clock(l.start)} – {clock(l.end)}</span>
          <input type="text" value={l.text} style={{ flex: 1 }}
            onChange={(e) => setDraft(draft.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} />
        </div>
      ))}
      <button className="btn small" disabled={busy || !changed} onClick={() => run(async () => {
        await api(`${base}/subtitles`, "PUT", { lines: draft });
        await onSaved();
      })}>{fa.queue.saveSubtitles}</button>
    </div>
  );
}

function PostView({ wsId, postId, onChanged }: { wsId: string; postId: string; onChanged: () => void }) {
  const post = useLoad<PostDetail>(`/workspaces/${wsId}/posts/${postId}`);
  const recipes = useLoad<{ recipes: Recipe[] }>(`/workspaces/${wsId}/recipes`);
  const [tab, setTab] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [instruction, setInstruction] = useState("");
  const [fix, setFix] = useState("");
  const [at, setAt] = useState("");
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const { run, busy, error } = useAction();
  const p = post.data;
  const variant = p?.variants[tab];

  useEffect(() => setDrafts(Object.fromEntries((p?.variants ?? []).map((v) => [v.id, draftOf(v)]))), [p]);
  const dirty = (p?.variants ?? []).filter((v) => {
    const d = drafts[v.id];
    return d !== undefined && !sameDraft(d, draftOf(v));
  });
  const draft = variant ? drafts[variant.id] ?? draftOf(variant) : null;
  const setDraft = (patch: Partial<Draft>) => variant && setDrafts({ ...drafts, [variant.id]: { ...draftOf(variant), ...drafts[variant.id], ...patch } });

  if (post.loading && !p) return <Loading />;
  if (!p) return <ErrorLine text={post.error} />;
  const editable = p.status === "pending" || p.status === "scheduled";
  const base = `/workspaces/${wsId}/posts/${p.id}`;
  const act = (path: string, body?: Record<string, unknown>, message?: string) => run(async () => {
    await api(`${base}${path}`, "POST", body);
    setNote(message ?? null);
    await post.reload();
    onChanged();
  });

  return (
    <div className="card">
      <div className="spread">
        <div>
          <h2>{p.title || "—"}</h2>
          <div className="row">
            {p.tag ? <span className="chip">#{p.tag}</span> : null}
            {p.duration_s ? <span className="muted">{fill(fa.queue.seconds, { n: Math.round(p.duration_s) })}</span> : null}
            {p.scheduled_at ? <span className="muted">{fa.queue.publishAt}: {dateTimeFa(p.scheduled_at)}</span> : null}
          </div>
        </div>
        {editable ? (
          <div className="row no-print">
            <button className="btn ghost" disabled={busy || dirty.length === 0} onClick={() => run(async () => {
              for (const v of dirty) {
                const d = drafts[v.id] ?? draftOf(v);
                await api(`${base}/variants/${v.id}`, "PUT", { title: d.title, caption: d.caption, tags: tagsOf(d.tags) });
              }
              await post.reload();
              setNote(fa.queue.savedAll);
            })}>{fa.queue.saveChanges}{dirty.length ? ` (${num(dirty.length)})` : ""}</button>
            {p.status === "pending" ? <button className="btn" disabled={busy || dirty.length > 0} title={dirty.length ? fa.queue.unsaved : undefined}
              onClick={() => act("/approve")}>{fa.queue.approve}</button> : null}
            <input type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} style={{ width: "auto" }} />
            <button className="btn ghost" disabled={busy || !at}
              onClick={() => act("/schedule", { at: new Date(at).toISOString() })}>{fa.queue.schedule}</button>
          </div>
        ) : null}
      </div>
      {editable && dirty.length ? <p className="chip warn">{fa.queue.unsaved}</p> : null}
      {p.auto_approve_at ? <p className="chip warn">{fa.queue.autoApprove} {dateTimeFa(p.auto_approve_at)}</p> : null}
      {p.tag_guessed && editable ? (
        <div className="row" style={{ margin: "8px 0" }}>
          <span>{fa.queue.tagGuessed}</span>
          {recipes.data?.recipes.map((r) => (
            <button key={r.tag} className={`btn small ${r.tag === p.tag ? "" : "ghost"}`} disabled={busy}
              onClick={() => act("/tag", { tag: r.tag })}>#{r.tag}</button>
          ))}
        </div>
      ) : null}
      <Tabs items={p.variants.map((v, i) => ({ id: String(i), label: `${fa.channels.names[v.channel.type]} · ${fa.queue.kinds[v.kind] ?? v.kind}` }))}
        value={String(tab)} onChange={(id) => setTab(Number(id))} />
      {variant ? (
        <div className="grid2">
          <div>
            {variant.video_url ? <video src={variant.video_url} poster={variant.cover_url ?? undefined} controls playsInline preload="metadata" /> : null}
            {variant.tracked_link ? <p className="muted ltr">{fa.queue.trackedLink}: {variant.tracked_link}</p> : null}
            {variant.publications.map((pub, i) => (
              <p key={i} className={pub.status === "published" ? "okText" : pub.status === "failed" ? "error" : "muted"}>
                {pub.status === "published" ? fa.queue.statusPublished : pub.status === "failed" ? fa.queue.statusFailed : fa.queue.statusHandoff}
                {pub.url ? <> · <a href={pub.url} target="_blank" rel="noreferrer">{pub.url}</a></> : null}
              </p>
            ))}
          </div>
          <div>
            <Field label={fa.queue.editTitle}>
              <input type="text" value={draft?.title ?? ""} maxLength={200} disabled={!editable} onChange={(e) => setDraft({ title: e.target.value })} />
            </Field>
            <Field label={fa.queue.editCaption2}>
              <textarea rows={10} value={draft?.caption ?? ""} disabled={!editable} onChange={(e) => setDraft({ caption: e.target.value })} />
            </Field>
            <Field label={fa.queue.editTags}>
              <input type="text" value={draft?.tags ?? ""} disabled={!editable} onChange={(e) => setDraft({ tags: e.target.value })} />
            </Field>
          </div>
        </div>
      ) : <Empty />}
      {editable ? (
        <div className="grid2 no-print" style={{ marginTop: 12 }}>
          <div>
            <Field label={fa.queue.editCaption}>
              <input type="text" value={instruction} placeholder={fa.queue.instruction} onChange={(e) => setInstruction(e.target.value)} />
            </Field>
            <button className="btn small ghost" disabled={busy || instruction.length < 2}
              onClick={() => act("/caption-edit", { instruction, channel_id: null }, fa.queue.queued)}>{fa.common.send}</button>
          </div>
          <div>
            <Field label={fa.queue.fixSubtitle}>
              <input type="text" value={fix} placeholder={fa.queue.fixHint} onChange={(e) => setFix(e.target.value)} />
            </Field>
            <button className="btn small ghost" disabled={busy || fix.length < 3}
              onClick={() => act("/subtitle-fix", { instruction: fix }, fa.queue.queued)}>{fa.common.send}</button>
          </div>
        </div>
      ) : null}
      <h3 style={{ marginTop: 16 }}>{fa.queue.qc}</h3>
      <QcList items={p.qc} />
      {p.faces > 0 ? <p className="muted">{fill(fa.queue.faces, { n: num(p.faces) })}</p> : null}
      {editable && p.subtitle_lines.length ? (
        <SubtitleEditor base={base} lines={p.subtitle_lines} busy={busy} run={run} onSaved={async () => {
          setNote(fa.queue.subtitlesQueued);
          await post.reload();
          onChanged();
        }} />
      ) : p.subtitles ? (<><h3>{fa.queue.subtitles}</h3><pre className="srt">{p.subtitles}</pre></>) : null}
      {editable ? (
        <div className="row no-print" style={{ marginTop: 12 }}>
          <input type="text" placeholder={fa.queue.rejectReason} value={reason} onChange={(e) => setReason(e.target.value)} style={{ maxWidth: 320 }} />
          <button className="btn danger" disabled={busy} onClick={() => act("/reject", { reason })}>{fa.queue.reject}</button>
        </div>
      ) : null}
      {p.status === "published" ? (
        <div className="row" style={{ marginTop: 12 }}>
          <span>{fa.queue.rate}</span>
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} className={`btn small ${p.rating === n ? "" : "ghost"}`} onClick={() => act("/rate", { score: n })}>{num(n)}</button>
          ))}
        </div>
      ) : null}
      {note ? <p className="okText">{note}</p> : null}
      <ErrorLine text={error} />
    </div>
  );
}

function Upload({ wsId, onDone }: { wsId: string; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [caption, setCaption] = useState("");
  const { run, busy, error } = useAction();
  return (
    <div className="card no-print">
      <h3>{fa.queue.upload}</h3>
      <div className="row">
        <input type="file" accept="video/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <input type="text" value={caption} placeholder={fa.queue.uploadCaption} onChange={(e) => setCaption(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
        <button className="btn" disabled={busy || !file} onClick={() => run(async () => {
          const form = new FormData();
          form.append("file", file as File);
          form.append("caption", caption);
          await api(`/workspaces/${wsId}/posts/upload`, "POST", form);
          setFile(null);
          setCaption("");
          onDone();
        })}>{busy ? fa.queue.uploading : fa.common.send}</button>
      </div>
      <ErrorLine text={error} />
    </div>
  );
}

export default function QueuePage() {
  const { ws } = useWorkspace();
  const [status, setStatus] = useState<StatusTab>("pending");
  const [selected, setSelected] = useState<string | null>(null);
  const list = useLoad<{ posts: PostSummary[] }>(`/workspaces/${ws.id}/posts?status=${status}`);
  return (
    <>
      <div className="spread"><h1>{fa.queue.title}</h1>
        <button className="btn ghost small" onClick={() => list.reload()}>{fa.common.refresh}</button></div>
      <Upload wsId={ws.id} onDone={() => { setStatus("processing"); void list.reload(); }} />
      <Tabs items={STATUS_TABS} value={status} onChange={(s) => { setStatus(s); setSelected(null); }} />
      {list.loading ? <Loading /> : null}
      <ErrorLine text={list.error} />
      <div className="split">
        <div>
          {list.data?.posts.length === 0 ? <Empty /> : null}
          {list.data?.posts.map((p) => (
            <button key={p.id} className="card" onClick={() => setSelected(p.id)}
              style={{ display: "block", width: "100%", textAlign: "start", cursor: "pointer",
                       borderColor: selected === p.id ? "var(--brand)" : undefined }}>
              <strong>{p.title || (p.tag ? `#${p.tag}` : "—")}</strong>
              <div className="muted">{dateTimeFa(p.created_at)}</div>
              {p.qc.some((q) => q.level === "fail") ? <span className="chip bad">✗</span> : null}
            </button>
          ))}
        </div>
        <div>{selected ? <PostView wsId={ws.id} postId={selected} onChanged={() => list.reload()} /> : null}</div>
      </div>
    </>
  );
}
