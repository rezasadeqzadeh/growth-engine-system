"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { addDays, dateFa, dayNumFa, iranWeekday, jalaliToday, monthFa, pct } from "@/lib/format";
import type { Slot } from "@/lib/types";
import { useAction, useLoad } from "@/components/hooks";
import { ErrorLine, Loading } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

interface Month {
  start: string; end: string; slots: Slot[]; balance: Record<string, number>;
  occasions: { day: string; name: string; tone: string }[];
}

export default function CalendarPage() {
  const { ws } = useWorkspace();
  const [ym, setYm] = useState(jalaliToday());
  const month = useLoad<Month>(`/workspaces/${ws.id}/calendar?year=${ym.year}&month=${ym.month}`);
  const { run, busy, error } = useAction();
  const [dragging, setDragging] = useState<string | null>(null);
  const [open, setOpen] = useState<Slot | null>(null);
  const kit = useLoad<{ pillars: { key: string; name: string }[] }>(`/workspaces/${ws.id}/brand-kit`);
  const pillarName = (key: string) => kit.data?.pillars.find((p) => p.key === key)?.name ?? key;

  const shift = (delta: number) => setYm(({ year, month: m }) => {
    const index = year * 12 + (m - 1) + delta;
    return { year: Math.floor(index / 12), month: (index % 12) + 1 };
  });
  const move = (slotId: string, day: string) => run(async () => {
    await api(`/workspaces/${ws.id}/calendar/slots/${slotId}`, "PATCH", { day });
    await month.reload();
  });

  const data = month.data;
  const days: string[] = [];
  if (data) for (let d = data.start; d <= data.end; d = addDays(d, 1)) days.push(d);
  const lead = data ? iranWeekday(data.start) : 0;

  return (
    <>
      <div className="spread">
        <h1>{fa.calendar.title} {data ? <span className="muted">· {monthFa(`${data.start}T12:00:00Z`)}</span> : null}</h1>
        <div className="row no-print">
          <button className="btn ghost small" onClick={() => shift(-1)}>{fa.calendar.prev}</button>
          <button className="btn ghost small" onClick={() => shift(1)}>{fa.calendar.next}</button>
          <button className="btn" disabled={busy} onClick={() => run(async () => {
            await api(`/workspaces/${ws.id}/calendar/generate`, "POST", ym);
            await month.reload();
          })}>{busy ? fa.calendar.generating : fa.calendar.generate}</button>
        </div>
      </div>
      {data ? (
        <div className="row" style={{ marginBottom: 12 }}>
          {(["attract", "trust", "convert"] as const).map((g) => (
            <span key={g} className="chip" style={{ background: `var(--${g})`, color: "#fff" }}>
              {fa.brand.goals[g]} {pct(data.balance[g] ?? 0)}
            </span>
          ))}
        </div>
      ) : null}
      <ErrorLine text={month.error ?? error} />
      {month.loading && !data ? <Loading /> : null}
      {data ? (
        <div className="cal">
          {fa.calendar.weekdays.map((w) => <div key={w} className="head">{w}</div>)}
          {Array.from({ length: lead }, (_, i) => <div key={`b${i}`} className="day blank" />)}
          {days.map((day) => {
            const occ = data.occasions.find((o) => o.day === day);
            return (
              <div key={day} className="day" onDragOver={(e) => e.preventDefault()}
                onDrop={() => { if (dragging) void move(dragging, day); setDragging(null); }}>
                <div className="n">{dayNumFa(day)}</div>
                {occ ? <div className="occ">{occ.name}</div> : null}
                {data.slots.filter((s) => s.day === day).map((s) => (
                  <div key={s.id} draggable onDragStart={() => setDragging(s.id)} onClick={() => setOpen(s)}
                    role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") setOpen(s); }}
                    className={`slot ${s.kind === "story" ? "story" : s.goal ?? ""} ${s.needs_media && !s.post_id ? "waiting" : ""}`}
                    title={`${fa.calendar.kinds[s.kind]} · ${s.tag ? `#${s.tag}` : ""} · ${s.title}${s.note ? ` · ${s.note}` : ""}`}>
                    {s.needs_media && !s.post_id ? "⏳ " : ""}{fa.calendar.kinds[s.kind]}: {s.title || (s.tag ? `#${s.tag}` : "")}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      ) : null}
      <p className="muted">{fa.calendar.legend}</p>
      {open ? (
        <div className="overlay" onClick={() => setOpen(null)}>
          <div className="card dialog" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
            <div className="spread">
              <h2>{open.title || fa.calendar.kinds[open.kind]}</h2>
              <button className="btn ghost small" onClick={() => setOpen(null)}>{fa.common.close}</button>
            </div>
            <table><tbody>
              <tr><th>{fa.calendar.day}</th><td>{dateFa(`${open.day}T12:00:00Z`)}</td></tr>
              <tr><th>{fa.calendar.kind}</th><td>{fa.calendar.kinds[open.kind]}</td></tr>
              {open.goal ? <tr><th>{fa.tags.goal}</th><td><span className={`chip goal-${open.goal}`}>{fa.brand.goals[open.goal]}</span></td></tr> : null}
              {open.tag ? <tr><th>{fa.tags.tag}</th><td>#{open.tag}</td></tr> : null}
              {open.pillar ? <tr><th>{fa.tags.pillar}</th><td>{pillarName(open.pillar)}</td></tr> : null}
              {open.occasion ? <tr><th>{fa.calendar.occasion}</th><td>{open.occasion}</td></tr> : null}
              {open.note ? <tr><th>{fa.calendar.note}</th><td>{open.note}</td></tr> : null}
              <tr><th>{fa.calendar.status}</th><td>
                {open.post_id ? fa.calendar.hasPost : open.needs_media
                  ? `${fa.calendar.waiting}${open.requested ? ` · ${fa.calendar.requested}` : ""}` : fa.calendar.ready}
              </td></tr>
            </tbody></table>
            <div className="row" style={{ marginTop: 12 }}>
              {open.post_id ? <Link className="btn" href={`/w/${ws.id}/queue`}>{fa.calendar.openPost}</Link> : null}
              <button className="btn danger" disabled={busy} onClick={() => run(async () => {
                await api(`/workspaces/${ws.id}/calendar/slots/${open.id}`, "DELETE");
                setOpen(null);
                await month.reload();
              })}>{fa.common.delete}</button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
