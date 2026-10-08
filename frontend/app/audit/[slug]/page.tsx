"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa, fill } from "@/lib/fa";
import { num } from "@/lib/format";
import { useLoad } from "@/components/hooks";
import { ErrorLine, Loading } from "@/components/ui";

interface Report {
  slug: string; handle: string; status: string; total: number | null; benchmark: number;
  scores: Record<string, number>; weights: Record<string, number>; followers: number | null; posts_count: number | null;
  fixes: string[]; rewrites: { before: string; after: string }[]; wants_service: boolean;
}

export default function AuditReport({ params }: { params: { slug: string } }) {
  const report = useLoad<Report>(`/audits/${params.slug}`);
  const [message, setMessage] = useState<string | null>(null);
  const status = report.data?.status;
  useEffect(() => {
    if (status !== "queued" && status !== "running") return;
    const timer = setInterval(() => void report.reload(), 5000);
    return () => clearInterval(timer);
  }, [status, report]);

  const r = report.data;
  if (!r) return <main className="main"><ErrorLine text={report.error} />{report.loading ? <Loading /> : null}</main>;
  return (
    <main className="main" style={{ maxWidth: 820, margin: "0 auto" }}>
      <div className="card">
        <h1 className="ltr" style={{ textAlign: "start" }}>@{r.handle}</h1>
        <p className="muted">{num(r.followers)} {fa.audit.followers} · {num(r.posts_count)} {fa.audit.posts}</p>
        {r.status === "failed" ? <p className="error">{fa.audit.failed}</p> : null}
        {r.status !== "done" && r.status !== "failed" ? <p>{fa.audit.waiting}</p> : null}
      </div>
      {r.status === "done" ? (
        <>
          <div className="grid2">
            <div className="card" style={{ textAlign: "center" }}>
              <div className="muted">{fa.audit.score}</div>
              <div className="score">{num(r.total)}</div>
              <div className="muted">{fill(fa.audit.average, { n: num(r.benchmark) })}</div>
            </div>
            <div className="card">
              {Object.entries(r.weights).map(([axis, weight]) => (
                <div key={axis} style={{ marginBottom: 6 }}>
                  <div className="spread"><span>{fa.audit.axes[axis]}</span><span>{num(r.scores[axis] ?? 0)}/{num(weight)}</span></div>
                  <div className="bar"><div style={{ width: `${(100 * (r.scores[axis] ?? 0)) / weight}%` }} /></div>
                </div>
              ))}
            </div>
          </div>
          <div className="grid2">
            <div className="card">
              <h2>{fa.audit.fixes}</h2>
              <ol>{r.fixes.map((f, i) => <li key={i}>{f}</li>)}</ol>
            </div>
            <div className="card">
              <h2>{fa.audit.rewrites}</h2>
              {r.rewrites.map((rw, i) => (
                <div key={i} style={{ marginBottom: 12 }}>
                  <p className="muted">{fa.audit.before} «{rw.before}»</p>
                  <p>{fa.audit.after} «{rw.after}»</p>
                </div>
              ))}
            </div>
          </div>
          <div className="row no-print">
            <button className="btn" disabled={r.wants_service} onClick={async () => {
              const res = await api<{ message: string }>(`/audits/${r.slug}/want-service`, "POST");
              setMessage(res.message);
            }}>{fa.audit.wantService}</button>
            <button className="btn ghost" onClick={() => window.print()}>{fa.common.print}</button>
          </div>
          {message ? <p className="okText">{message}</p> : null}
        </>
      ) : null}
    </main>
  );
}
