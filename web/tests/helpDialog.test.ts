import assert from "node:assert/strict";
import { HELP_SECTIONS, SCORE_FORMULA_TEXT } from "../src/components/HelpDialog";

assert.equal(SCORE_FORMULA_TEXT, "resolved=100, partially_resolved=50, unresolved=0; each pushback subtracts 5 points, capped at half of the base score.");

assert.deepEqual(
  HELP_SECTIONS.map((section) => section.title),
  ["What It Is", "Key Capabilities", "Scoring", "Annotations & Metrics"],
);

assert.ok(
  HELP_SECTIONS.find((section) => section.title === "Key Capabilities")?.items.some((item) =>
    item.includes("multiple log formats")
  ),
);

assert.ok(
  HELP_SECTIONS.find((section) => section.title === "Scoring")?.items.some((item) =>
    item.includes("overall_score")
  ),
);
