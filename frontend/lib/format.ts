// Numbers, money and dates for Persian readers: Persian digits, Toman,
// the Jalali calendar and Tehran time.

import { fa } from "./fa";

const faNumber = new Intl.NumberFormat("fa-IR");
const faDate = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { timeZone: "Asia/Tehran", day: "numeric", month: "long" });
const faDateTime = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: "Asia/Tehran", weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
});
const faMonth = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { timeZone: "Asia/Tehran", month: "long", year: "numeric" });
const faDayNum = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { timeZone: "Asia/Tehran", day: "numeric" });
const parts = new Intl.DateTimeFormat("en-US-u-ca-persian", {
  timeZone: "Asia/Tehran", year: "numeric", month: "numeric", day: "numeric",
});

export const num = (n: number | null | undefined): string => (n === null || n === undefined ? "—" : faNumber.format(n));
export const toman = (n: number): string => `${faNumber.format(n)} ${fa.common.toman}`;
export const pct = (n: number): string =>
  new Intl.NumberFormat("fa-IR", { style: "percent", maximumFractionDigits: 0 }).format(n / 100);
/** Split a comma list typed with Persian or Latin commas. */
export const splitList = (text: string): string[] => text.split(/[\u060c,]/).map((x) => x.trim()).filter(Boolean);
export const dateFa = (iso: string): string => faDate.format(new Date(iso));
export const dateTimeFa = (iso: string): string => faDateTime.format(new Date(iso));
export const monthFa = (iso: string): string => faMonth.format(new Date(iso));
export const dayNumFa = (iso: string): string => faDayNum.format(new Date(`${iso}T12:00:00Z`));

/** Today's Jalali year and month (Tehran). */
export function jalaliToday(): { year: number; month: number } {
  const p = parts.formatToParts(new Date());
  const get = (t: string) => Number(p.find((x) => x.type === t)?.value ?? 0);
  return { year: get("year"), month: get("month") };
}

/** Saturday-first weekday index (0 = Saturday) of an ISO date. */
export function iranWeekday(iso: string): number {
  return (new Date(`${iso}T12:00:00Z`).getUTCDay() + 1) % 7;
}

export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
