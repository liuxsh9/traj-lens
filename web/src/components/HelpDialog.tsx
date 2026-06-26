import { useEffect, useState } from "react";

export const SCORE_FORMULA_TEXT = "resolved=100，partially_resolved=50，unresolved=0；每次 pushback 扣 5 分，最多扣基础分的一半。";

export const HELP_SECTIONS = [
  {
    title: "系统定位",
    items: [
      "traj-lens 用来分析 coding-agent 的完整工作轨迹：从原始日志导入，到统一建模、标注、指标计算、审阅和训练数据导出。",
      "系统保留两层真相：raw bytes 是可追溯的导出真相，canonical Items 是分析真相。",
    ],
  },
  {
    title: "关键能力",
    items: [
      "导入多来源日志，适配 OpenAI messages、Codex、swe_chat 等格式，并归一化为统一轨迹模型。",
      "按数据集管理样本，支持筛选、排序、批量标注、指标刷新、安全扫描和导出。",
      "轨迹详情页提供 turn/step 分组、工具调用、代码变更、错误恢复、pushback 和最终回复的上下文视图。",
    ],
  },
  {
    title: "分数计算",
    items: [
      `overall_score 由 resolution 基础分减去 pushback 惩罚得到：${SCORE_FORMULA_TEXT}`,
      "resolved 表示任务完成，partially_resolved 表示部分完成，unresolved 表示未解决。",
      "pushback 反映用户中途纠偏或反对的次数，首个用户需求不计入 pushback。",
    ],
  },
  {
    title: "标注与指标",
    items: [
      "标注器覆盖 resolution、topic、intent、pushback、error_recovery、hard_interruption、change_acceptance 等维度。",
      "常用指标包括 turns、steps、tools、pushback_count、error_steps、introduced_findings_count 和 overall_score。",
      "陈旧标注表示当前结果来自旧版本标注器，可以重跑标注或重新计算指标来刷新视图。",
    ],
  },
] as const;

export const HELP_BUTTON_CLASS = "btn btn-sm btn-ghost";

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
            <h2 id="help-title">理解 traj-lens</h2>
            <p>系统能力、标注含义和评分逻辑速览</p>
          </div>
          <button className="help-close" type="button" onClick={onClose} aria-label="关闭帮助">
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
        className={HELP_BUTTON_CLASS}
        type="button"
        onClick={() => setOpen(true)}
        title="Open help"
        aria-haspopup="dialog"
      >
        Help
      </button>
      {open && <HelpDialog onClose={() => setOpen(false)} />}
    </>
  );
}
