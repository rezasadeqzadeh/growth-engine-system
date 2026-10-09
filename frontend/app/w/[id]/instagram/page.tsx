"use client";

import Link from "next/link";
import { fa, fill } from "@/lib/fa";
import { dateFa, dateTimeFa, num } from "@/lib/format";
import { useLoad } from "@/components/hooks";
import { Empty, ErrorLine, Loading, Stat } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";

interface Post { id: string; type: string; caption: string; at: string | null; likes: number; comments: number; url: string | null }
interface Stats {
  username: string | null; account_type: string | null; followers: number | null; media_count: number | null;
  engagement_rate: number | null; period_days: number; period: Record<string, number>; period_error: string | null;
  posts: Post[]; fetched_at: string;
}

const PERIOD_KEYS = ["reach", "views", "accounts_engaged", "total_interactions", "likes", "comments", "shares", "saves",
  "follows_and_unfollows", "profile_links_taps"] as const;

export default function InstagramStatsPage() {
  const { ws } = useWorkspace();
  const stats = useLoad<Stats>(`/workspaces/${ws.id}/instagram/stats`);
  const t = fa.instagramStats;
  const notConnected = stats.error === fa.errors.instagram_not_connected || stats.error === fa.errors.instagram_token_expired;
  return (
    <>
      <div className="spread">
        <h1>{t.title}{stats.data?.username ? ` · @${stats.data.username}` : ""}</h1>
        <button className="btn ghost" disabled={stats.loading} onClick={() => stats.reload()}>{fa.common.refresh}</button>
      </div>
      {stats.loading && !stats.data ? <Loading /> : null}
      {notConnected ? (
        <div className="card">
          <p>{stats.error}</p>
          <Link className="btn" href={`/w/${ws.id}/channels`}>{t.connect}</Link>
        </div>
      ) : <ErrorLine text={stats.error} />}
      {stats.data ? (
        <>
          <div className="stats">
            <Stat label={t.followers} value={num(stats.data.followers)} />
            <Stat label={t.mediaCount} value={num(stats.data.media_count)} />
            <Stat label={t.engagement} value={stats.data.engagement_rate === null ? "—" : `${num(stats.data.engagement_rate)}٪`}
              note={t.engagementNote} />
          </div>
          <h2>{fill(t.periodTitle, { days: num(stats.data.period_days) })}</h2>
          {stats.data.period_error ? <p className="muted">{t.periodUnavailable}</p> : (
            <div className="stats">
              {PERIOD_KEYS.filter((k) => k in stats.data!.period).map((k) => (
                <Stat key={k} label={t.metrics[k] ?? k} value={num(stats.data!.period[k])} />
              ))}
            </div>
          )}
          <h2>{t.recentPosts}</h2>
          {stats.data.posts.length === 0 ? <Empty /> : (
            <table>
              <thead><tr><th>{t.date}</th><th>{t.type}</th><th>{t.caption}</th><th>{t.likes}</th><th>{t.comments}</th><th /></tr></thead>
              <tbody>
                {stats.data.posts.map((p) => (
                  <tr key={p.id}>
                    <td>{p.at ? dateFa(p.at) : "—"}</td>
                    <td>{t.types[p.type] ?? p.type}</td>
                    <td>{p.caption || "—"}</td>
                    <td>{num(p.likes)}</td>
                    <td>{num(p.comments)}</td>
                    <td>{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{t.open}</a> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted">{fill(t.fetchedAt, { time: dateTimeFa(stats.data.fetched_at) })}</p>
        </>
      ) : null}
    </>
  );
}
