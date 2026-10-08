"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { dateTimeFa, num } from "@/lib/format";
import { useAction, useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Loading } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

interface Item {
  id: string; channel_type: string; author: string; text: string; at: string; category: string | null;
  suggested_reply: string | null; handled: boolean; alerted: boolean; can_send: boolean;
}

function Row({ wsId, item, onChange }: { wsId: string; item: Item; onChange: () => void }) {
  const [reply, setReply] = useState(item.suggested_reply ?? "");
  const [copied, setCopied] = useState(false);
  const { run, busy, error } = useAction();
  const base = `/workspaces/${wsId}/feedback/${item.id}`;
  return (
    <div className="card" style={{ opacity: item.handled ? 0.6 : 1 }}>
      <div className="spread">
        <div className="row">
          <span className={`chip ${item.category === "purchase_question" ? "warn" : item.category === "criticism" ? "bad" : ""}`}>
            {fa.feedback.categories[item.category ?? "unsorted"]}
          </span>
          <strong>{item.author || "—"}</strong>
          <span className="muted">{fa.channels.names[item.channel_type]} · {dateTimeFa(item.at)}</span>
        </div>
        {item.alerted ? <span className="chip bad">{fa.feedback.alerted}</span> : null}
      </div>
      <p>«{item.text}»</p>
      {item.suggested_reply !== null || item.category === "purchase_question" ? (
        <>
          <span className="muted">💡 {fa.feedback.suggestion}</span>
          <textarea rows={3} value={reply} onChange={(e) => setReply(e.target.value)} />
        </>
      ) : null}
      {!item.handled ? (
        <div className="row" style={{ marginTop: 8 }}>
          {reply ? <button className="btn small ghost" onClick={async () => {
            await navigator.clipboard.writeText(reply);
            setCopied(true);
            await run(() => api(`${base}/handled`, "POST"));
            onChange();
          }}>{copied ? fa.common.copied : fa.feedback.copySend}</button> : null}
          {reply && item.can_send ? <button className="btn small" disabled={busy}
            onClick={() => run(async () => { await api(`${base}/reply`, "POST", { text: reply }); onChange(); })}>{fa.feedback.sendBot}</button> : null}
          <button className="btn small ghost" disabled={busy}
            onClick={() => run(async () => { await api(`${base}/handled`, "POST"); onChange(); })}>{fa.feedback.handled}</button>
          <button className="btn small ghost" disabled={busy}
            onClick={() => run(async () => { await api(`${base}/to-idea`, "POST"); onChange(); })}>{fa.feedback.toIdea}</button>
        </div>
      ) : null}
      <ErrorLine text={error} />
    </div>
  );
}

export default function FeedbackPage() {
  const { ws } = useWorkspace();
  const [category, setCategory] = useState<string>("");
  const list = useLoad<{ items: Item[]; counts: Record<string, number> }>(
    `/workspaces/${ws.id}/feedback${category ? `?category=${category}` : ""}`);
  return (
    <>
      <h1>{fa.feedback.title}</h1>
      <div className="row" style={{ marginBottom: 12 }}>
        <button className={`btn small ${category ? "ghost" : ""}`} onClick={() => setCategory("")}>{fa.feedback.all}</button>
        {["purchase_question", "praise", "criticism", "idea", "other"].map((c) => (
          <button key={c} className={`btn small ${category === c ? "" : "ghost"}`} onClick={() => setCategory(c)}>
            {fa.feedback.categories[c]} {num(list.data?.counts[c] ?? 0)}
          </button>
        ))}
      </div>
      {list.loading && !list.data ? <Loading /> : null}
      <ErrorLine text={list.error} />
      {list.data?.items.length === 0 ? <Empty /> : null}
      {list.data?.items.map((item) => <Row key={item.id} wsId={ws.id} item={item} onChange={() => list.reload()} />)}
    </>
  );
}
