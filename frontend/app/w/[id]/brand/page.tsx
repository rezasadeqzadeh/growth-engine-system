"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fa, fill } from "@/lib/fa";
import { num, splitList } from "@/lib/format";
import { useAction, useLoad } from "@/components/hooks";
import { ErrorLine, Field, linesOf, Loading } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { DigitInput } from "@/components/DigitInput";

interface Pillar { key: string; name: string; goal: string }
interface Kit {
  version: number; answers: Record<string, string>; questions: string[]; logo_url: string | null;
  colors: { primary: string[]; accent: string[]; text: string; names?: Record<string, string> };
  fonts: { heading: string; body: string };
  tone: { adjectives?: string[]; anti?: string[]; do?: string[]; dont?: string[] };
  pillars: Pillar[]; glossary: string[]; banned: string[];
  templates: Record<string, string>; bio: { suggestions?: string[]; highlights?: { name: string; cover: string }[] };
}

export default function BrandPage() {
  const { ws } = useWorkspace();
  const kit = useLoad<Kit>(`/workspaces/${ws.id}/brand-kit`);
  const versions = useLoad<{ versions: { version: number; created_at: string; current: boolean }[] }>(`/workspaces/${ws.id}/brand-kit/versions`);
  const [draft, setDraft] = useState<Kit | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const { run, busy, error } = useAction();

  useEffect(() => {
    if (kit.data) {
      setDraft(kit.data);
      setAnswers(kit.data.answers ?? {});
    }
  }, [kit.data]);

  if (kit.loading && !draft) return <Loading />;
  if (!draft) return <ErrorLine text={kit.error} />;
  draft.colors = { ...draft.colors, primary: draft.colors?.primary ?? [], accent: draft.colors?.accent ?? [] };
  const set = <K extends keyof Kit>(key: K, value: Kit[K]) => { setDraft({ ...draft, [key]: value }); setSaved(false); };
  const done = async (k: Kit) => { kit.setData(k as Kit); await kit.reload(); await versions.reload(); setSaved(true); };

  const save = () => run(async () => {
    const { colors, fonts, tone, pillars, glossary, banned, templates, bio } = draft;
    await done(await api<Kit>(`/workspaces/${ws.id}/brand-kit`, "PUT", { colors, fonts, tone, pillars, glossary, banned, templates, bio }));
  });
  const generate = () => run(async () => {
    await done(await api<Kit>(`/workspaces/${ws.id}/brand-kit/generate`, "POST", { answers }));
  });
  const uploadLogo = (file: File) => run(async () => {
    const form = new FormData();
    form.append("file", file);
    await done(await api<Kit>(`/workspaces/${ws.id}/brand-kit/logo`, "POST", form));
  });

  const tone = draft.tone ?? {};
  const color = (group: "primary" | "accent", i: number) => (
    <input type="color" value={draft.colors[group]?.[i] ?? "#000000"} aria-label={`${group} ${i + 1}`}
      onChange={(e) => {
        const values = [...(draft.colors[group] ?? [])];
        values[i] = e.target.value;
        set("colors", { ...draft.colors, [group]: values });
      }} />
  );

  return (
    <>
      <div className="spread">
        <h1>{fa.brand.title} <span className="muted">· {fill(fa.brand.version, { n: num(draft.version) })}</span></h1>
        <div className="row no-print">
          <button className="btn ghost" onClick={() => window.print()}>{fa.common.print}</button>
          <button className="btn" disabled={busy} onClick={save}>{fa.common.save}</button>
        </div>
      </div>
      {saved ? <p className="okText">{fa.common.saved}</p> : null}
      <ErrorLine text={error} />

      <details className="card no-print" open={!draft.answers || Object.keys(draft.answers).length === 0}>
        <summary><strong>{fa.brand.questionnaire}</strong></summary>
        {draft.questions.map((q) => (
          <Field key={q} label={fa.brand.questions[q] ?? q}>
            <textarea rows={2} value={answers[q] ?? ""} onChange={(e) => setAnswers({ ...answers, [q]: e.target.value })} />
          </Field>
        ))}
        <button className="btn" disabled={busy} onClick={generate}>{busy ? fa.brand.generating : fa.brand.regenerate}</button>
      </details>

      <div className="grid2">
        <div className="card">
          <h2>{fa.brand.colors}</h2>
          <div className="row"><span>{fa.brand.primary}</span>{color("primary", 0)}{color("primary", 1)}</div>
          <div className="row"><span>{fa.brand.accent}</span>{color("accent", 0)}{color("accent", 1)}</div>
          <div className="row"><span>{fa.brand.text}</span>
            <input type="color" value={draft.colors.text} onChange={(e) => set("colors", { ...draft.colors, text: e.target.value })} /></div>
          <h3 style={{ marginTop: 12 }}>{fa.brand.preview}</h3>
          <div style={{ background: "#555", padding: 24, borderRadius: 10, textAlign: "center" }}>
            <span style={{ background: draft.colors.primary?.[1] ?? "#1f2a44", color: draft.colors.text ?? "#ffffff", padding: "4px 10px", borderRadius: 4,
                           fontFamily: draft.fonts.body, fontWeight: 900 }}>{fa.brand.previewText}</span>
          </div>
        </div>
        <div className="card">
          <h2>{fa.brand.fonts}</h2>
          <Field label={fa.brand.heading}><DigitInput type="text" className="ltr" value={draft.fonts.heading}
            onChange={(e) => set("fonts", { ...draft.fonts, heading: e.target.value })} /></Field>
          <Field label={fa.brand.body}><DigitInput type="text" className="ltr" value={draft.fonts.body}
            onChange={(e) => set("fonts", { ...draft.fonts, body: e.target.value })} /></Field>
          <Field label={fa.brand.logo}>
            {draft.logo_url ? <img src={draft.logo_url} alt="" style={{ maxHeight: 64, display: "block", marginBottom: 8 }} /> : null}
            <input type="file" accept="image/png" onChange={(e) => e.target.files?.[0] && uploadLogo(e.target.files[0])} />
          </Field>
        </div>
        <div className="card">
          <h2>{fa.brand.tone}</h2>
          <Field label={fa.brand.adjectives}><input type="text" value={(tone.adjectives ?? []).join(fa.common.listSep)}
            onChange={(e) => set("tone", { ...tone, adjectives: splitList(e.target.value) })} /></Field>
          <Field label={fa.brand.anti}><input type="text" value={(tone.anti ?? []).join(fa.common.listSep)}
            onChange={(e) => set("tone", { ...tone, anti: splitList(e.target.value) })} /></Field>
          <Field label={fa.brand.doExamples}><textarea rows={3} value={(tone.do ?? []).join("\n")}
            onChange={(e) => set("tone", { ...tone, do: linesOf(e.target.value) })} /></Field>
          <Field label={fa.brand.dontExamples}><textarea rows={3} value={(tone.dont ?? []).join("\n")}
            onChange={(e) => set("tone", { ...tone, dont: linesOf(e.target.value) })} /></Field>
        </div>
        <div className="card">
          <h2>{fa.brand.pillars}</h2>
          {draft.pillars.map((p, i) => (
            <div key={i} className="row" style={{ marginBottom: 6 }}>
              <input type="text" value={p.name} style={{ flex: 1 }} onChange={(e) => {
                const next = [...draft.pillars]; next[i] = { ...p, name: e.target.value }; set("pillars", next);
              }} />
              <select value={p.goal} style={{ width: 110 }} onChange={(e) => {
                const next = [...draft.pillars]; next[i] = { ...p, goal: e.target.value }; set("pillars", next);
              }}>
                {Object.entries(fa.brand.goals).map(([g, label]) => <option key={g} value={g}>{label}</option>)}
              </select>
              <button className="btn ghost small" onClick={() => set("pillars", draft.pillars.filter((_, j) => j !== i))}>{fa.common.delete}</button>
            </div>
          ))}
          <button className="btn ghost small" onClick={() => set("pillars", [...draft.pillars,
            { key: `p${draft.pillars.length + 1}`, name: "", goal: "trust" }])}>{fa.common.add}</button>
        </div>
        <div className="card">
          <Field label={fa.brand.glossary}><textarea rows={6} value={draft.glossary.join("\n")}
            onChange={(e) => set("glossary", linesOf(e.target.value))} /></Field>
          <Field label={fa.brand.banned}><textarea rows={4} value={draft.banned.join("\n")}
            onChange={(e) => set("banned", linesOf(e.target.value))} /></Field>
        </div>
        <div className="card">
          <h2>{fa.brand.bio}</h2>
          <Field label={fa.brand.oneLine}><textarea rows={4} value={(draft.bio.suggestions ?? []).join("\n")}
            onChange={(e) => set("bio", { ...draft.bio, suggestions: linesOf(e.target.value) })} /></Field>
          <h3>{fa.brand.highlights}</h3>
          <p>{(draft.bio.highlights ?? []).map((h) => `${h.cover} ${h.name}`).join(" · ") || "—"}</p>
          <h3>{fa.brand.versions}</h3>
          <p className="muted">{versions.data?.versions.map((v) => num(v.version)).join(fa.common.listSep)}</p>
        </div>
      </div>
    </>
  );
}
