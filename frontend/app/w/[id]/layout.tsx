"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { fa } from "@/lib/fa";
import type { Workspace } from "@/lib/types";
import { useLoad } from "@/components/hooks";
import { WorkspaceContext } from "@/components/workspace";
import { ErrorLine, Loading } from "@/components/ui";

const NAV: { path: string; label: string }[] = [
  { path: "", label: fa.nav.dashboard },
  { path: "/instagram", label: fa.nav.instagram },
  { path: "/queue", label: fa.nav.queue },
  { path: "/calendar", label: fa.nav.calendar },
  { path: "/brand", label: fa.nav.brand },
  { path: "/tags", label: fa.nav.tags },
  { path: "/feedback", label: fa.nav.feedback },
  { path: "/competitors", label: fa.nav.competitors },
  { path: "/sales", label: fa.nav.sales },
  { path: "/reports", label: fa.nav.reports },
  { path: "/channels", label: fa.nav.channels },
  { path: "/team", label: fa.nav.team },
  { path: "/settings", label: fa.nav.settings },
];

export default function WorkspaceLayout({ children, params }: { children: ReactNode; params: { id: string } }) {
  const { data, error, reload } = useLoad<Workspace>(`/workspaces/${params.id}`);
  const pathname = usePathname();
  const base = `/w/${params.id}`;
  if (error) return <main className="main"><ErrorLine text={error} /></main>;
  if (!data) return <main className="main"><Loading /></main>;
  return (
    <WorkspaceContext.Provider value={{ ws: data, reload }}>
      <div className="shell" style={{ ["--brand" as string]: data.brand.primary_color }}>
        <nav className="sidebar" aria-label={data.name}>
          <div className="product">{data.brand.display_name}</div>
          <div className="ws">{data.name}</div>
          {NAV.map((item) => {
            const href = `${base}${item.path}`;
            const active = item.path === "" ? pathname === base : pathname.startsWith(href);
            return <Link key={item.path} href={href} className={active ? "active" : ""}>{item.label}</Link>;
          })}
          <Link href="/">{fa.nav.workspaces}</Link>
        </nav>
        <main className="main">{children}</main>
      </div>
    </WorkspaceContext.Provider>
  );
}
