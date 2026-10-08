"use client";

import { fa, fill } from "@/lib/fa";
import { num, pct, toman } from "@/lib/format";
import { useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Loading, Stat } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

interface Dashboard {
  registrations: number; revenue_toman: number; tracked_revenue_toman: number; outside_city: number;
  admin_minutes_per_week: number; baseline: { registrations?: number; admin_hours_per_week?: number; outside_city?: number };
  funnel: { step: string; value: number }[]; bottleneck: { from: string; to: string; rate: number } | null;
  by_source: { key: string; count: number }[]; by_channel: { key: string; count: number }[];
  attention: Record<string, number>;
}

function sourceLabel(key: string): string {
  const [kind, value] = key.split(":");
  if (kind === "tag") return `#${value}`;
  if (kind === "coupon") return `${fa.dashboard.coupon} ${value}`;
  if (kind === "channel") return fa.channels.names[value ?? ""] ?? value ?? "";
  return fa.dashboard.direct;
}

function Bars({ rows, label }: { rows: { key: string; count: number }[]; label: (k: string) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (rows.length === 0) return <Empty />;
  return (
    <div>
      {rows.map((r) => (
        <div key={r.key} style={{ marginBottom: 8 }}>
          <div className="spread"><span>{label(r.key)}</span><strong>{num(r.count)}</strong></div>
          <div className="bar"><div style={{ width: `${(100 * r.count) / max}%` }} /></div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const { ws } = useWorkspace();
  const { data, error, loading } = useLoad<Dashboard>(`/workspaces/${ws.id}/dashboard?days=30`);
  if (loading) return <Loading />;
  if (error || !data) return <ErrorLine text={error} />;
  const base = data.baseline;
  const top = Math.max(1, data.funnel[0]?.value ?? 1);
  return (
    <>
      <div className="spread">
        <h1>{fa.dashboard.title} <span className="muted">· {fa.dashboard.period}</span></h1>
        <button className="btn ghost no-print" onClick={() => window.print()}>{fa.common.print}</button>
      </div>
      <div className="stats">
        <Stat label={fa.dashboard.registrations} value={num(data.registrations)}
          note={base.registrations !== undefined ? `${fa.dashboard.baselineFrom} ${num(base.registrations)}` : undefined} />
        <Stat label={fa.dashboard.revenue} value={toman(data.tracked_revenue_toman)} />
        <Stat label={fa.dashboard.outside} value={num(data.outside_city)}
          note={base.outside_city !== undefined ? `${fa.dashboard.baselineFrom} ${num(base.outside_city)}` : undefined} />
        <Stat label={fa.dashboard.adminTime} value={`${num(data.admin_minutes_per_week)} ${fa.dashboard.minutes}`}
          note={base.admin_hours_per_week !== undefined ? `${fa.dashboard.baselineFrom} ${num(base.admin_hours_per_week * 60)} ${fa.dashboard.minutes}` : undefined} />
      </div>
      <div className="grid2">
        <div className="card">
          <h2>{fa.dashboard.funnel}</h2>
          {data.funnel.map((step) => (
            <div key={step.step} style={{ marginBottom: 8 }}>
              <div className="spread"><span>{fa.dashboard.steps[step.step]}</span><strong>{num(step.value)}</strong></div>
              <div className="bar"><div style={{ width: `${(100 * step.value) / top}%` }} /></div>
            </div>
          ))}
          {data.bottleneck ? (
            <p className="chip warn">
              {fa.dashboard.bottleneck}: {fill(fa.dashboard.bottleneckText, {
                from: fa.dashboard.steps[data.bottleneck.from] ?? "", to: fa.dashboard.steps[data.bottleneck.to] ?? "",
                rate: pct(data.bottleneck.rate * 100),
              })}
            </p>
          ) : null}
        </div>
        <div className="card">
          <h2>{fa.dashboard.bySource}</h2>
          <Bars rows={data.by_source} label={sourceLabel} />
        </div>
        <div className="card">
          <h2>{fa.dashboard.byChannel}</h2>
          <Bars rows={data.by_channel} label={(k) => fa.channels.names[k] ?? fa.dashboard.direct} />
        </div>
        <div className="card">
          <h2>{fa.dashboard.attention}</h2>
          <table><tbody>
            {Object.entries(data.attention).map(([k, v]) => (
              <tr key={k}><td>{fa.dashboard.metrics[k]}</td><td>{num(v)}</td></tr>
            ))}
          </tbody></table>
        </div>
      </div>
    </>
  );
}
