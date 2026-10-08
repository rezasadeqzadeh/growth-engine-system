"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fa, fill } from "@/lib/fa";
import { useAction, useLoad } from "@/components/hooks";
import { ErrorLine, Loading } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

interface Member {
  id: string; display_name: string; role: string; user_id: string | null; bale_bound: boolean; telegram_bound: boolean;
  link_code: string | null;
}

export default function TeamPage() {
  const { ws } = useWorkspace();
  const list = useLoad<{ members: Member[] }>(`/workspaces/${ws.id}/members`);
  const [name, setName] = useState("");
  const [role, setRole] = useState("approver");
  const { run, busy, error } = useAction();
  const base = `/workspaces/${ws.id}/members`;
  if (list.loading && !list.data) return <Loading />;
  return (
    <>
      <h1>{fa.team.title}</h1>
      <ErrorLine text={list.error ?? error} />
      <div className="card table-wrap">
        <table>
          <thead><tr><th>{fa.team.name}</th><th>{fa.team.role}</th><th>{fa.team.bound}</th><th>{fa.team.linkCode}</th><th /></tr></thead>
          <tbody>{list.data?.members.map((m) => (
            <tr key={m.id}>
              <td>{m.display_name}</td>
              <td>
                <select value={m.role} style={{ maxWidth: 160 }} disabled={busy} onChange={(e) => run(async () => {
                  await api(`${base}/${m.id}`, "PATCH", { display_name: m.display_name, role: e.target.value });
                  await list.reload();
                })}>
                  {Object.entries(fa.team.roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </td>
              <td>{[m.bale_bound ? fa.channels.names.bale : "", m.telegram_bound ? fa.channels.names.telegram : ""].filter(Boolean).join(" · ") || "—"}</td>
              <td>{m.link_code ? <span className="ltr">{fill(fa.team.linkHint, { code: m.link_code })}</span> : null}</td>
              <td className="row">
                <button className="btn ghost small" disabled={busy} onClick={() => run(async () => {
                  await api(`${base}/${m.id}/link-code`, "POST");
                  await list.reload();
                })}>{fa.team.newCode}</button>
                {m.user_id === null ? <button className="btn ghost small" disabled={busy} onClick={() => run(async () => {
                  await api(`${base}/${m.id}`, "DELETE");
                  await list.reload();
                })}>{fa.common.delete}</button> : null}
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="card row">
        <input type="text" placeholder={fa.team.name} value={name} style={{ maxWidth: 240 }} onChange={(e) => setName(e.target.value)} />
        <select value={role} style={{ maxWidth: 180 }} onChange={(e) => setRole(e.target.value)}>
          {Object.entries(fa.team.roles).filter(([k]) => k !== "owner").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <button className="btn" disabled={busy || !name} onClick={() => run(async () => {
          await api(base, "POST", { display_name: name, role });
          setName("");
          await list.reload();
        })}>{fa.team.add}</button>
      </div>
    </>
  );
}
