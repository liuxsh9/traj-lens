import type { JobInfo } from "../api";

export interface AnnotatorProgressSummary {
  finished: number;
  total: number | null;
  pct: number;
  pending: number;
}

export type WorkflowTaskStatus = "pending" | "running" | "done" | "failed";

export interface WorkflowProgressTask {
  id: string;
  status: WorkflowTaskStatus;
  innerPct?: number;
  weight?: number;
}

export interface WorkflowProgressSummary {
  finishedSlots: number;
  totalSlots: number;
  pct: number;
  pending: number;
  running: number;
}

function fmtSlot(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function jobTime(job: JobInfo): number {
  return job.created_at ? new Date(job.created_at).getTime() || 0 : 0;
}

function jobUpdateTime(job: JobInfo): number {
  return job.updated_at ? new Date(job.updated_at).getTime() || 0 : jobTime(job);
}

export function jobErrCount(job: JobInfo): number {
  if (!job.errors) return 0;
  try { return JSON.parse(job.errors).length; } catch { return 0; }
}

function fmtDuration(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  return rem > 0 ? `${hours}h ${rem}m` : `${hours}h`;
}

export function formatJobTiming(job: JobInfo, now = Date.now()): string {
  if (!job.created_at) return "";
  const created = Date.parse(job.created_at);
  if (!Number.isFinite(created)) return "";
  const updated = job.updated_at ? Date.parse(job.updated_at) : NaN;
  if (job.status === "pending") {
    const parts = [`elapsed ${fmtDuration(now - created)}`];
    if (Number.isFinite(updated)) parts.push(`updated ${fmtDuration(now - updated)} ago`);
    return parts.join(" · ");
  }
  if (Number.isFinite(updated)) return `took ${fmtDuration(updated - created)}`;
  return "";
}

export function formatJobLabel(job: JobInfo): { text: string; color: string } {
  if (job.status === "error") return { text: "failed", color: "var(--bad)" };
  if (job.status === "interrupted") {
    const prog = job.total ? ` at ${job.done ?? 0}/${job.total}` : "";
    return { text: `interrupted${prog} · re-run to resume`, color: "var(--warn)" };
  }
  if (job.status === "pending") {
    if ((job.queued_behind ?? 0) > 0 && !job.total) {
      const n = job.queued_behind ?? 0;
      return { text: `queued behind ${n} job${n === 1 ? "" : "s"}`, color: "var(--warn)" };
    }
    if (!job.total) return { text: "preparing targets…", color: "var(--warn)" };
    const finished = (job.done ?? 0) + (job.skipped ?? 0);
    return { text: `processing targets… ${finished}/${job.total}`, color: "var(--warn)" };
  }
  const done = job.done ?? 0, skipped = job.skipped ?? 0, errs = jobErrCount(job);
  const parts: string[] = [];
  if (done > 0) parts.push(`${done} new`);
  if (skipped > 0) parts.push(`${skipped} cached`);
  if (errs > 0) parts.push(`${errs} errors`);
  if (parts.length === 0) parts.push("nothing to do");
  return { text: `✓ ${parts.join(" · ")}`, color: errs > 0 ? "var(--warn)" : "var(--good)" };
}

export function keepLatestJobsByAnnotator(jobs: JobInfo[]): JobInfo[] {
  const byId = new Map<string, JobInfo>();
  for (const job of jobs) {
    const cur = byId.get(job.job_id);
    if (!cur || jobUpdateTime(job) >= jobUpdateTime(cur)) {
      byId.set(job.job_id, job);
    }
  }

  const latest = new Map<string, JobInfo>();
  for (const job of byId.values()) {
    const cur = latest.get(job.annotator_id);
    if (!cur || !job.created_at || !cur.created_at || jobTime(job) >= jobTime(cur)) {
      latest.set(job.annotator_id, job);
    }
  }
  return [...byId.values()].filter((job) => latest.get(job.annotator_id)?.job_id === job.job_id);
}

export function summarizeAnnotatorProgress(activeJobs: JobInfo[]): AnnotatorProgressSummary {
  const finished = activeJobs.reduce(
    (sum, job) => sum + (job.done ?? 0) + (job.skipped ?? 0),
    0,
  );
  const total = activeJobs.reduce((sum, job) => sum + (job.total ?? 0), 0);
  const pending = activeJobs.filter((job) => job.status === "pending").length;
  const hasPendingWithoutTotal = activeJobs.some(
    (job) => job.status === "pending" && !(job.total && job.total > 0),
  );
  const pct = total > 0 && !hasPendingWithoutTotal
    ? Math.round((finished / total) * 100)
    : 0;
  return { finished, total: total || null, pct, pending };
}

export function summarizeWorkflowProgress(tasks: WorkflowProgressTask[]): WorkflowProgressSummary {
  const totalSlots = tasks.reduce((sum, task) => sum + (task.weight ?? 1), 0);
  const finishedSlots = tasks.reduce((sum, task) => {
    const weight = task.weight ?? 1;
    if (task.status === "done" || task.status === "failed") return sum + weight;
    if (task.status !== "running") return sum;
    const innerPct = Math.max(0, Math.min(100, task.innerPct ?? 0));
    return sum + weight * (innerPct / 100);
  }, 0);
  const pct = totalSlots > 0 ? Math.round((finishedSlots / totalSlots) * 100) : 0;
  return {
    finishedSlots,
    totalSlots,
    pct,
    pending: tasks.filter((task) => task.status === "pending").length,
    running: tasks.filter((task) => task.status === "running").length,
  };
}

export function workflowTaskFromJob(job: JobInfo): WorkflowProgressTask {
  if (job.status === "pending") {
    const total = job.total ?? 0;
    const finished = (job.done ?? 0) + (job.skipped ?? 0);
    return {
      id: job.job_id,
      status: total > 0 ? "running" : "pending",
      innerPct: total > 0 ? Math.round((finished / total) * 100) : 0,
    };
  }
  if (job.status === "done") return { id: job.job_id, status: "done" };
  return { id: job.job_id, status: "failed" };
}

export function workflowTaskFromMetrics(metrics: { status: "pending" | "done" | "error"; computed?: number } | null): WorkflowProgressTask | null {
  if (!metrics) return null;
  if (metrics.status === "pending") return { id: "metrics", status: "running", innerPct: 0 };
  if (metrics.status === "done") return { id: "metrics", status: "done" };
  return { id: "metrics", status: "failed" };
}

export function buildWorkflowTasks(
  plan: string[],
  jobs: JobInfo[],
  metrics: { status: "pending" | "done" | "error"; computed?: number } | null,
): WorkflowProgressTask[] {
  const byAnnotator = new Map(jobs.map((job) => [job.annotator_id, job]));
  const planned = plan.map((id): WorkflowProgressTask => {
    if (id === "metrics") {
      return workflowTaskFromMetrics(metrics) ?? { id, status: "pending" };
    }
    const plannedJob = byAnnotator.get(id);
    return plannedJob ? workflowTaskFromJob(plannedJob) : { id, status: "pending" };
  });
  const plannedIds = new Set(plan);
  const extras = jobs
    .filter((job) => !plannedIds.has(job.annotator_id))
    .map(workflowTaskFromJob);
  return [...planned, ...extras];
}

export function formatWorkflowProgressLabel(summary: WorkflowProgressSummary): string {
  return [
    "Workflow progress",
    `${fmtSlot(summary.finishedSlots)}/${fmtSlot(summary.totalSlots)} tasks`,
    `${summary.pct}% overall`,
    `${summary.running} running`,
    `${summary.pending} waiting`,
  ].join(" · ");
}
