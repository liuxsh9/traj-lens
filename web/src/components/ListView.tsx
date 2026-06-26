import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { useSticky } from "../useSticky";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from "@tanstack/react-table";
import { listTrajectories, createExport, listExports, deleteExport, downloadExportUrl,
  ACCEPT_DISPLAY, type AcceptLikelihood,
  type TrajSummary, type PageResult, type ExportArtifact } from "../api";
import { FilterBar, type FilterRule } from "./FilterBar";

const PAGE_SIZES = [10, 25, 50, 100] as const;
const col = createColumnHelper<TrajSummary>();

function fmtDate(iso: string) {
  return iso.slice(5, 16).replace("T", " ");
}

export function getListScoreClass(v: number) {
  return v >= 80 ? "res-ok" : v >= 40 ? "res-part" : "res-fail";
}

export function getListAcceptClass(v: AcceptLikelihood) {
  return v === "high" ? "res-ok" : v === "low" ? "res-fail" : "res-part";
}

export function formatListResolution(v: string) {
  return v === "partially_resolved" ? "partially" : v;
}

function ScorePill({ v }: { v: number }) {
  if (v < 0) return <span className="faint">—</span>;
  const cls = getListScoreClass(v);
  return <span className={`chip-sm ${cls}`}>{v}</span>;
}

// ponytail: sort_by map — column id → backend field name
const sortFieldMap: Record<string, string> = {
  turns: "turns", steps: "steps", tools: "tools",
  pb: "pushback_count", score: "score", sec: "security_findings", created_at: "created_at",
};

const defaultSorting: SortingState = [{ id: "score", desc: true }];

export function getListSortParams(sorting: SortingState) {
  const activeSort = sorting[0] ?? defaultSorting[0];
  return {
    sortBy: sortFieldMap[activeSort.id] ?? "created_at",
    sortDir: activeSort.desc === false ? "asc" : "desc",
  };
}

export function shouldShowExportSelection({
  datasetId,
  total,
  exportMode,
}: {
  datasetId?: string;
  total: number;
  exportMode: boolean;
}) {
  return Boolean(datasetId && total > 0 && exportMode);
}

export function shouldResetListForExternalFilters({
  hasControlledFilters,
  previousKey,
  nextKey,
}: {
  hasControlledFilters: boolean;
  previousKey: string | null;
  nextKey: string;
}) {
  return hasControlledFilters && previousKey !== null && previousKey !== nextKey;
}

