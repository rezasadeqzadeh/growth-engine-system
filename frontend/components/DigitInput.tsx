"use client";

import type { ChangeEvent, InputHTMLAttributes } from "react";
import { enDigits } from "@/lib/format";

type Props = InputHTMLAttributes<HTMLInputElement> & { numeric?: boolean };

/**
 * An input for numbers and codes (phones, prices, slugs, page ids): Persian
 * and Arabic digits become ASCII as they are typed. `numeric` replaces
 * type="number", which silently empties itself on Persian digits.
 */
export function DigitInput({ numeric, onChange, type, ...rest }: Props) {
  const handle = (e: ChangeEvent<HTMLInputElement>) => {
    const value = enDigits(e.target.value);
    if (value !== e.target.value) e.target.value = value;
    onChange?.(e);
  };
  return (
    <input {...rest} type={numeric ? "text" : type ?? "text"} inputMode={numeric ? "decimal" : rest.inputMode}
      dir={rest.dir ?? "ltr"} onChange={handle} />
  );
}
