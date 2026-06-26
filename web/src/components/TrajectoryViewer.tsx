import { useState, useRef, useCallback, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getTrajectory, groupByTurns, groupBySteps, parseAnnotationValue } from "../api";
import { SessionHeader } from "./SessionHeader";
import { Minimap } from "./Minimap";
import { CardStack, PinnedUser, PinnedReply } from "./CardStack";
import { TrimBar } from "./TrimBar";
import { ChangesPanel } from "./ChangesPanel";

export function TrajectoryViewer({ hash, onBack }: { hash: string; onBack: () => void }) {
  const { data: traj, error, isLoading } = useQuery({
    queryKey: ["trajectory", hash],
    queryFn: () => getTrajectory(hash),
  });

  const cardsRef = useRef<HTMLDivElement>(null);
  const [vpTop, setVpTop] = useState(0);
  const [vpHeight, setVpHeight] = useState(0.3);

  // ── Default: runs expanded, steps collapsed, bookends open ──
  const initialExpanded = useMemo(() => {
    if (!traj) return new Set<string>();
    const set = new Set<string>();
    const turns = groupByTurns(traj.items);
    for (const t of turns) {
      if (t.kind === "run" && t.run_id !== null) {
        set.add(`run-${t.run_id}`);
      }
    }
    return set;
  }, [traj]);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    setExpanded(initialExpanded);
  }, [initialExpanded]);

  const onToggle = useCallback((key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const onExpandAll = useCallback(() => {
    if (!traj) return;
    const set = new Set<string>();
    const turns = groupByTurns(traj.items);
    for (const t of turns) {
      if (t.kind === "run" && t.run_id !== null) {
        set.add(`run-${t.run_id}`);
        for (const s of groupBySteps(t.items)) set.add(`${s.run_id}-${s.step_id}`);
      }
    }
    setExpanded(set);
  }, [traj]);

  const onCollapseAll = useCallback(() => {
    // Keep runs + pinned bookends expanded, only collapse steps
    setExpanded((prev) => {
      const next = new Set<string>();
      for (const k of prev) {
        if (k.startsWith("run-") || k.startsWith("pinned-")) next.add(k);
      }
      return next;
    });
  }, []);

  // ── Scroll sync for minimap ──
  const syncViewport = useCallback(() => {
    const el = cardsRef.current;
    if (!el) return;
    const top = el.scrollTop / el.scrollHeight;
    const height = el.clientHeight / el.scrollHeight;
    setVpTop(top);
    setVpHeight(height);
  }, []);

  // Re-sync after expand/collapse changes content height
  useEffect(() => {
    requestAnimationFrame(syncViewport);
  }, [expanded, syncViewport]);

  // ── Pushback indices for minimap flags ──
  const pushbackIndices = useMemo(() => {
    const set = new Set<number>();
    if (!traj?.annotations) return set;
    // Mark user message items that precede a pushback
    // ponytail: approximate — flag all user messages if any pushback exists
    const hasPushback = traj.annotations.some((a) => {
      if (a.annotator_id !== "pushback") return false;
      const v = parseAnnotationValue(a);
      return v.category && v.category !== "none";
    });
    if (hasPushback) {
      traj.items.forEach((it, i) => {
        if (it.type === "message" && it.role === "user" && i > 0) set.add(i);
      });
    }
    return set;
  }, [traj]);

  // ── Click minimap tick → scroll cards ──
  const onClickTick = useCallback((index: number) => {
    // Approximate: scroll the card container proportionally
    const el = cardsRef.current;
    if (!el || !traj) return;
    const fraction = index / traj.items.length;
    el.scrollTo({ top: fraction * el.scrollHeight, behavior: "smooth" });
  }, [traj]);

  // ── Keyboard shortcuts ──
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onBack();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onBack]);

  if (error) {
    return (
      <div className="page-viewer">
        <button className="btn" onClick={onBack}>← 返回列表</button>
        <p className="error" style={{ marginTop: 20 }}>{String(error)}</p>
      </div>
    );
  }

  if (isLoading || !traj) {
    return (
      <div className="page-viewer">
        <button className="btn" onClick={onBack}>← 返回列表</button>
        <p className="dim" style={{ textAlign: "center", padding: 40 }}>加载中…</p>
      </div>
    );
  }

  // Extract first user turn items for the pinned bookend
  const turns = groupByTurns(traj.items);
  const firstUserTurn = turns.find((t) => t.kind === "user");

  return (
    <div className="page-viewer">
      <div className="frame">
        <SessionHeader
          items={traj.items}
          annotations={traj.annotations ?? []}
          score={traj.metrics?.overall_score ?? null}
          onBack={onBack}
          onExpandAll={onExpandAll}
          onCollapseAll={onCollapseAll}
        />
        <ChangesPanel changes={traj.code_changes ?? []} hash={hash} onJump={onClickTick}
          persisted={traj.security_findings} scannedBefore={!!traj.security_scan} />
        {firstUserTurn && (
          <PinnedUser
            items={firstUserTurn.items}
            annotations={traj.annotations ?? []}
            isExpanded={expanded.has("pinned-user")}
            onToggle={() => onToggle("pinned-user")}
          />
        )}
        <div className="two">
          <Minimap
            items={traj.items}
            pushbackIndices={pushbackIndices}
            viewportTop={vpTop}
            viewportHeight={vpHeight}
            onClickTick={onClickTick}
          />
          <div className="cards" ref={cardsRef} onScroll={syncViewport}>
            <CardStack
              items={traj.items}
              annotations={traj.annotations ?? []}
              expanded={expanded}
              onToggle={onToggle}
            />
          </div>
        </div>
        <PinnedReply
          items={traj.items}
          isExpanded={expanded.has("pinned-reply")}
          onToggle={() => onToggle("pinned-reply")}
        />
        <TrimBar />
      </div>
    </div>
  );
}
