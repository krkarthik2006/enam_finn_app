from engine.guidance import compare_guidance, next_period, quarter_label, rule_claims


def source(quarter, actual, guided):
    return {"citation_id": quarter, "kind": "transcript", "title": f"FY2027 Q{quarter} transcript",
            "text": f"Consolidated results. EBITDA margin delivered was {actual}%. "
                    f"Management explicitly guided for EBITDA margin of {guided}% in the following quarter."}


def test_quarter_labels_and_rollover_are_not_calendar_guesses():
    assert quarter_label("Q2 FY27") == "FY2027 Q2"
    assert quarter_label("FY2026 Q4") == "FY2026 Q4"
    assert next_period("FY2026 Q4") == "FY2027 Q1"
    assert next_period("2026-12-31") == "2027-03-31"


def test_guidance_compares_following_quarter_in_percentage_points():
    claims = rule_claims(source(1, 20, 22)) + rule_claims(source(2, 20, 23))
    result = compare_guidance(claims)
    assert result[0]["period"] == "FY2027 Q2" and result[0]["status"] == "missed"
    assert result[0]["delta"] == -2
    assert result[0]["citation_ids"] == [1, 2]
    assert result[0]["difference_unit"] == "percentage_points"
    assert result[1]["status"] == "missing_actual"


def test_ranges_conflicts_and_unknown_scope_do_not_fake_precision():
    base = {"kind": "guidance", "period": "FY2027 Q2", "metric": "ebitda_margin", "low": 20,
            "high": 22, "unit": "percent", "basis": "consolidated", "citation_ids": ["guide"]}
    actual = {**base, "kind": "actual", "low": 21, "high": 21, "citation_ids": ["actual"]}
    assert compare_guidance([base, actual])[0]["status"] == "met"
    conflict = {**actual, "low": 19, "high": 19}
    assert compare_guidance([base, actual, conflict])[0]["status"] == "conflicting_actuals"
    assert compare_guidance([{**base, "basis": "not_stated"}])[0]["status"] == "basis_not_stated"
    assert compare_guidance([base, {**actual, "basis": "standalone"}])[0]["actual"] is None
