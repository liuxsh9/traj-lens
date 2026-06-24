export interface Provenance {
  content_hash: string;
  origin: string;
  raw_sha: string | null;
}

export interface Item {
  type: "message" | "reasoning" | "function_call" | "function_call_output";
  role?: string;
  content?: string;
  name?: string;
  arguments?: string;
  call_id?: string;
  output?: string;
  step_id: number | null;
  run_id: number | null;
  provenance: Provenance | null;
}

export interface Annotation {
  target_hash: string;
  annotator_id: string;
  annotator_version: string;
  value: string;
  produced_at: string;
  target_type?: string;
  target_idx?: number;
}

export interface CodeChange {
  item_idx: number;
  step_id: number | null;
  run_id: number | null;
  tool: string;
  op: "create" | "edit" | "delete" | "run";
  path: string | null;
  old: string | null;
  new: string | null;
  command: string | null;
}

export interface Trajectory {
  content_hash: string;
  items: Item[];
  tools: unknown[];
  meta: Record<string, unknown>;
  annotations?: Annotation[];
  code_changes?: CodeChange[];
  metrics?: Record<string, number | null>;
}

export interface TrajSummary {
  content_hash: string;
  items_count: number;
  created_at: string;
  metrics: Record<string, number>;
  annotations: {
    resolution?: string;
    title?: string;
    summary?: string;
    tags?: string[];
    interrupted?: boolean;
  };
}

export interface PageResult {
  items: TrajSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ListParams {
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_dir?: string;
  filters?: { field: string; op: string; value: string }[];
}

export async function listTrajectories(params: ListParams = {}, datasetId?: string): Promise<PageResult> {
  const q = new URLSearchParams();
  if (params.limit) q.set("limit", String(params.limit));
  if (params.offset) q.set("offset", String(params.offset));
  if (params.sort_by) q.set("sort_by", params.sort_by);
  if (params.sort_dir) q.set("sort_dir", params.sort_dir);
  if (params.filters?.length) q.set("filters", JSON.stringify(params.filters));
  const base = datasetId
    ? `/api/v1/datasets/${datasetId}/trajectories`
    : `/api/v1/trajectories`;
  const r = await fetch(`${base}?${q}`);
  if (!r.ok) throw new Error(`list failed: ${r.status}`);
  return r.json();
}

// ── Dataset API ──────────────────────────────────────────────────────

export interface Dataset {
  id: string;
  name: string;
  description: string;
  traj_count: number;
  batch_count: number;
  created_at: string;
}

export interface Batch {
  id: string;
  dataset_id: string;
  name: string;
  format: string;
  traj_count: number;
  created_at: string;
}

export async function listDatasets(): Promise<Dataset[]> {
  const r = await fetch("/api/v1/datasets");
  if (!r.ok) throw new Error(`list datasets failed: ${r.status}`);
  return r.json();
}

export async function createDataset(name: string, description = ""): Promise<Dataset> {
  const r = await fetch("/api/v1/datasets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description }),
  });
  if (!r.ok) throw new Error(`create dataset failed: ${r.status}`);
  return r.json();
}

