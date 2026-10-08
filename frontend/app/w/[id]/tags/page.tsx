"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fa } from "@/lib/fa";
import { num } from "@/lib/format";
import type { Recipe } from "@/lib/types";
import { useAction, useLoad } from "@/components/hooks";
import { ErrorLine, Field, Loading } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

const CHANNELS = ["instagram", "bale", "telegram", "aparat", "eitaa", "rubika", "site"];
const BLANK: Recipe = {
  tag: "", goal: "trust", pillar: null, caption_style: "", cta: "",
  video_spec: { min_s: 15, max_s: 60, aspects: ["9:16"], subtitle_mode: "sentence", overlay: "title", music: false },
  channels: ["instagram", "telegram"], timing: { mode: "best_hour" }, low_risk: false,
};

function Editor({ wsId, initial, onSaved }: { wsId: string; initial: Recipe; onSaved: () => void }) {
  const [r, setR] = useState<Recipe>(initial);
  const { run, busy, error } = useAction();
  const spec = r.video_spec;
  const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);
  const save = () => run(async () => {
    const { id, ...body } = r;
    await api(`/workspaces/${wsId}/recipes${id ? `/${id}` : ""}`, id ? "PUT" : "POST", body);
    onSaved();
  });
  return (
    <div className="card">
      <div className="grid2">
        <div>
          <Field label={fa.tags.tag}><input type="text" value={r.tag} onChange={(e) => setR({ ...r, tag: e.target.value.replace(/^#/, "").replace(/\s+/g, "_") })} /></Field>
          <Field label={fa.tags.goal}>
            <select value={r.goal} onChange={(e) => setR({ ...r, goal: e.target.value })}>
              {Object.entries(fa.brand.goals).map(([g, label]) => <option key={g} value={g}>{label}</option>)}
            </select>
          </Field>
          <Field label={fa.tags.style}><textarea rows={2} value={r.caption_style} onChange={(e) => setR({ ...r, caption_style: e.target.value })} /></Field>
          <Field label={fa.tags.cta}><input type="text" value={r.cta} onChange={(e) => setR({ ...r, cta: e.target.value })} /></Field>
        </div>
        <div>
          <div className="row">
            <Field label={`${fa.tags.length} · ${fa.tags.min}`}><input type="number" min={5} value={spec.min_s ?? 15}
              onChange={(e) => setR({ ...r, video_spec: { ...spec, min_s: Number(e.target.value) } })} /></Field>
            <Field label={fa.tags.max}><input type="number" min={5} value={spec.max_s ?? 60}
              onChange={(e) => setR({ ...r, video_spec: { ...spec, max_s: Number(e.target.value) } })} /></Field>
          </div>
          <Field label={fa.tags.aspects}>
            <div className="row">{["9:16", "16:9"].map((a) => (
              <label key={a} className="row"><input type="checkbox" checked={(spec.aspects ?? []).includes(a)}
                onChange={() => setR({ ...r, video_spec: { ...spec, aspects: toggle(spec.aspects ?? [], a) } })} /> <span className="ltr">{a}</span></label>
            ))}</div>
          </Field>
          <Field label={fa.tags.subtitle}>
            <select value={spec.subtitle_mode ?? "sentence"} onChange={(e) => setR({ ...r, video_spec: { ...spec, subtitle_mode: e.target.value } })}>
              {Object.entries(fa.tags.subtitleModes).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label={fa.tags.overlay}>
            <select value={spec.overlay ?? "none"} onChange={(e) => setR({ ...r, video_spec: { ...spec, overlay: e.target.value } })}>
              {Object.entries(fa.tags.overlays).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <label className="row"><input type="checkbox" checked={!!spec.music}
            onChange={(e) => setR({ ...r, video_spec: { ...spec, music: e.target.checked } })} /> {fa.tags.music}</label>
        </div>
        <div>
          <Field label={fa.tags.channels}>
            <div className="row">{CHANNELS.map((c) => (
              <label key={c} className="row"><input type="checkbox" checked={r.channels.includes(c)}
                onChange={() => setR({ ...r, channels: toggle(r.channels, c) })} /> {fa.channels.names[c]}</label>
            ))}</div>
          </Field>
          <Field label={fa.tags.timing}>
            <select value={r.timing.mode} onChange={(e) => setR({ ...r, timing: { ...r.timing, mode: e.target.value } })}>
              {Object.entries(fa.tags.timings).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          {r.timing.mode === "next_day_evening" ? (
            <Field label={fa.tags.hour}><input type="number" min={0} max={23} value={r.timing.hour ?? 18}
              onChange={(e) => setR({ ...r, timing: { ...r.timing, hour: Number(e.target.value) } })} /></Field>
          ) : null}
          {r.goal === "convert" ? (
            <Field label={fa.tags.reminder}><input type="number" min={0} max={30} value={r.timing.reminder_days ?? 0}
              onChange={(e) => setR({ ...r, timing: { ...r.timing, reminder_days: Number(e.target.value) || undefined } })} /></Field>
          ) : null}
          <label className="row"><input type="checkbox" checked={r.low_risk} onChange={(e) => setR({ ...r, low_risk: e.target.checked })} /> {fa.tags.lowRisk}</label>
        </div>
      </div>
      <div className="row">
        <button className="btn" disabled={busy || r.tag.length < 2} onClick={save}>{fa.common.save}</button>
        {r.id ? <button className="btn danger" disabled={busy} onClick={() => run(async () => {
          await api(`/workspaces/${wsId}/recipes/${r.id}`, "DELETE");
          onSaved();
        })}>{fa.common.delete}</button> : null}
      </div>
      <ErrorLine text={error} />
    </div>
  );
}

export default function TagsPage() {
  const { ws } = useWorkspace();
  const list = useLoad<{ recipes: Recipe[] }>(`/workspaces/${ws.id}/recipes`);
  const [open, setOpen] = useState<string | null>(null);
  if (list.loading && !list.data) return <Loading />;
  return (
    <>
      <div className="spread"><h1>{fa.tags.title}</h1>
        <button className="btn" onClick={() => setOpen("new")}>{fa.tags.new}</button></div>
      <p className="muted">{fa.tags.hint}</p>
      <ErrorLine text={list.error} />
      {open === "new" ? <Editor wsId={ws.id} initial={BLANK} onSaved={() => { setOpen(null); void list.reload(); }} /> : null}
      <div className="table-wrap card">
        <table>
          <thead><tr><th>{fa.tags.tag}</th><th>{fa.tags.goal}</th><th>{fa.tags.length}</th><th>{fa.tags.channels}</th><th>{fa.tags.timing}</th><th /></tr></thead>
          <tbody>
            {list.data?.recipes.map((r) => (
              <tr key={r.id}>
                <td>#{r.tag}</td>
                <td>{fa.brand.goals[r.goal]}</td>
                <td>{num(r.video_spec.min_s ?? 0)}–{num(r.video_spec.max_s ?? 0)}</td>
                <td>{r.channels.map((c) => fa.channels.names[c]).join(fa.common.listSep)}</td>
                <td>{fa.tags.timings[r.timing.mode]}</td>
                <td><button className="btn ghost small" onClick={() => setOpen(open === r.id ? null : r.id ?? null)}>{fa.common.edit}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {list.data?.recipes.filter((r) => r.id === open).map((r) => (
        <Editor key={r.id} wsId={ws.id} initial={r} onSaved={() => { setOpen(null); void list.reload(); }} />
      ))}
    </>
  );
}
