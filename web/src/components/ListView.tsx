import { useState, useCallback, useMemo } from "react";
import { useSticky } from "../useSticky";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from "@tanstack/react-table";
import { listTrajectories, type TrajSummary, type PageResult } from "../api";
import { FilterBar, type FilterRule } from "./FilterBar";

const PAGE_SIZES = [10, 25, 50, 100] as const;
const col = createColumnHelper<TrajSummary>();

function fmtDate(iso: string) {
  return iso.slice(5, 16).replace("T", " ");
}

function ScorePill({ v }: { v: number }) {
  if (v < 0) return <span className="faint">—</span>;
  const cls = v >= 80 ? "score-good" : v >= 40 ? "score-mid" : "score-bad";
  return <span className={`chip-sm ${cls}`}>{v}</span>;
}

// ponytail: sort_by map — column id → backend field name
const sortFieldMap: Record<string, string> = {
  turns: "turns", steps: "steps", tools: "tools",
  pb: "pushback_count", score: "score", sec: "security_findings", created_at: "created_at",
};

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
  col.accessor((r) => r.metrics?.success_score ?? -1, {
    id: "score",
    header: "score",
    cell: (c) => <ScorePill v={c.getValue()} />,
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
  col.accessor((r) => r.annotations?.resolution ?? "", {
    id: "resolution",
    header: "resolution",
    cell: (c) => {
      const v = c.getValue();
      if (!v) return <span className="faint">—</span>;
      const cls = v === "resolved" ? "res-ok" : v === "unresolved" ? "res-fail" : v === "indeterminate" ? "res-ind" : "res-part";
      return <span className={`chip-sm ${cls}`}>{v}</span>;
    },
    enableSorting: false,
  }),
  col.accessor("created_at", {
    header: "created",
    cell: (c) => <span className="faint">{fmtDate(c.getValue())}</span>,
  }),
];

export function ListView({ onOpen, datasetId }: { onOpen: (h: string) => void; datasetId?: string }) {
  // persist list UI state per dataset so it survives opening a sample (which
  // unmounts this view) and page reloads.
  const k = `list:${datasetId ?? "_all"}`;
  const [page, setPage] = useSticky(`${k}:page`, 0);
  const [pageSize, setPageSize] = useSticky<number>(`${k}:size`, 50);
  const [sorting, setSorting] = useSticky<SortingState>(`${k}:sort`, []);
  const [filterRules, setFilterRules] = useSticky<FilterRule[]>(`${k}:filters`, []);

  // derive server params from UI state
  const sortBy = sorting[0]?.id ? (sortFieldMap[sorting[0].id] ?? "created_at") : "created_at";
  const sortDir = sorting[0]?.desc === false ? "asc" : "desc";
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
  }, []);

  // reset to page 0 when sort changes
  const handleSortChange = useCallback((updater: SortingState | ((old: SortingState) => SortingState)) => {
    setSorting(updater);
    setPage(0);
  }, []);

  const table = useReactTable({
    data: items,
    columns,
    state: { sorting },
    onSortingChange: handleSortChange,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
  });

  const handleRowClick = useCallback((hash: string) => {
    const sel = window.getSelection();
    if (sel && sel.toString().length > 0) return;
    onOpen(hash);
  }, [onOpen]);

  // For FilterBar: fetch all rows for enum/tag options (lightweight — only needed for dropdown hints)
  // ponytail: reuse current page data for options; at scale, a dedicated /facets endpoint is better
  const allLoadedRows = items;

  return (
    <div className="page">
      <div className="list-header">
        <h1>traj-lens</h1>
        {isFetching && !isLoading && <span className="faint" style={{ fontSize: 11 }}>加载中…</span>}
      </div>

      <FilterBar rules={filterRules} onChange={handleFilterChange} rows={allLoadedRows} />

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