export async function deleteDataset(id: string): Promise<void> {
  const r = await fetch(`/api/v1/datasets/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`delete dataset failed: ${r.status}`);
}

export async function listBatches(datasetId: string): Promise<Batch[]> {
  const r = await fetch(`/api/v1/datasets/${datasetId}/batches`);
  if (!r.ok) throw new Error(`list batches failed: ${r.status}`);
  return r.json();
}

export interface DatasetStats {
  total: number;
  metrics: Record<string, { min: number; max: number; avg: number; count: number }>;
  resolution: Record<string, number>;
  top_tags: { tag: string; count: number }[];
  batches: Batch[];
}

export async function getDatasetStats(datasetId: string): Promise<DatasetStats> {
  const r = await fetch(`/api/v1/datasets/${datasetId}/stats`);
  if (!r.ok) throw new Error(`stats failed: ${r.status}`);
  return r.json();
}

// ── Upload / Annotate API ───────────────────────────────────────────

export interface UploadResult {
  count: number;
  errors_count: number;
  errors: string[];
  batch_id: string | null;
}

export async function uploadToDataset(datasetId: string, file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(`/api/v1/datasets/${datasetId}/upload`, { method: "POST", body: form });
  if (!r.ok) throw new Error(`upload failed: ${r.status}`);
  return r.json();
}

export interface AnnotatorInfo {
  id: string;
  type: string;
  target: string;
  path: string;
}

export async function listAnnotators(): Promise<AnnotatorInfo[]> {
  const r = await fetch("/api/v1/annotators");
  if (!r.ok) throw new Error(`list annotators failed: ${r.status}`);
  return r.json();
}

export interface JobInfo {
  job_id: string;
  annotator_id: string;
  status: string;
  total?: number;
  done?: number;
  skipped?: number;
  errors?: string;
}

export async function computeMetrics(datasetId?: string): Promise<{ computed: number }> {
  const r = await fetch("/api/v1/metrics/compute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(datasetId ? { dataset_id: datasetId } : {}),
  });
  if (!r.ok) throw new Error(`compute metrics failed: ${r.status}`);
  return r.json();
}

export async function createJob(annotatorPath: string, datasetId?: string): Promise<JobInfo> {
  const body: Record<string, string> = { annotator: annotatorPath };
  if (datasetId) body.dataset_id = datasetId;
  const r = await fetch("/api/v1/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`create job failed: ${r.status}`);
  return r.json();
}

export async function getJob(jobId: string): Promise<JobInfo> {
  const r = await fetch(`/api/v1/jobs/${jobId}`);
  if (!r.ok) throw new Error(`get job failed: ${r.status}`);
  return r.json();
}

export async function getTrajectory(hash: string): Promise<Trajectory> {
  const r = await fetch(`/api/v1/trajectories/${hash}`);
  if (!r.ok) throw new Error(`get failed: ${r.status}`);
  return r.json();
}

export interface SemgrepFinding {
  item_idx: number;
  check_id: string;
  severity: string;
  message: string;
  line: number | null;
}

export interface SemgrepResult {
  available: boolean;
  scanned: number;
  findings: SemgrepFinding[];
  error?: string;
}

export async function scanSemgrep(hash: string): Promise<SemgrepResult> {
  const r = await fetch(`/api/v1/trajectories/${hash}/semgrep`, { method: "POST" });
  if (!r.ok) throw new Error(`semgrep scan failed: ${r.status}`);
  return r.json();
}

// ── Grouping helpers (frontend projection from backend-tagged items) ──

export interface TurnGroup {
  kind: "user" | "run";
  run_id: number | null;
  items: Item[];
}

export interface StepGroup {
  step_id: number;
  run_id: number;
  items: Item[];
}

export function groupByTurns(items: Item[]): TurnGroup[] {
  const groups: TurnGroup[] = [];
  let cur: TurnGroup | null = null;
  for (const it of items) {
    const isUser = it.run_id === null;
    const kind = isUser ? "user" : "run";
    if (!cur || cur.kind !== kind || (!isUser && cur.run_id !== it.run_id)) {
      cur = { kind, run_id: it.run_id, items: [] };
      groups.push(cur);
    }
    cur.items.push(it);
  }
  return groups;
}

export function groupBySteps(items: Item[]): StepGroup[] {
  const groups: StepGroup[] = [];
  let cur: StepGroup | null = null;
  for (const it of items) {
    if (it.step_id === null || it.run_id === null) continue;
    if (!cur || cur.step_id !== it.step_id) {
      cur = { step_id: it.step_id, run_id: it.run_id, items: [] };
      groups.push(cur);
    }
    cur.items.push(it);
  }
  return groups;
}

export function findPushback(annotations: Annotation[]): Map<number, Annotation> {
  const map = new Map<number, Annotation>();
  if (!annotations) return map;
  for (const a of annotations) {
    if (a.annotator_id !== "pushback") continue;
    let parsed: Record<string, unknown> = {};
    try { parsed = JSON.parse(a.value); } catch { continue; }
    if (parsed.category && parsed.category !== "none") {
      const idx = annotations.indexOf(a);
      map.set(idx, a);
    }
  }
  return map;
}

export function parseAnnotationValue(a: Annotation): Record<string, unknown> {
  try { return JSON.parse(a.value); } catch { return {}; }
}
