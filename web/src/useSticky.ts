import { useState } from "react";

// useState that survives page reload (sessionStorage: per-tab, cleared on close).
// Drop-in for useState — supports functional updaters.
export function useSticky<T>(key: string, initial: T) {
  const [val, setVal] = useState<T>(() => {
    try {
      const s = sessionStorage.getItem(key);
      return s ? (JSON.parse(s) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = (v: T | ((prev: T) => T)) => {
    setVal((prev) => {
      const next = typeof v === "function" ? (v as (p: T) => T)(prev) : v;
      try { sessionStorage.setItem(key, JSON.stringify(next)); } catch { /* quota/private mode */ }
      return next;
    });
  };
  return [val, set] as const;
}
