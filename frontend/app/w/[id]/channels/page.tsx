"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fa, fill } from "@/lib/fa";
import { dateTimeFa, num } from "@/lib/format";
import type { ChannelOut } from "@/lib/types";
import { useAction, useLoad } from "@/components/hooks";
import { ErrorLine, Field, Loading } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { DigitInput } from "@/components/DigitInput";

// What each channel type asks for: [config keys, secret keys] (mirrors api/channels.py FIELDS).
const FIELDS: Record<string, [string[], string[]]> = {
  bale: [["chat_id", "username", "raw_chat_id"], ["bot_token"]],
  telegram: [["chat_id", "username", "raw_chat_id", "discussion_chat_id"], ["bot_token"]],
  eitaa: [["chat_id"], ["token"]],
  rubika: [["chat_id"], ["token"]],
  aparat: [["category"], ["username", "password"]],
};

function ChannelForm({ wsId, channel, type, onSaved }: { wsId: string; channel?: ChannelOut; type: string; onSaved: () => void }) {
  const [configKeys, secretKeys] = FIELDS[type] ?? [[], []];
  const [name, setName] = useState(channel?.name ?? "");
  const [config, setConfig] = useState<Record<string, string>>(channel?.config ?? {});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const { run, busy, error } = useAction();
  const save = () => run(async () => {
    const body = { type, name, config, credentials: secrets, enabled: true };
    if (channel) await api(`/workspaces/${wsId}/channels/${channel.id}`, "PATCH", body);
    else await api(`/workspaces/${wsId}/channels`, "POST", body);
    setSecrets({});
    onSaved();
  });
  return (
    <div>
      <p className="muted">{fa.channels.hints[type]}</p>
      <Field label={fa.channels.name}><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      {configKeys.map((k) => (
        <Field key={k} label={fa.channels.fields[k] ?? k}>
          <DigitInput type="text" className="ltr" value={config[k] ?? ""} onChange={(e) => setConfig({ ...config, [k]: e.target.value })} />
        </Field>
      ))}
      {secretKeys.map((k) => {
        const stored = channel?.secrets_set.includes(k === "password" ? "lpass" : k);
        return (
          <Field key={k} label={fa.channels.fields[k] ?? k}>
            <input type="password" className="ltr" autoComplete="off" placeholder={stored ? fa.channels.secretSet : ""}
              value={secrets[k] ?? ""} onChange={(e) => setSecrets({ ...secrets, [k]: e.target.value })} />
          </Field>
        );
      })}
      <button className="btn" disabled={busy} onClick={save}>{fa.common.save}</button>
      <ErrorLine text={error} />
    </div>
  );
}

function Health({ c }: { c: ChannelOut }) {
  if (c.health_ok === null) return <span className="chip">{fa.channels.unchecked}</span>;
  return (
    <span className={`chip ${c.health_ok ? "ok" : "bad"}`} title={c.health_error ?? ""}>
      {c.health_ok ? fa.channels.healthy : fa.channels.broken}{c.health_checked_at ? ` · ${dateTimeFa(c.health_checked_at)}` : ""}
    </span>
  );
}

export default function ChannelsPage() {
  const { ws } = useWorkspace();
  const list = useLoad<{ channels: ChannelOut[] }>(`/workspaces/${ws.id}/channels`);
  const [adding, setAdding] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const { run, busy, error } = useAction();
  const status = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("instagram") : null;

  if (list.loading && !list.data) return <Loading />;
  const instagram = list.data?.channels.find((c) => c.type === "instagram");
  return (
    <>
      <h1>{fa.channels.title}</h1>
      {status === "failed" ? <p className="error">{fa.errors.generic}</p> : null}
      <ErrorLine text={list.error ?? error} />
      {list.data?.channels.map((c) => (
        <div key={c.id} className="card" style={{ opacity: c.enabled ? 1 : 0.5 }}>
          <div className="spread">
            <div className="row"><strong>{fa.channels.names[c.type]}</strong><span>{c.name}</span><Health c={c} /></div>
            <div className="row">
              <button className="btn ghost small" disabled={busy} onClick={() => run(async () => {
                await api(`/workspaces/${ws.id}/channels/${c.id}/test`, "POST");
                await list.reload();
              })}>{fa.channels.test}</button>
              {FIELDS[c.type] ? <button className="btn ghost small" onClick={() => setOpen(open === c.id ? null : c.id)}>{fa.common.edit}</button> : null}
              {c.type !== "site" && c.enabled ? <button className="btn ghost small" disabled={busy} onClick={() => run(async () => {
                await api(`/workspaces/${ws.id}/channels/${c.id}`, "DELETE");
                await list.reload();
              })}>{fa.channels.disable}</button> : null}
            </div>
          </div>
          <p className="muted">{fill(fa.channels.caps, {
            auto: c.capabilities.auto_publish ? "✓" : "—", metrics: c.capabilities.metrics, comments: c.capabilities.comments,
            mb: num(c.capabilities.max_video_mb) })}</p>
          {c.type === "instagram" || c.type === "site" ? <p className="muted">{fa.channels.hints[c.type]}</p> : null}
          {open === c.id ? <ChannelForm wsId={ws.id} channel={c} type={c.type} onSaved={() => { setOpen(null); void list.reload(); }} /> : null}
        </div>
      ))}
      <div className="card">
        <h2>{fa.channels.add}</h2>
        <div className="row">
          <select value={adding} onChange={(e) => setAdding(e.target.value)} style={{ maxWidth: 220 }}>
            <option value="">{fa.channels.type}</option>
            {Object.keys(FIELDS).map((t) => <option key={t} value={t}>{fa.channels.names[t]}</option>)}
          </select>
          {!instagram?.config.ig_user_id ? (
            <button className="btn ghost" disabled={busy} onClick={() => run(async () => {
              const res = await api<{ authorize_url: string }>(`/workspaces/${ws.id}/channels/instagram/connect`, "POST");
              window.location.href = res.authorize_url;
            })}>{fa.channels.connectInstagram}</button>
          ) : null}
          {!instagram ? (
            <button className="btn ghost" disabled={busy} onClick={() => run(async () => {
              await api(`/workspaces/${ws.id}/channels`, "POST", { type: "instagram", name: fa.channels.names.instagram ?? "", config: { mode: "handoff" } });
              await list.reload();
            })}>{fa.channels.instagramHandoff}</button>
          ) : null}
        </div>
        {adding ? <ChannelForm key={adding} wsId={ws.id} type={adding} onSaved={() => { setAdding(""); void list.reload(); }} /> : null}
      </div>
    </>
  );
}