const columns = [
  col.accessor((r) => r.annotations?.title ?? "", {
    id: "title",
    header: "轨迹",
    cell: (c) => {
      const title = c.getValue();
      const hash = c.row.original.content_hash.slice(0, 8);
      const tags = c.row.original.annotations?.tags;
      return (
        <div style={{ minWidth: 180 }}>
          <div style={{ fontWeight: 500, fontSize: 13 }}>
            {title || <span className="faint">{hash}</span>}
          </div>
          {title && <span className="mono faint" style={{ fontSize: 11 }}>{hash}</span>}
          <button
            className="copy-btn"
            title="复制完整 hash"
            onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(c.row.original.content_hash); }}
          >⎘</button>
          {tags && tags.length > 0 && (
            <div style={{ marginTop: 2, display: "flex", gap: 3, flexWrap: "wrap" }}>
              {tags.slice(0, 4).map((t) => (
                <span key={t} className="chip-sm" style={{ fontSize: 10, background: "var(--border-light)", color: "var(--dim)" }}>{t}</span>
              ))}
            </div>
          )}
        </div>
      );
    },
    enableSorting: false,
  }),
  col.accessor((r) => r.metrics?.turn_count ?? 0, { id: "turns", header: "turns" }),
  col.accessor((r) => r.metrics?.step_count ?? 0, { id: "steps", header: "steps" }),
  col.accessor((r) => r.metrics?.tool_count ?? 0, { id: "tools", header: "tools" }),
  col.accessor((r) => r.annotations?.resolution ?? "", {
    id: "resolution",
    header: "resolution",
    cell: (c) => {
      const v = c.getValue();
      if (!v) return <span className="faint">—</span>;
      const cls = v === "resolved" ? "res-ok" : v === "unresolved" ? "res-fail" : v === "indeterminate" ? "res-ind" : "res-part";
      return <span className={`chip-sm ${cls}`}>{formatListResolution(v)}</span>;
    },
    enableSorting: false,
  }),
  col.accessor((r) => r.annotations?.acceptance ?? "", {
    id: "acceptance",
    header: "accept",
    cell: (c) => {
      const v = c.getValue() as AcceptLikelihood | "";
      if (!v) return <span className="faint" title="无代码修改">—</span>;  // N/A
      const d = ACCEPT_DISPLAY[v];
      if (!d) return <span className="faint">—</span>;
      return (
        <span className={`chip-sm ${getListAcceptClass(v)}`}
          title={`修改被用户采纳的可能性：${d.zh}\n${d.hint}`}>
          {v}
        </span>
      );
    },
    enableSorting: false,
  }),
  col.accessor((r) => r.metrics?.pushback_count ?? 0, {
    id: "pb",
    header: "pb",
    cell: (c) => {
      const v = c.getValue();
      return v > 0 ? <span style={{ color: "var(--warn)" }}>{v}</span> : <span className="faint">0</span>;
    },
  }),
  col.accessor((r) => r.metrics?.error_steps ?? 0, {
    id: "errors",
    header: "errs",
    cell: (c) => {
      const v = c.getValue();
      return v > 0 ? <span style={{ color: "var(--warn)" }}>{v}</span> : <span className="faint">0</span>;
    },
    enableSorting: false,
  }),
  col.accessor((r) => r.metrics?.introduced_findings_count ?? -1, {
    id: "sec",
    header: "sec",
    cell: (c) => {
      const v = c.getValue();
      if (v < 0) return <span className="faint">—</span>;        // never scanned
      return v > 0 ? <span style={{ color: "var(--bad)" }}>{v}</span> : <span className="faint">0</span>;
    },
  }),
  col.accessor((r) => r.metrics?.overall_score ?? -1, {
    id: "score",
    header: "score",
    cell: (c) => <ScorePill v={c.getValue()} />,
  }),
  col.accessor("created_at", {
    id: "created_at",
    header: "created",
    cell: (c) => <span className="faint">{fmtDate(c.getValue())}</span>,
  }),
];

export function getListColumnIds() {
  return columns.map((column) => column.id);
}

interface ListViewProps {
  onOpen: (h: string) => void;
  datasetId?: string;
  filterRules?: FilterRule[];
  onFilterRulesChange?: (rules: FilterRule[]) => void;
}

