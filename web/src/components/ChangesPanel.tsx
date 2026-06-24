import { useState } from "react";
import { scanSemgrep } from "../api";
import type { CodeChange, SemgrepFinding, SemgrepResult } from "../api";

// op → label + color. edit/create/delete are file ops; run is a shell command.
const OP: Record<string, { label: string; color: string }> = {
  edit: { label: "编辑", color: "var(--warn)" },
  create: { label: "新建", color: "var(--good)" },
  delete: { label: "删除", color: "var(--bad)" },
  run: { label: "运行", color: "var(--accent)" },
};

const SEV_COLOR: Record<string, string> = {
  ERROR: "var(--bad)", WARNING: "var(--warn)", INFO: "var(--dim)",
};

const basename = (p: string) => p.split("/").filter(Boolean).pop() || p;
const clip = (s: string, n = 6) => {
  const lines = s.split("\n");
  return lines.length > n ? lines.slice(0, n).join("\n") + "\n…" : s;
};

// HTML/SVG content renderable in a sandboxed iframe. Mermaid deferred (needs
// mermaid.js). Edits expose only a fragment, so preview targets full documents:
// a content sniff or an .html/.svg path with markup.
function previewSrc(c: CodeChange): string | null {
  const body = c.new ?? "";
  if (!body) return null;
  const t = body.trimStart().toLowerCase();
  const ext = (c.path ?? "").toLowerCase();
  const looksDoc = t.startsWith("<svg") || t.startsWith("<!doctype html") || t.startsWith("<html");
  const isMarkupFile = (ext.endsWith(".html") || ext.endsWith(".htm") || ext.endsWith(".svg")) && body.includes("<");
  return looksDoc || isMarkupFile ? body : null;
}

// Compact old→new fragment for an edit; nothing for a create/run.
function Diff({ c }: { c: CodeChange }) {
  if (c.op === "run" || c.op === "delete") return null;
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

function ChangeRow({ c, onJump, findings }: {
  c: CodeChange; onJump?: (i: number) => void; findings: SemgrepFinding[];
}) {
  const [preview, setPreview] = useState(false);
  const op = OP[c.op] ?? OP.run;
  const target = c.op === "run" ? c.command : c.path;
  const src = previewSrc(c);
  return (
    <div style={{ padding: "6px 8px", border: "1px solid var(--border-light)", borderRadius: 5, background: "var(--panel)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
        <span className="chip chip-sm" style={{ color: "var(--dim)", cursor: onJump ? "pointer" : "default" }}
          onClick={() => onJump?.(c.item_idx)}>
          {c.run_id ?? 0}·{c.step_id ?? 0}
        </span>
        <span style={{ color: op.color, fontWeight: 600 }}>{op.label}</span>
        <span className="mono" style={{ color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: c.op === "run" ? "nowrap" : "normal", flex: 1 }} title={target ?? ""}>
          {c.op === "run" ? target : c.path ? basename(c.path) : "(无路径)"}
        </span>
        {src && (
          <button className="btn" style={{ fontSize: 11, padding: "1px 6px" }}
            onClick={() => setPreview((v) => !v)}>{preview ? "隐藏" : "预览"}</button>
        )}
      </div>
      {c.op !== "run" && c.path && (
        <div className="dim mono" style={{ fontSize: 10.5, marginTop: 2 }}>{c.path}</div>
      )}
      <Diff c={c} />
      {findings.map((f, i) => (
        <div key={i} className="mono" style={{ fontSize: 10.5, marginTop: 3, color: SEV_COLOR[f.severity] ?? "var(--dim)" }}
          title={f.check_id}>
          ⚠ {f.severity}{f.line ? ` L${f.line}` : ""}: {f.message.split("\n")[0]}
        </div>
      ))}
      {src && preview && (
        // sandbox="" = no scripts, no same-origin — safe static render of HTML/SVG
        <iframe sandbox="" srcDoc={src} title="preview"
          style={{ width: "100%", height: 280, marginTop: 6, border: "1px solid var(--border)",
            borderRadius: 4, background: "#fff" }} />
      )}
    </div>
  );
}

export function ChangesPanel({ changes, hash, onJump, persisted, scannedBefore }: {
  changes: CodeChange[]; hash: string; onJump?: (itemIdx: number) => void;
  persisted?: SemgrepFinding[];          // findings from a prior scan, shown on load
  scannedBefore?: boolean;               // was this trajectory scanned at all
}) {
  const [open, setOpen] = useState(false);
  const [scan, setScan] = useState<SemgrepResult | null>(null);
  const [scanning, setScanning] = useState(false);
  if (changes.length === 0) return null;

  // summary counts per op for the collapsed header
  const counts = changes.reduce<Record<string, number>>((m, c) => ((m[c.op] = (m[c.op] ?? 0) + 1), m), {});
  const summary = ["edit", "create", "delete", "run"]
    .filter((o) => counts[o])
    .map((o) => `${counts[o]} ${OP[o].label}`)
    .join(" · ");

  // findings shown = this session's fresh scan, else the persisted ones from a
  // prior scan (so they appear on load without re-running semgrep)
  const shown = scan?.findings ?? persisted ?? [];
  const byItem = new Map<number, SemgrepFinding[]>();
  for (const f of shown) {
    const list = byItem.get(f.item_idx) ?? [];
    list.push(f);
    byItem.set(f.item_idx, list);
  }

  const hasResult = scan !== null || scannedBefore;
  const runScan = async () => {
    setScanning(true);
    try { setScan(await scanSemgrep(hash, scannedBefore)); }  // force re-scan if already scanned
    catch { setScan({ available: true, scanned: 0, findings: [], error: "请求失败" }); }
    finally { setScanning(false); }
  };

  const scanLabel = () => {
    if (scanning) return "扫描中…";
    if (scan) {
      if (!scan.available) return "semgrep 未安装";
      if (scan.error) return `扫描出错：${scan.error}`;
      const tag = scan.cached ? "（缓存）" : "";
      return `发现 ${scan.findings.length} 处${tag}`;
    }
    if (scannedBefore) return `已扫描 · ${shown.length} 处（缓存）`;
    return null;
  };

  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "6px 12px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <button className="btn" onClick={() => setOpen((v) => !v)} style={{ fontSize: 12 }}>
          {open ? "▾" : "▸"} 代码变更 ({changes.length})
        </button>
        <span className="dim" style={{ fontSize: 12 }}>{summary}</span>
        <button className="btn" onClick={runScan} disabled={scanning} style={{ fontSize: 12, marginLeft: "auto" }}>
          {hasResult ? "重新扫描" : "安全扫描"}
        </button>
        {scanLabel() && <span className="dim" style={{ fontSize: 12 }}>{scanLabel()}</span>}
      </div>
      {open && (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6, maxHeight: 360, overflowY: "auto" }}>
          {changes.map((c, i) => (
            <ChangeRow key={i} c={c} onJump={onJump} findings={byItem.get(c.item_idx) ?? []} />
          ))}
        </div>
      )}
    </div>
  );
}
