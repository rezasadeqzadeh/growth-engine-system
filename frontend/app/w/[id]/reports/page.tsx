"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { dateFa } from "@/lib/format";
import { useAction, useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Loading } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

interface Report { id: string; period_start: string; period_end: string; text: string; sent: boolean }

export default function ReportsPage() {
  const { ws } = useWorkspace();
  const list = useLoad<{ reports: Report[] }>(`/workspaces/${ws.id}/reports`);
  const [note, setNote] = useState<string | null>(null);
  const { run, busy, error } = useAction();
  return (
    <>
      <div className="spread"><h1>{fa.reports.title}</h1>
        <button className="btn" disabled={busy} onClick={() => run(async () => {
          await api(`/workspaces/${ws.id}/reports/run`, "POST");
          setNote(fa.reports.queued);
        })}>{fa.reports.runNow}</button></div>
      {note ? <p className="okText">{note}</p> : null}
      <ErrorLine text={list.error ?? error} />
      {list.loading && !list.data ? <Loading /> : null}
      {list.data?.reports.length === 0 ? <Empty /> : null}
      {list.data?.reports.map((r) => (
        <div key={r.id} className="card">
          <div className="spread">
            <strong>{dateFa(r.period_start)} — {dateFa(r.period_end)}</strong>
            <span className={`chip ${r.sent ? "ok" : "warn"}`}>{r.sent ? fa.reports.sent : fa.reports.notSent}</span>
          </div>
          <pre className="srt">{r.text}</pre>
        </div>
      ))}
    </>
  );
}
