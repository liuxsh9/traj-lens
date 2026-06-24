import { useState, useRef, useEffect, useMemo } from "react";
import type { TrajSummary } from "../api";

// ── Types ──────────────────────────────────────────────────────────────

export interface FilterRule {
  id: number;
  field: string;
  op: string;
  value: string;
}

interface FieldDef {
  key: string;
  label: string;
  type: "enum" | "number" | "tags";
  ops: string[];
  options?: string[]; // for enum
}

const FIELDS: FieldDef[] = [
  { key: "resolution", label: "resolution", type: "enum", ops: ["=", "≠"], options: [] },
  { key: "interrupted", label: "interrupted", type: "enum", ops: ["="], options: ["true", "false"] },
  { key: "turns", label: "turns", type: "number", ops: ["≥", "≤", "="] },
  { key: "steps", label: "steps", type: "number", ops: ["≥", "≤", "="] },
  { key: "tools", label: "tools", type: "number", ops: ["≥", "≤", "="] },
  { key: "pushback_count", label: "pushback", type: "number", ops: ["≥", "≤", "="] },
  { key: "error_steps", label: "error steps", type: "number", ops: ["≥", "≤", "="] },
  { key: "score", label: "score", type: "number", ops: ["≥", "≤", "="] },
  { key: "tags", label: "tags", type: "tags", ops: ["∋", "∌"] },
];

// ── Filter logic ───────────────────────────────────────────────────────

function getVal(row: TrajSummary, field: string): unknown {
  if (field === "resolution") return row.annotations?.resolution ?? "";
  if (field === "interrupted") return row.annotations?.interrupted ? "true" : "false";
  if (field === "tags") return row.annotations?.tags ?? [];
  const metricMap: Record<string, string> = {
    turns: "turn_count", steps: "step_count", tools: "tool_count",
    pushback_count: "pushback_count", error_steps: "error_steps", score: "success_score",
  };
  return row.metrics?.[metricMap[field]] ?? 0;
}

function matchRule(row: TrajSummary, r: FilterRule): boolean {
  const v = getVal(row, r.field);
  const def = FIELDS.find((f) => f.key === r.field);
  if (!def) return true;

  if (def.type === "enum") {
    return r.op === "=" ? v === r.value : v !== r.value;
  }
  if (def.type === "number") {
    const n = Number(v), t = Number(r.value);
    if (isNaN(t)) return true;
    if (r.op === "≥") return n >= t;
    if (r.op === "≤") return n <= t;
    return n === t;
  }
  if (def.type === "tags") {
    const arr = v as string[];
    const needle = r.value.toLowerCase();
    if (!needle) return true;
    const has = arr.some((t) => t.toLowerCase().includes(needle));
    return r.op === "∋" ? has : !has;
  }
  return true;
}

export function applyFilters(rows: TrajSummary[], rules: FilterRule[]): TrajSummary[] {
  if (!rules.length) return rows;
  return rows.filter((row) => rules.every((r) => matchRule(row, r)));
}

// ── Component ──────────────────────────────────────────────────────────

let _nextId = 1;

export function FilterBar({
  rules, onChange, rows,
}: {
  rules: FilterRule[];
  onChange: (rules: FilterRule[]) => void;
  rows: TrajSummary[];
}) {
  const [adding, setAdding] = useState<string | null>(null); // field key being added
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // dynamic enum options from data
  const enumOptions = useMemo(() => {
    const res = new Set<string>();
    for (const r of rows) {
      const v = r.annotations?.resolution;
      if (v) res.add(v);
    }
    return [...res].sort();
  }, [rows]);

  const tagOptions = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) {
      for (const t of r.annotations?.tags ?? []) s.add(t);
    }
    return [...s].sort();
  }, [rows]);

  // close menu on outside click
  useEffect(() => {
    if (!menuOpen && !adding) return;
    const h = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
        setAdding(null);
      }
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [menuOpen, adding]);

  // focus input when adding
  useEffect(() => {
    if (adding) inputRef.current?.focus();
  }, [adding]);

  const remove = (id: number) => onChange(rules.filter((r) => r.id !== id));

  const commit = (field: string, op: string, value: string) => {
    if (!value) return;
    onChange([...rules, { id: _nextId++, field, op, value }]);
    setAdding(null);
    setMenuOpen(false);
  };

  const def = adding ? FIELDS.find((f) => f.key === adding) : null;

  return (
    <div className="filter-bar" ref={menuRef}>
      {rules.map((r) => {
        const d = FIELDS.find((f) => f.key === r.field);
        return (
          <span key={r.id} className="filter-chip">
            {d?.label ?? r.field} {r.op} {r.value}
            <button className="chip-x" onClick={() => remove(r.id)}>×</button>
          </span>
        );
      })}

      <button className="filter-add-btn" onClick={() => setMenuOpen(!menuOpen)}>+ 筛选</button>

      {menuOpen && !adding && (
        <div className="filter-dropdown">
          {FIELDS.map((f) => (
            <div key={f.key} className="filter-dropdown-item" onClick={() => { setAdding(f.key); setMenuOpen(false); }}>
              {f.label}
              <span className="faint" style={{ marginLeft: 6, fontSize: 11 }}>
                {f.type === "enum" ? "枚举" : f.type === "number" ? "数值" : "标签"}
              </span>
            </div>
          ))}
        </div>
      )}

      {adding && def && (
        <AddRulePopover def={def}
          enumOptions={def.key === "interrupted" ? ["true", "false"] : enumOptions}
          tagOptions={tagOptions}
          inputRef={inputRef} onCommit={commit} onCancel={() => setAdding(null)} />
      )}
    </div>
  );
}

// ── Inline rule editor ─────────────────────────────────────────────────

function AddRulePopover({ def, enumOptions, tagOptions, inputRef, onCommit, onCancel }: {
  def: FieldDef;
  enumOptions: string[];
  tagOptions: string[];
  inputRef: React.MutableRefObject<HTMLInputElement | null>;
  onCommit: (field: string, op: string, value: string) => void;
  onCancel: () => void;
}) {
  const [op, setOp] = useState(def.ops[0]);
  const [value, setValue] = useState("");

  const submit = () => { onCommit(def.key, op, value); };

  return (
    <div className="filter-dropdown filter-popover">
      <span className="filter-popover-label">{def.label}</span>
      <select className="filter-select-sm" value={op} onChange={(e) => setOp(e.target.value)}>
        {def.ops.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>

      {def.type === "enum" && (
        <select className="filter-select-sm" value={value}
          onChange={(e) => { setValue(e.target.value); onCommit(def.key, op, e.target.value); }}>
          <option value="">选择…</option>
          {enumOptions.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      )}

      {def.type === "number" && (
        <input ref={inputRef} className="filter-input-sm" type="number" placeholder="值"
          value={value} onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") onCancel(); }} />
      )}

      {def.type === "tags" && (
        <input ref={inputRef} className="filter-input-sm" type="text" placeholder="标签名"
          list="tag-opts" value={value} onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) submit(); if (e.key === "Escape") onCancel(); }} />
      )}
      {def.type === "tags" && (
        <datalist id="tag-opts">
          {tagOptions.map((t) => <option key={t} value={t} />)}
        </datalist>
      )}

      {def.type !== "enum" && (
        <button className="filter-commit-btn" onClick={submit}>确定</button>
      )}
      <button className="chip-x" onClick={onCancel}>×</button>
    </div>
  );
}
