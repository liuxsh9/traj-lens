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
}

export interface Trajectory {
  content_hash: string;
  items: Item[];
  tools: unknown[];
  meta: Record<string, unknown>;
  annotations?: Annotation[];
}

export interface TrajSummary {
  content_hash: string;
  items_count: number;
  created_at: string;
}

export async function listTrajectories(): Promise<TrajSummary[]> {
  const r = await fetch("/api/v1/trajectories");
  if (!r.ok) throw new Error(`list failed: ${r.status}`);
  return r.json();
}

export async function getTrajectory(hash: string): Promise<Trajectory> {
  const r = await fetch(`/api/v1/trajectories/${hash}`);
  if (!r.ok) throw new Error(`get failed: ${r.status}`);
  return r.json();
}
