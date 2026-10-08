"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { dateTimeFa, num } from "@/lib/format";
import { useAction, useLoad } from "@/components/hooks";
import { ErrorLine, Tabs } from "@/components/ui";

interface Jobs { counts: Record<string, number>; jobs: { id: string; kind: string; queue: string; attempts: number; error: string | null; created_at: string }[] }

export default function AdminPage() {
  const [status, setStatus] = useState("failed");
  const jobs = useLoad<Jobs>(`/admin/jobs?status=${status}`);
  const { run, busy, error } = useAction();
  return (
    <main className="main">
      <h1>{fa.admin.title}</h1>
      <Tabs items={Object.entries(fa.admin.statuses).map(([id, label]) => ({ id, label: `${label} ${num(jobs.data?.counts[id] ?? 0)}` }))}
        value={status} onChange={setStatus} />
      <ErrorLine text={jobs.error ?? error} />
      <div className="card table-wrap"><table><tbody>{jobs.data?.jobs.map((j) => (
        <tr key={j.id}><td className="ltr">{j.kind}</td><td>{j.queue}</td><td>{num(j.attempts)}</td><td>{dateTimeFa(j.created_at)}</td>
          <td className="ltr" style={{ maxWidth: 420, whiteSpace: "pre-wrap" }}>{j.error}</td>
          <td>{status === "failed" ? <button className="btn small" disabled={busy} onClick={() => run(async () => {
            await api(`/admin/jobs/${j.id}/retry`, "POST");
            await jobs.reload();
          })}>{fa.admin.retry}</button> : null}</td></tr>
      ))}</tbody></table></div>
    </main>
  );
}
