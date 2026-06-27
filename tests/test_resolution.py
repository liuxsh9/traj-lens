"""Unit tests for the resolution LLM annotator parse path.

Regression guard for the production incident where a session whose assistant
clearly said "done" was labelled `indeterminate`: the LLM response was
unparseable, and parse() silently fabricated an `indeterminate` annotation.
It must now RAISE so runner.py records an error and writes no annotation
(the target stays a gap and a re-run retries it).
"""
import pytest

from trajlens.annotate.llm import UnparseableResponse, resolution


def test_parse_valid_label():
    assert resolution.parse('{"label": "resolved", "reason": "tests pass"}') == {
        "resolution": "resolved", "reason": "tests pass"}


def test_parse_unverified_label():
    # New state: complete solution delivered but never verified.
    out = resolution.parse('{"label": "unverified", "reason": "code never run"}')
    assert out["resolution"] == "unverified"


def test_parse_markdown_fenced():
    out = resolution.parse('```json\n{"label": "unresolved", "reason": "x"}\n```')
    assert out["resolution"] == "unresolved"


def test_parse_genuine_indeterminate_is_kept():
    # A real, parseable indeterminate verdict is a valid judgement — NOT an error.
    out = resolution.parse('{"label": "indeterminate", "reason": "cut short"}')
    assert out["resolution"] == "indeterminate"


def test_parse_unknown_label_falls_back_to_indeterminate():
    # Parseable JSON, unknown label → indeterminate (still a real annotation).
    assert resolution.parse('{"label": "mostly", "reason": "x"}')["resolution"] == "indeterminate"


def test_parse_unparseable_raises():
    # The incident case: no usable JSON → raise, do NOT fabricate indeterminate.
    with pytest.raises(UnparseableResponse):
        resolution.parse("Sure! The session looks resolved to me.")
