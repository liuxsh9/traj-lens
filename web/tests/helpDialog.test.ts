import assert from "node:assert/strict";
import { HELP_SECTIONS, SCORE_FORMULA_TEXT } from "../src/components/HelpDialog";

assert.equal(SCORE_FORMULA_TEXT, "resolved=100，partially_resolved=50，unresolved=0；每次 pushback 扣 5 分，最多扣基础分的一半。");

assert.deepEqual(
  HELP_SECTIONS.map((section) => section.title),
  ["系统定位", "关键能力", "分数计算", "标注与指标"],
);

assert.ok(
  HELP_SECTIONS.find((section) => section.title === "关键能力")?.items.some((item) =>
    item.includes("多来源日志")
  ),
);

assert.ok(
  HELP_SECTIONS.find((section) => section.title === "分数计算")?.items.some((item) =>
    item.includes("overall_score")
  ),
);
