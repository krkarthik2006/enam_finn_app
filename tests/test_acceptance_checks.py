"""Ensure the live-test numeric oracle rejects bad answers and accepts valid citations."""

import pytest
from test_live_workflow import assert_margin_answer, supported_percent


def answer(text, citations=None):
    return {
        "status": "analysed",
        "findings": [{"text": text, "citation_ids": citations or ["q2"]}],
        "sources": [
            {"citation_id": "q1", "title": "Q1 transcript", "kind": "transcript", "mode": "demo",
             "text": "Q1 guidance for Q2 EBITDA margin was 22%."},
            {"citation_id": "q2", "title": "Q2 transcript", "kind": "transcript", "mode": "demo",
             "text": "Q2 actual margin was 20% versus Q1 guidance of 22%."},
        ],
    }


@pytest.mark.parametrize("text", [
    "Q2 actual was 20% versus guidance of 22%, a miss of 2 percentage points.",
    "Guidance was 22 percent and actual was 20 percent, below by two percentage points.",
    "Guidance was 22% and actual was 20%, a shortfall of 200 basis points.",
])
def test_margin_oracle_accepts_supported_wording_and_restatement(text):
    assert_margin_answer(answer(text), 22, 20)


@pytest.mark.parametrize("text,citations", [
    ("Guidance 99%, actual 20%, miss of 2 percentage points.", ["q2"]),
    ("Guidance 22%, actual 19%, miss of 2 percentage points.", ["q2"]),
    ("Guidance 22%, actual 20%, miss of 5 percentage points.", ["q2"]),
    ("Guidance 22%, actual 20%, beat of 2 percentage points.", ["q2"]),
    ("Guidance 22%, actual 20%, miss of 2%.", ["q2"]),
    ("Guidance 22%, actual 20%, miss of 2 percentage points.", ["invented"]),
    ("Guidance 22%, actual 20%, miss of 2 percentage points.", ["q1"]),
])
def test_margin_oracle_rejects_wrong_facts_units_direction_or_sources(text, citations):
    with pytest.raises(AssertionError):
        assert_margin_answer(answer(text, citations), 22, 20)


def test_missing_evidence_oracle_allows_only_correct_explicitly_derived_margin():
    cited = "FY2025 revenue was INR 4,000 crore and EBITDA was INR 800 crore."
    assert supported_percent("FY2025 margin was 20% implied", cited, "20")
    assert supported_percent("FY2025 figures implying ~20% EBITDA margin", cited, "20")
    assert not supported_percent("FY2025 margin was 21% implied", cited, "21")
    assert not supported_percent("Q3 forecast was 20%", cited, "20")
