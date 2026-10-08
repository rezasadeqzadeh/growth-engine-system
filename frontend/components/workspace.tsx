"use client";

import { createContext, useContext } from "react";
import type { Workspace } from "@/lib/types";

export const WorkspaceContext = createContext<{ ws: Workspace; reload: () => Promise<void> } | null>(null);

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace outside a workspace page");
  return value;
}
