import { useState } from "react";
import type { CodeChange } from "../api";

// op → label + color. edit/create/delete are file ops; run is a shell command.
const OP: Record<string, { label: string; color: string }> = {
  edit: { label: "编辑", color: "var(--warn)" },
  create: { label: "新建", color: "var(--good)" },
  delete: { label: "删除", color: "var(--bad)" },
  run: { label: "运行", color: "var(--accent)" },
};

const basename = (p: string) => p.split("/").filter(Boolean).pop() || p;
const clip = (s: string, n = 6) => {
  const lines = s.split("\n");
  return lines.length > n ? lines.slice(0, n).join("\n") + "\n…" : s;
};

// Compact old→new fragment for an edit; nothing for a create/run.
function Diff({ c }: { c: CodeChange }) {
  if (c.op === "run") return null;
  return (
    <div className="mono" style={{ fontSize: 11.5, marginTop: 4, lineHeight: 1.45 }}>
      {c.old ? (
        <pre style={{ margin: 0, padding: "2px 6px", whiteSpace: "pre-wrap", wordBreak: "break-word",
          background: "rgba(196,77,77,.08)", borderLeft: "2px solid var(--bad)", color: "var(--bad)" }}>
          {clip(c.old)}
        </pre>
      ) : null}
      {c.new ? (
        <pre style={{ margin: c.old ? "2px 0 0" : 0, padding: "2px 6px", whiteSpace: "pre-wrap", wordBreak: "break-word",
          background: "rgba(61,139,94,.08)", borderLeft: "2px solid var(--good)", color: "var(--good)" }}>
          {clip(c.new)}
        </pre>
      ) : null}
    </div>
  );
}

export function ChangesPanel({ changes, onJump }: { changes: CodeChange[]; onJump?: (itemIdx: number) => void }) {
  const [open, setOpen] = useState(false);
  if (changes.length === 0) return null;

  // summary counts per op for the collapsed header
  const counts = changes.reduce<Record<string, number>>((m, c) => ((m[c.op] = (m[c.op] ?? 0) + 1), m), {});
  const summary = ["edit", "create", "delete", "run"]
    .filter((o) => counts[o])
    .map((o) => `${counts[o]} ${OP[o].label}`)
    .join(" · ");

  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "6px 12px" }}>
      <button className="btn" onClick={() => setOpen((v) => !v)} style={{ fontSize: 12 }}>
        {open ? "▾" : "▸"} 代码变更 ({changes.length}) <span className="dim">· {summary}</span>
      </button>
      {open && (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6,
          maxHeight: 360, overflowY: "auto" }}>
          {changes.map((c, i) => {
            const op = OP[c.op] ?? OP.run;
            const target = c.op === "run" ? c.command : c.path;
            return (
              <div key={i}
                onClick={() => onJump?.(c.item_idx)}
                style={{ padding: "6px 8px", border: "1px solid var(--border-light)", borderRadius: 5,
                  cursor: onJump ? "pointer" : "default", background: "var(--panel)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
                  <span className="chip chip-sm" style={{ color: "var(--dim)" }}>
                    {c.run_id ?? 0}·{c.step_id ?? 0}
                  </span>
                  <span style={{ color: op.color, fontWeight: 600 }}>{op.label}</span>
                  <span className="mono" style={{ color: "var(--ink)", overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: c.op === "run" ? "nowrap" : "normal" }}
                    title={target ?? ""}>
                    {c.op === "run" ? target : c.path ? basename(c.path) : "(无路径)"}
                  </span>
                </div>
                {c.op !== "run" && c.path && (
                  <div className="dim mono" style={{ fontSize: 10.5, marginTop: 2 }}>{c.path}</div>
                )}
                <Diff c={c} />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
