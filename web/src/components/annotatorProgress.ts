import type { JobInfo } from "../api";

export interface AnnotatorProgressSummary {
  finished: number;
  total: number | null;
  pct: number;
  pending: number;
}

function jobTime(job: JobInfo): number {
  return job.created_at ? new Date(job.created_at).getTime() || 0 : 0;
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
    return { text: `calling LLM… ${finished}/${job.total}`, color: "var(--warn)" };
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
  const latest = new Map<string, JobInfo>();
  for (const job of jobs) {
    const cur = latest.get(job.annotator_id);
    if (!cur || !job.created_at || !cur.created_at || jobTime(job) >= jobTime(cur)) {
      latest.set(job.annotator_id, job);
    }
  }
  return jobs.filter((job) => latest.get(job.annotator_id)?.job_id === job.job_id);
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
