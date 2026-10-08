import type { ReactNode } from "react";
import { fa } from "@/lib/fa";

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function Loading() {
  return <p className="muted">{fa.common.loading}</p>;
}

export function Empty({ text }: { text?: string }) {
  return <p className="muted">{text ?? fa.common.empty}</p>;
}

export function ErrorLine({ text }: { text: string | null }) {
  return text ? <p className="error" role="alert">{text}</p> : null;
}

export function Stat({ label, value, note }: { label: string; value: ReactNode; note?: ReactNode }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note ? <div className="muted">{note}</div> : null}
    </div>
  );
}

export function Tabs<T extends string>({ items, value, onChange }: {
  items: { id: T; label: string }[]; value: T; onChange: (id: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {items.map((item) => (
        <button key={item.id} type="button" role="tab" aria-selected={value === item.id}
          className={value === item.id ? "on" : ""} onClick={() => onChange(item.id)}>
          {item.label}
        </button>
      ))}
    </div>
  );
}

/** Lines of a textarea <-> a list. */
export const linesOf = (text: string): string[] => text.split("\n").map((l) => l.trim()).filter(Boolean);
