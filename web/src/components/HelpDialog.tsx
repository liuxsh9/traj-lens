import { useEffect, useState } from "react";

export const SCORE_FORMULA_TEXT = "resolved=100, partially_resolved=50, unresolved=0; each pushback subtracts 5 points, capped at half of the base score.";

export const HELP_SECTIONS = [
  {
    title: "What It Is",
    items: [
      "traj-lens is a trajectory analysis platform for coding agents, covering ingestion, normalization, annotation, metrics, review, and training-data export.",
      "It keeps two layers of truth: raw bytes for reproducible export, and canonical Items for analysis.",
    ],
  },
  {
    title: "Key Capabilities",
    items: [
      "Ingest multiple log formats such as OpenAI messages, Codex, and swe_chat, then normalize them into one trajectory model.",
      "Organize samples by dataset with filtering, sorting, batch annotation, metric refresh, security scanning, and export.",
      "Inspect each trajectory through turn and step groups, tool calls, code changes, error recovery, pushback, and the final reply.",
    ],
  },
  {
    title: "Scoring",
    items: [
      `overall_score starts from the resolution base score and subtracts the pushback penalty: ${SCORE_FORMULA_TEXT}`,
      "resolved means the task was completed, partially_resolved means only part of it was completed, and unresolved means it was not solved.",
      "pushback counts user corrections or objections during the trajectory. The initial user request is not counted as pushback.",
    ],
  },
  {
    title: "Annotations & Metrics",
    items: [
      "Annotators cover resolution, topic, intent, pushback, error_recovery, hard_interruption, change_acceptance, and related review signals.",
      "Common metrics include turns, steps, tools, pushback_count, error_steps, introduced_findings_count, and overall_score.",
      "A stale annotation means the result came from an older annotator version. Re-run annotations or compute metrics to refresh the view.",
    ],
  },
] as const;

function HelpDialog({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", onKeyDown, { capture: true });
  }, [onClose]);

  return (
    <div className="help-overlay" role="presentation" onMouseDown={onClose}>
      <section
        className="help-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="help-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="help-head">
          <div>
            <h2 id="help-title">About traj-lens</h2>
            <p>A quick guide to capabilities, annotations, metrics, and scoring.</p>
          </div>
          <button className="help-close" type="button" onClick={onClose} aria-label="Close help">
            ×
          </button>
        </div>
        <div className="help-body">
          {HELP_SECTIONS.map((section) => (
            <section key={section.title} className="help-section">
              <h3>{section.title}</h3>
              <ul>
                {section.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </section>
    </div>
  );
}

export function HelpButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className="btn btn-sm help-trigger"
        type="button"
        onClick={() => setOpen(true)}
        title="Open help"
        aria-haspopup="dialog"
      >
        <span className="help-mark">?</span>
        <span>Help</span>
      </button>
      {open && <HelpDialog onClose={() => setOpen(false)} />}
    </>
  );
}