export function ListView({ onOpen, datasetId, filterRules: controlledFilterRules, onFilterRulesChange }: ListViewProps) {
  // persist list UI state per dataset so it survives opening a sample (which
  // unmounts this view) and page reloads.
  const k = `list:${datasetId ?? "_all"}`;
  const [page, setPage] = useSticky(`${k}:page`, 0);
  const [pageSize, setPageSize] = useSticky<number>(`${k}:size`, 50);
  const [sorting, setSorting] = useSticky<SortingState>(`${k}:sort`, defaultSorting);
  const [localFilterRules, setLocalFilterRules] = useSticky<FilterRule[]>(`${k}:filters`, []);
  const filterRules = controlledFilterRules ?? localFilterRules;
  const setFilterRules = onFilterRulesChange ?? setLocalFilterRules;
  const filterRulesKey = JSON.stringify(filterRules.map((r) => [r.field, r.op, r.value]));
  const previousControlledFilterRulesKey = useRef<string | null>(null);

  // ephemeral selection: default-all-selected, so we only track EXCLUDED hashes
  // (un-checked rows). Survives paging within a session; resets on reload —
  // intentional, no persistence (see CLAUDE.md: trim/mask/selection don't touch
  // canonical). Filter change clears it: the matched set just changed.
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [exportMode, setExportMode] = useState(false);

  // derive server params from UI state
  const effectiveSorting = sorting.length > 0 ? sorting : defaultSorting;
  const { sortBy, sortDir } = getListSortParams(effectiveSorting);
  const apiFilters = useMemo(
    () => filterRules.map((r) => ({ field: r.field, op: r.op, value: r.value })),
    [filterRules],
  );

  const { data, error, isLoading, isFetching } = useQuery<PageResult>({
    queryKey: ["trajectories", datasetId, page, pageSize, sortBy, sortDir, apiFilters],
    queryFn: () => listTrajectories({
      limit: pageSize, offset: page * pageSize,
      sort_by: sortBy, sort_dir: sortDir,
      filters: apiFilters.length ? apiFilters : undefined,
    }, datasetId),
    placeholderData: keepPreviousData,
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const handlePageSizeChange = useCallback((size: number) => {
    setPageSize(size);
    setPage(0);
  }, []);

  const handleFilterChange = useCallback((rules: FilterRule[]) => {
    setFilterRules(rules);
    setPage(0);
    setExcluded(new Set());  // matched set changed → exclusions no longer meaningful
    setExportMode(false);
  }, [setFilterRules, setPage]);

  useEffect(() => {
    if (shouldResetListForExternalFilters({
      hasControlledFilters: Boolean(controlledFilterRules),
      previousKey: previousControlledFilterRulesKey.current,
      nextKey: filterRulesKey,
    })) {
      setPage(0);
      setExcluded(new Set());
      setExportMode(false);
    }
    previousControlledFilterRulesKey.current = filterRulesKey;
  }, [controlledFilterRules, filterRulesKey, setPage]);

  const toggleRow = useCallback((hash: string) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(hash)) next.delete(hash);
      else next.add(hash);
      return next;
    });
  }, []);

  // reset to page 0 when sort changes
  const handleSortChange = useCallback((updater: SortingState | ((old: SortingState) => SortingState)) => {
    setSorting(typeof updater === "function" ? updater(effectiveSorting) : updater);
    setPage(0);
  }, [effectiveSorting, setPage, setSorting]);

  const table = useReactTable({
    data: items,
    columns,
    state: { sorting: effectiveSorting },
    onSortingChange: handleSortChange,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
  });

  const handleRowClick = useCallback((hash: string) => {
    const sel = window.getSelection();
    if (sel && sel.toString().length > 0) return;
    onOpen(hash);
  }, [onOpen]);

  // export = matched set minus un-checked rows. selectedCount is exact across
  // pages: total is the server's filtered count, excluded is the un-check set.
  const selectedCount = Math.max(0, total - excluded.size);
  const showExportSelection = shouldShowExportSelection({ datasetId, total, exportMode });

  // For FilterBar: fetch all rows for enum/tag options (lightweight — only needed for dropdown hints)
  // ponytail: reuse current page data for options; at scale, a dedicated /facets endpoint is better
  const allLoadedRows = items;

  const isEmbedded = Boolean(datasetId);

  return (
    <div className={isEmbedded ? "list-view" : "page"}>
      {!isEmbedded && (
        <div className="list-header">
          <h1>traj-lens</h1>
          {isFetching && !isLoading && <span className="faint" style={{ fontSize: 11 }}>加载中…</span>}
        </div>
      )}

      <FilterBar rules={filterRules} onChange={handleFilterChange} rows={allLoadedRows} />

      {datasetId && total > 0 && (
        <ExportBar
          datasetId={datasetId}
          filters={apiFilters}
          excluded={excluded}
          selectedCount={selectedCount}
          onClearExclusions={() => setExcluded(new Set())}
          exportMode={exportMode}
          onStart={() => {
            setExcluded(new Set());
            setExportMode(true);
          }}
          onCancel={() => {
            setExcluded(new Set());
            setExportMode(false);
          }}
          onExportComplete={() => {
            setExcluded(new Set());
            setExportMode(false);
          }}
        />
      )}

      {total > 0 && (
        <div className="stats-bar">
          <span><b>{total}</b> 条轨迹</span>
          <span>第 {page + 1}/{totalPages} 页</span>
        </div>
      )}

      {error && <p className="error">{String(error)}</p>}
      {isLoading && <p className="dim" style={{ textAlign: "center", padding: 40 }}>加载中…</p>}

      {!isLoading && total === 0 && (
        <div className="empty-state">
          {filterRules.length > 0
            ? <p>无匹配结果，试试调整筛选条件</p>
            : <>
                <p>暂无轨迹数据</p>
                <p>使用 <code>trajlens ingest &lt;file&gt;</code> 导入</p>
              </>}
        </div>
      )}

      {items.length > 0 && (
        <table className="list">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {showExportSelection && (
                  <th style={{ width: 28 }}>
                    <input
                      type="checkbox"
                      title="全选/取消当前页"
                      checked={items.every((r) => !excluded.has(r.content_hash))}
                      onChange={(e) => {
                        setExcluded((prev) => {
                          const next = new Set(prev);
                          for (const r of items) {
                            if (e.target.checked) next.delete(r.content_hash);
                            else next.add(r.content_hash);
                          }
                          return next;
                        });
                      }}
                    />
                  </th>
                )}
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    onClick={h.column.getToggleSortingHandler()}
                    className={h.column.getCanSort() ? "sortable" : ""}
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {h.column.getIsSorted() === "asc" ? " ↑" : ""}
                    {h.column.getIsSorted() === "desc" ? " ↓" : ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} onClick={() => handleRowClick(row.original.content_hash)}>
                {showExportSelection && (
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={!excluded.has(row.original.content_hash)}
                      onChange={() => toggleRow(row.original.content_hash)}
                    />
                  </td>
                )}
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {total > 0 && (
        <Pagination page={page} totalPages={totalPages} pageSize={pageSize}
          onChange={setPage} onPageSizeChange={handlePageSizeChange} />
      )}
    </div>
  );
}

// ── Export bar ──────────────────────────────────────────────────────────

const EXPORT_FORMATS = ["panguml2"];  // ponytail: add as exporters register
export const EXPORT_MODE_HINT = "基于当前筛选后的样本集创建，进入后可勾选或取消再导出。";

function ExportBar({
  datasetId,
  filters,
  excluded,
  selectedCount,
  onClearExclusions,
  exportMode,
  onStart,
  onCancel,
  onExportComplete,
}: {
  datasetId: string;
  filters: { field: string; op: string; value: string }[];
  excluded: Set<string>;
  selectedCount: number;
  onClearExclusions: () => void;
  exportMode: boolean;
  onStart: () => void;
  onCancel: () => void;
  onExportComplete: () => void;
}) {
  const [format, setFormat] = useState(EXPORT_FORMATS[0]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const { data: exports = [], refetch } = useQuery({
    queryKey: ["exports", datasetId],
    queryFn: () => listExports(datasetId),
  });

  const remove = async (id: string) => {
    await deleteExport(id);
    refetch();
  };

  const COLLAPSE_AT = 3;
  const shown = showAll ? exports : exports.slice(0, COLLAPSE_AT);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const art = await createExport(datasetId, {
        format,
        filters: filters.length ? filters : undefined,
        exclude_hashes: excluded.size ? [...excluded] : undefined,
      });
      refetch();
      onExportComplete();
      window.open(downloadExportUrl(art.id), "_blank");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="export-bar">
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        {exportMode ? (
          <>
            <button className="btn btn-sm active" onClick={run} disabled={busy || selectedCount === 0}>
              {busy ? "导出中…" : `导出 ${selectedCount} 条`}
            </button>
            <select className="btn btn-sm btn-ghost" value={format}
              onChange={(e) => setFormat(e.target.value)} disabled={busy}>
              {EXPORT_FORMATS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <button className="btn btn-sm btn-ghost" onClick={onCancel} disabled={busy}>取消</button>
            {excluded.size > 0 && (
              <span className="faint" style={{ fontSize: 11 }}>
                已取消 {excluded.size} 条 ·
                <button className="link-btn" onClick={onClearExclusions} style={{ marginLeft: 4 }}>恢复全选</button>
              </span>
            )}
          </>
        ) : (
          <>
            <button className="btn btn-sm active" onClick={onStart}>创建导出</button>
            <span className="faint" style={{ fontSize: 11 }}>{EXPORT_MODE_HINT}</span>
            {exports.length > 0 && (
              <span className="faint" style={{ fontSize: 11 }}>导出历史</span>
            )}
          </>
        )}
        {err && <span className="dim" style={{ fontSize: 11, color: "var(--bad)" }}>{err}</span>}
      </div>
      {exports.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
          {shown.map((x: ExportArtifact) => {
            const cfg = x.config ?? {};
            const flt = cfg.filters ?? [];
            // Prefer matched as the denominator; full-select reads "5/5" too,
            // making "filtered then kept all" explicit. Fall back to traj_count
            // only for pre-config legacy rows.
            const mat = cfg.matched ?? x.traj_count;
            const sel = cfg.selected ?? x.traj_count;
            return (
              <div key={x.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, flexWrap: "wrap" }}>
                <span className="chip-sm">{x.exporter}</span>
                <span className="faint">{sel}/{mat} 条</span>
                <span className="faint" style={{ fontSize: 11 }}>
                  {flt.length
                    ? flt.map((f) => `${f.field}${f.op}${f.value}`).join(" · ")
                    : "全部（无筛选）"}
                </span>
                <span className="faint">{x.created_at?.slice(0, 19).replace("T", " ")}</span>
                <a className="link-btn" href={downloadExportUrl(x.id)} target="_blank" rel="noreferrer">↓ 下载</a>
                <button className="link-btn" onClick={() => remove(x.id)}
                  style={{ color: "var(--bad)" }}>✕ 删除</button>
              </div>
            );
          })}
          {exports.length > COLLAPSE_AT && (
            <button className="link-btn" style={{ alignSelf: "flex-start", marginTop: 2 }}
              onClick={() => setShowAll((s) => !s)}>
              {showAll ? "收起" : `展开全部 ${exports.length} 条`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Pagination ─────────────────────────────────────────────────────────

function Pagination({ page, totalPages, pageSize, onChange, onPageSizeChange }: {
  page: number; totalPages: number; pageSize: number;
  onChange: (p: number) => void; onPageSizeChange: (s: number) => void;
}) {
  const [jumpVal, setJumpVal] = useState("");

  const handleJump = () => {
    const n = parseInt(jumpVal, 10);
    if (!isNaN(n) && n >= 1 && n <= totalPages) {
      onChange(n - 1);
      setJumpVal("");
    }
  };

  // ponytail: compact page buttons — show at most 7, ellipsis collapses the rest
  const pages: (number | "...")[] = [];
  if (totalPages <= 7) {
    for (let i = 0; i < totalPages; i++) pages.push(i);
  } else {
    pages.push(0);
    if (page > 2) pages.push("...");
    for (let i = Math.max(1, page - 1); i <= Math.min(totalPages - 2, page + 1); i++) pages.push(i);
    if (page < totalPages - 3) pages.push("...");
    pages.push(totalPages - 1);
  }

  return (
    <div className="pagination">
      <div className="page-size-picker">
        {PAGE_SIZES.map((s) => (
          <button key={s} className={`page-size-btn ${s === pageSize ? "active" : ""}`}
            onClick={() => onPageSizeChange(s)}>{s}</button>
        ))}
        <span className="faint" style={{ fontSize: 11, marginLeft: 2 }}>条/页</span>
      </div>
      <div className="page-nav">
        <button className="page-btn" disabled={page === 0} onClick={() => onChange(0)} title="首页">«</button>
        <button className="page-btn" disabled={page === 0} onClick={() => onChange(page - 1)}>‹</button>
        {pages.map((p, i) =>
          p === "..."
            ? <span key={`e${i}`} className="page-ellipsis">…</span>
            : <button key={p} className={`page-btn ${p === page ? "active" : ""}`} onClick={() => onChange(p)}>{p + 1}</button>
        )}
        <button className="page-btn" disabled={page >= totalPages - 1} onClick={() => onChange(page + 1)}>›</button>
        <button className="page-btn" disabled={page >= totalPages - 1} onClick={() => onChange(totalPages - 1)} title="末页">»</button>
        {totalPages > 7 && (
          <span className="page-jump">
            <input className="page-jump-input" type="text" inputMode="numeric" placeholder={`${page + 1}/${totalPages}`}
              value={jumpVal} onChange={(e) => setJumpVal(e.target.value.replace(/\D/g, ""))}
              onKeyDown={(e) => { if (e.key === "Enter") handleJump(); }} />
            <button className="page-jump-go" onClick={handleJump}>跳转</button>
          </span>
        )}
      </div>
    </div>
  );
}
