"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { num, toman } from "@/lib/format";
import { useAction, useLoad } from "@/components/hooks";
import { ErrorLine, Field } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { DigitInput } from "@/components/DigitInput";

type Plans = Record<string, { price_toman: number; videos: number; ai_calls: number }>;
interface Settings {
  auto_approve_consent?: boolean; home_city?: string; best_hour?: number;
  weekly_slots?: { post: number; reel: number; story: number };
  baseline?: { registrations?: number; admin_hours_per_week?: number };
}

export default function SettingsPage() {
  const { ws, reload } = useWorkspace();
  const plans = useLoad<{ plans: Plans }>("/plans");
  const [s, setS] = useState<Settings>(ws.settings as Settings);
  const [saved, setSaved] = useState(false);
  const { run, busy, error } = useAction();
  const result = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("result") : null;
  useEffect(() => setS(ws.settings as Settings), [ws.settings]);

  const slots = s.weekly_slots ?? { post: 3, reel: 1, story: 5 };
  const save = () => run(async () => {
    const body: Record<string, unknown> = { home_city: s.home_city ?? "", weekly_slots: slots, baseline: s.baseline ?? {} };
    if (ws.role === "owner") body.auto_approve_consent = !!s.auto_approve_consent;
    await api(`/workspaces/${ws.id}`, "PATCH", { settings: body });
    await reload();
    setSaved(true);
  });

  return (
    <>
      <h1>{fa.settings.title}</h1>
      {result === "paid" ? <p className="okText">{fa.settings.paid}</p> : null}
      {result === "failed" ? <p className="error">{fa.settings.payFailed}</p> : null}
      <div className="grid2">
        <div className="card">
          <h2>{fa.settings.plan}: {fa.settings.plans[ws.plan] ?? ws.plan}</h2>
          <h3>{fa.settings.usage}</h3>
          <p>{fa.settings.videos}: {num(ws.usage?.videos?.used ?? 0)} / {num(ws.usage?.videos?.limit ?? 0)}</p>
          <p>{fa.settings.aiCalls}: {num(ws.usage?.ai_calls?.used ?? 0)} / {num(ws.usage?.ai_calls?.limit ?? 0)}</p>
          {Object.entries(plans.data?.plans ?? {}).filter(([id]) => id !== "free" && (id !== "agency" || ws.agency_id)).map(([id, p]) => (
            <div key={id} className="spread" style={{ borderTop: "1px solid var(--line)", padding: "8px 0" }}>
              <span><strong>{fa.settings.plans[id]}</strong> · {num(p.videos)} {fa.settings.videos} · {toman(p.price_toman)} {fa.settings.perMonth}</span>
              {ws.role === "owner" ? <button className="btn small" disabled={busy || ws.plan === id} onClick={() => run(async () => {
                const res = await api<{ payment_url: string }>(`/workspaces/${ws.id}/billing/start`, "POST", { plan: id });
                window.location.href = res.payment_url;
              })}>{fa.settings.buy}</button> : null}
            </div>
          ))}
        </div>
        <div className="card">
          <label className="row" style={{ marginBottom: 12 }}>
            <input type="checkbox" checked={!!s.auto_approve_consent} disabled={ws.role !== "owner"}
              onChange={(e) => setS({ ...s, auto_approve_consent: e.target.checked })} /> {fa.settings.consent}
          </label>
          <Field label={fa.settings.homeCity}><input type="text" value={s.home_city ?? ""} onChange={(e) => setS({ ...s, home_city: e.target.value })} /></Field>
          <p className="muted">{fa.settings.bestHour}: {num(s.best_hour ?? 20)}:{num(30)}</p>
          <h3>{fa.settings.weeklySlots}</h3>
          <div className="row">
            {(["post", "reel", "story"] as const).map((k) => (
              <Field key={k} label={k === "post" ? fa.settings.posts : k === "reel" ? fa.settings.reels : fa.settings.stories}>
                <DigitInput numeric min={0} max={14} value={slots[k]} style={{ width: 80 }}
                  onChange={(e) => setS({ ...s, weekly_slots: { ...slots, [k]: Number(e.target.value) } })} />
              </Field>
            ))}
          </div>
          <h3>{fa.settings.baseline}</h3>
          <div className="row">
            <Field label={fa.settings.baseRegs}><DigitInput numeric min={0} value={s.baseline?.registrations ?? ""}
              onChange={(e) => setS({ ...s, baseline: { ...s.baseline, registrations: Number(e.target.value) } })} /></Field>
            <Field label={fa.settings.baseHours}><DigitInput numeric min={0} value={s.baseline?.admin_hours_per_week ?? ""}
              onChange={(e) => setS({ ...s, baseline: { ...s.baseline, admin_hours_per_week: Number(e.target.value) } })} /></Field>
          </div>
          <button className="btn" disabled={busy} onClick={save}>{fa.common.save}</button>
          {saved ? <p className="okText">{fa.common.saved}</p> : null}
          <ErrorLine text={error} />
        </div>
      </div>
    </>
  );
}
