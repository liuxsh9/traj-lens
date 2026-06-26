import type { JobInfo } from "../api";

export interface AnnotatorProgressSummary {
  finished: number;
  total: number | null;
  pct: number;
  pending: number;
}

function jobProgress(job: JobInfo): number {
  if (job.status !== "pending") return 1;
  const total = job.total ?? 0;
  if (total <= 0) return 0;
  const finished = (job.done ?? 0) + (job.skipped ?? 0);
  return Math.max(0, Math.min(1, finished / total));
}

function jobTime(job: JobInfo): number {
  return job.created_at ? new Date(job.created_at).getTime() || 0 : 0;
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
  const pct = activeJobs.length
    ? Math.round(
      (activeJobs.reduce((sum, job) => sum + jobProgress(job), 0) / activeJobs.length) * 100,
    )
    : 0;
  const pending = activeJobs.filter((job) => job.status === "pending").length;
  return { finished, total: total || null, pct, pending };
}
