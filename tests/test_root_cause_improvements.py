"""اختبارات تحسينات Root Cause: إصلاح نافذة الشهور، مقارنة النظير لكل مؤشر، تفعيل الواجهة."""
import os

from app.engine.root_cause import _month_offset, get_historical_data


# --- Fix 1: month cutoff is relative to the report month, not today ---

def test_month_offset_relative_to_report_month():
    assert _month_offset("2026-06", 6) == "2026-01"
    assert _month_offset("2026-01", 6) == "2025-08"
    assert _month_offset("2026-03", 3) == "2026-01"
    assert _month_offset("2026-06", 1) == "2026-06"


def test_get_historical_data_uses_report_month_window(db_session):
    """نافذة الأشهر تُحسب من شهر التقرير — تعمل مع بيانات تاريخية لا علاقة لها بتاريخ اليوم."""
    from app.models import Hospital, Indicator, IndicatorValue

    h = Hospital(name="Hist Hosp", is_active=True)
    db_session.add(h)
    db_session.flush()
    ind = db_session.query(Indicator).filter(Indicator.code == "2").first()
    for m, v in [("2026-01", 100), ("2026-02", 110), ("2026-03", 120),
                 ("2026-04", 130), ("2026-05", 140), ("2026-06", 150)]:
        db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=ind.id, month=m, value=v))
    db_session.commit()

    # قبل الإصلاح كانت النافذة تُحسب من تاريخ اليوم (2026-08) فلا تعود بأي شيء
    history = get_historical_data(db_session, h.id, "2", months_back=3, month="2026-06")
    assert len(history) == 3
    assert history[0].month == "2026-04"
    assert history[-1].month == "2026-06"


# --- Fix 3: per-indicator peer comparison ---

def test_peer_comparisons_are_per_indicator(db_session):
    from app.models import Hospital, HospitalType, Indicator, IndicatorValue
    from app.engine.root_cause import generate_root_cause_analysis, PeerIndicatorComparison

    htype = HospitalType(name="Gov")
    db_session.add(htype)
    db_session.flush()
    target = Hospital(name="Target", hospital_type_id=htype.id, is_active=True)
    peers = [Hospital(name=f"Peer{i}", hospital_type_id=htype.id, is_active=True) for i in range(4)]
    db_session.add_all([target] + peers)
    db_session.flush()

    code_to_id = {i.code: i.id for i in db_session.query(Indicator).all()}
    for h in [target] + peers:
        high = h is target
        vals = {"2": 200, "5": 80 if high else 40, "6": 190, "10": 5 if high else 2}
        for code, v in vals.items():
            db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=code_to_id[code], month="2026-06", value=v))
    db_session.commit()

    report = generate_root_cause_analysis(
        db_session, target.id, "2026-06",
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        include_history=False, compare_peers=True,
    )
    comps = report.peer_comparisons
    assert len(comps) >= 2
    for code, comp in comps.items():
        assert isinstance(comp, PeerIndicatorComparison)
        assert comp.hospital_value > 0
        assert comp.peer_mean > 0
        assert comp.peer_count >= 4
    # القيصرية أعلى بوضوح عند الهدف مقابل النظير
    cs = comps.get("cs_rate")
    assert cs is not None
    assert cs.hospital_value > cs.peer_mean
    assert cs.gap_pct > 0


# --- Fix 2: frontend enables history + peers and renders advanced sections ---

def test_frontend_enables_history_and_peers():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "settings.js")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "include_history=true" in content
    assert "compare_peers=true" in content
    assert "months_back=6" in content


def test_frontend_renders_advanced_sections():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "settings.js")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "rcSummaryArabic" in content
    assert "rcCausalChains" in content
    assert "rcCausalTree" in content
    assert "rcPeerComparisons" in content
    assert "causal_chains" in content
    assert "peer_comparisons" in content
    assert "summary_arabic" in content

    html_path = os.path.join(os.path.dirname(__file__), "..", "static", "tabs", "root-cause.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    assert 'id="rcSummaryArabic"' in html
    assert 'id="rcCausalChains"' in html
    assert 'id="rcCausalTree"' in html
    assert 'id="rcPeerComparisons"' in html


def test_frontend_renders_history_sparklines():
    """الاتجاهات (trends): الشجرة السببية تعرض sparkline لكل عامل عبر الأشهر."""
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "settings.js")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "_rcSparkline" in content
    assert "n.history" in content
    assert "polyline" in content


# --- Fix 5: deep transitive causal chains (parent <- children) ---

def test_extract_rule_structure(db_session):
    from app.engine.root_cause import _extract_rule_structure
    structure = _extract_rule_structure(db_session)
    # R001: إجمالي الولادات (2) >= مجموع [3,4,5]
    assert structure["R001"]["total"] == "2"
    assert "5" in structure["R001"]["parts"]
    # R006: القيصرية (5) = طارئة + مجدولة
    assert structure["R006"]["total"] == "5"
    # R008: شكل {child, parent} — الجزء 5.b.1 ضمن القيصرية
    assert structure["R008"]["total"] == "5"
    assert structure["R008"]["parts"] == ["5.b.1"]


def test_link_rule_causes_parent_child(db_session):
    from app.models import Hospital, ValidationResult
    from app.engine.root_cause import (
        analyze_rule_failures, _extract_rule_structure, _link_rule_causes,
    )

    h = db_session.query(Hospital).first()
    # R001 (الأب: 2 >= 3+4+5) + R006 (الابن: 5 = طارئة+مجدولة) يفشلان معاً
    for code, sev in [("R001", "HIGH"), ("R006", "HIGH")]:
        db_session.add(ValidationResult(
            hospital_id=h.id, month="2026-06", rule_code=code,
            rule_description=code, status="FAIL", severity=sev,
        ))
    db_session.commit()

    failures = analyze_rule_failures(db_session, h.id, "2026-06")
    causes = _link_rule_causes(failures, _extract_rule_structure(db_session))
    # R006 سبب مباشر لـ R001 لأن مؤشره (5) ضمن أبناء R001
    assert "R006" in causes.get("R001", [])


def test_transitive_chain_deepest_cause_to_symptom(db_session):
    from app.models import Hospital, ValidationResult
    from app.engine.root_cause import (
        analyze_rule_failures, build_transitive_causal_chains, CausalChain,
    )

    h = db_session.query(Hospital).first()
    # سلسلة من ثلاثة مستويات: R008 (5.b.1) -> R006 (5) -> R001 (2)
    for code, sev in [("R001", "HIGH"), ("R006", "HIGH"), ("R008", "HIGH")]:
        db_session.add(ValidationResult(
            hospital_id=h.id, month="2026-06", rule_code=code,
            rule_description=code, status="FAIL", severity=sev,
        ))
    db_session.commit()

    failures = analyze_rule_failures(db_session, h.id, "2026-06")
    chains = build_transitive_causal_chains(db_session, failures)
    assert len(chains) >= 1
    chain = chains[0]
    assert isinstance(chain, CausalChain)
    assert len(chain.chain_path) >= 2
    # أعمق سبب (R008/R006) قبل العرض (R001)
    assert chain.chain_path[0] == "R001"
    assert "R006" in chain.chain_path
    assert chain.chain_path_arabic
    assert len(chain.evidence) == len(chain.chain_path)
    assert chain.confidence > 0


def test_transitive_chains_in_report(db_session):
    from app.models import Hospital, ValidationResult
    from app.engine.root_cause import generate_root_cause_analysis

    h = db_session.query(Hospital).first()
    for code, sev in [("R001", "HIGH"), ("R006", "HIGH")]:
        db_session.add(ValidationResult(
            hospital_id=h.id, month="2026-06", rule_code=code,
            rule_description=code, status="FAIL", severity=sev,
        ))
    db_session.commit()

    report = generate_root_cause_analysis(
        db_session, h.id, "2026-06",
        quality_data={"score": 60, "rule_compliance": 50, "completeness": 70,
                      "consistency": 60, "outlier_penalty": 0.0},
        confidence_data={"overall_confidence": 60},
    )
    chains = [c for c in report.causal_chains if c.chain_path]
    assert len(chains) >= 1
    assert any(len(c.chain_path) >= 2 for c in chains)


def test_api_returns_chain_path(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.models import Hospital, ValidationResult

    h = db_session.query(Hospital).first()
    for code, sev in [("R001", "HIGH"), ("R006", "HIGH")]:
        db_session.add(ValidationResult(
            hospital_id=h.id, month="2026-06", rule_code=code,
            rule_description=code, status="FAIL", severity=sev,
        ))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get(f"/root-cause/{h.id}?month=2026-06&include_history=true")
        assert resp.status_code == 200
        data = resp.json()
        assert "causal_chains" in data
        with_path = [c for c in data["causal_chains"] if c.get("chain_path")]
        assert len(with_path) >= 1
        assert any(len(c["chain_path"]) >= 2 for c in with_path)
    finally:
        app.dependency_overrides.clear()


def test_frontend_renders_chain_path():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "settings.js")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "chain_path" in content
    assert "chain_path_arabic" in content
    assert "سلسلة السبب والنتيجة" in content


def test_api_returns_primary_cause_ar(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.models import Hospital, ValidationResult

    h = Hospital(name="ARHosp", is_active=True)
    db_session.add(h)
    db_session.flush()
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-06", rule_code="R041",
        rule_description="C-section rate", status="FAIL",
        severity="HIGH", rule_type="BENCHMARK",
    ))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get(f"/root-cause/{h.id}?month=2026-06")
        assert resp.status_code == 200
        data = resp.json()
        failures = data["top_rule_failures"]
        assert len(failures) >= 1
        assert "primary_cause_ar" in failures[0]
    finally:
        app.dependency_overrides.clear()


# --- Fix 4: quantified priorities (impact/effort/roi) ---

def test_priority_actions_have_quantified_metrics(db_session):
    from app.models import Hospital, ValidationResult
    from app.engine.root_cause import generate_root_cause_analysis, PriorityActionDetail

    h = Hospital(name="QHosp", is_active=True)
    db_session.add(h)
    db_session.flush()
    # قاعدة حرجة تفشل 100%
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-06", rule_code="R054",
        rule_description="Maternal deaths surge", status="FAIL",
        severity="CRITICAL", rule_type="THRESHOLD",
    ))
    db_session.commit()

    report = generate_root_cause_analysis(
        db_session, h.id, "2026-06",
        quality_data={"score": 50, "rule_compliance": 40, "completeness": 60,
                      "consistency": 50, "outlier_penalty": 0.1},
        confidence_data={"overall_confidence": 50},
    )
    details = report.priority_action_details
    assert len(details) >= 1
    for p in details:
        assert isinstance(p, PriorityActionDetail)
        assert 0 <= p.impact <= 100
        assert 1 <= p.effort <= 5
        assert p.roi > 0
    # القاعدة الحرجية 100% فشل → أثر مرتفع
    rule = [p for p in details if p.source == "rule"]
    if rule:
        assert rule[0].impact >= 60


def test_effort_varies_by_rule_type():
    from app.engine.root_cause import _estimate_action_metrics
    logic = _estimate_action_metrics(severity="HIGH", failure_rate=50, rule_type="LOGIC")
    bench = _estimate_action_metrics(severity="HIGH", failure_rate=50, rule_type="BENCHMARK")
    assert logic["effort"] == 2
    assert bench["effort"] == 4
    assert logic["roi"] > bench["roi"]  # نفس الأثر بجهد أقل = عائد أعلى


def test_impact_scales_with_failure_rate_and_severity():
    from app.engine.root_cause import _estimate_action_metrics
    low = _estimate_action_metrics(severity="LOW", failure_rate=20)
    high = _estimate_action_metrics(severity="CRITICAL", failure_rate=80)
    assert low["impact"] < high["impact"]
    assert high["impact"] == 80.0


def test_impact_fallback_branches():
    """فروع الثقة والشذوذ في التقدير الكمي تُختبر مباشرة."""
    from app.engine.root_cause import _estimate_action_metrics
    # فجوة ثقة: confidence=50 → أثر (100-50)*0.9 = 45
    conf = _estimate_action_metrics(severity="LOW", confidence=50)
    assert conf["impact"] == 45.0
    # شذوذ: z=2 → أثر 2*25 = 50
    anom = _estimate_action_metrics(severity="HIGH", z_score=2.0)
    assert anom["impact"] == 50.0


def test_impact_zero_when_no_signal():
    """عند غياب كل الإشارات يكون الأثر والعائد صفراً دون انهيار."""
    from app.engine.root_cause import _estimate_action_metrics
    m = _estimate_action_metrics()
    assert m["impact"] == 0.0
    assert m["roi"] == 0.0
    assert 1 <= m["effort"] <= 5


def test_api_returns_priority_action_details(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db
    from app.models import Hospital, ValidationResult

    h = Hospital(name="ApiQHosp", is_active=True)
    db_session.add(h)
    db_session.flush()
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-06", rule_code="R054",
        rule_description="Maternal deaths surge", status="FAIL",
        severity="CRITICAL", rule_type="THRESHOLD",
    ))
    db_session.commit()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get(f"/root-cause/{h.id}?month=2026-06")
        assert resp.status_code == 200
        data = resp.json()
        assert "priority_action_details" in data
        details = data["priority_action_details"]
        assert len(details) == len(data["priority_actions"])
        for p in details:
            assert "impact" in p and "effort" in p and "roi" in p
            assert isinstance(p["impact"], (int, float))
    finally:
        app.dependency_overrides.clear()


def test_frontend_renders_impact_effort_roi():
    path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "settings.js")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "priority_action_details" in content
    assert "det.impact" in content
    assert "det.effort" in content
    assert "det.roi" in content
    assert "الأثر" in content
    assert "عائد" in content


def test_causal_tree_serializes_history(db_session):
    """API يعرض history لكل عقدة في الشجرة السببية حتى يرسمها المتصفح."""
    from app.models import Hospital, HospitalType, Indicator, IndicatorValue
    from app.engine.root_cause import generate_root_cause_analysis, MonthDataPoint

    htype = HospitalType(name="Gov2")
    db_session.add(htype)
    db_session.flush()
    target = Hospital(name="HistTarget", hospital_type_id=htype.id, is_active=True)
    peers = [Hospital(name=f"HP{i}", hospital_type_id=htype.id, is_active=True) for i in range(3)]
    db_session.add_all([target] + peers)
    db_session.flush()

    code_to_id = {i.code: i.id for i in db_session.query(Indicator).all()}
    for h in [target] + peers:
        for code, v in {"2": 200, "5": 40, "6": 190, "10": 2}.items():
            for m in ["2026-04", "2026-05", "2026-06"]:
                db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=code_to_id[code], month=m, value=v))
    # قاعدة تفشل بنسب متصاعدة عبر الأشهر حتى يحصل عقد القاعدة على تاريخ حقيقي
    from app.models import ValidationResult
    for i, m in enumerate(["2026-04", "2026-05", "2026-06"]):
        db_session.add(ValidationResult(
            hospital_id=target.id, month=m, rule_code="R041",
            rule_description="C-section rate exceeds threshold", status="FAIL", severity="HIGH",
        ))
        db_session.add(ValidationResult(
            hospital_id=target.id, month=m, rule_code="R041",
            rule_description="C-section rate exceeds threshold", status="PASS", severity="HIGH",
        ))
    db_session.commit()

    report = generate_root_cause_analysis(
        db_session, target.id, "2026-06",
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        include_history=True, compare_peers=True, months_back=3,
    )
    assert report.historical_trends
    nodes_with_history = [n for n in report.causal_tree if n.history]
    assert nodes_with_history
    for n in nodes_with_history:
        for p in n.history:
            assert isinstance(p, MonthDataPoint)
            assert p.month >= "2026-04"
            assert p.month <= "2026-06"


def test_analyze_rule_failures_populates_arabic_cause(db_session):
    from app.models import Hospital, ValidationResult
    from app.engine.root_cause import analyze_rule_failures

    h = Hospital(name="ArCauseHosp", is_active=True)
    db_session.add(h)
    db_session.flush()
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-06", rule_code="R041",
        rule_description="C-section rate", status="FAIL",
        severity="HIGH", rule_type="BENCHMARK",
    ))
    db_session.commit()

    patterns = analyze_rule_failures(db_session, h.id, "2026-06")
    assert len(patterns) >= 1
    assert patterns[0].primary_cause_ar


def test_analyze_rule_failures_dynamic_structure(db_session):
    """قاعدة مع params ينتج سبباً عربياً/إنجليزياً محدداً من المستوى الثاني."""
    from app.models import Hospital, ValidationResult, Rule
    from app.engine.root_cause import analyze_rule_failures

    h = Hospital(name="DynHosp", is_active=True)
    db_session.add(h)
    db_session.flush()
    rule = Rule(code="RDYN1", name="Dyn", rule_type="LOGIC", severity="HIGH",
                category="BASIC_LOGIC", expression_type="ge",
                params='{"parent": "2", "children": ["3", "4", "5"]}',
                description="Dyn rule")
    db_session.add(rule)
    db_session.add(ValidationResult(
        hospital_id=h.id, month="2026-06", rule_code="RDYN1",
        rule_description="Dyn rule", status="FAIL", severity="HIGH", rule_type="LOGIC",
    ))
    db_session.commit()

    patterns = analyze_rule_failures(db_session, h.id, "2026-06")
    assert any(p.rule_code == "RDYN1" for p in patterns)
    dyn = [p for p in patterns if p.rule_code == "RDYN1"][0]
    assert dyn.primary_cause
    assert dyn.primary_cause_ar


def test_peer_comparison_includes_governorates(db_session):
    from app.models import Hospital, HospitalType, Governorate, Indicator, IndicatorValue
    from app.engine.root_cause import generate_root_cause_analysis

    gov = Governorate(name="North")
    htype = HospitalType(name="Gov")
    db_session.add_all([gov, htype])
    db_session.flush()
    target = Hospital(name="Target2", hospital_type_id=htype.id,
                      governorate_id=gov.id, is_active=True)
    peers = [
        Hospital(name=f"P2{i}", hospital_type_id=htype.id,
                 governorate_id=gov.id, is_active=True)
        for i in range(4)
    ]
    db_session.add_all([target] + peers)
    db_session.flush()

    code_to_id = {i.code: i.id for i in db_session.query(Indicator).all()}
    for h in [target] + peers:
        high = h is target
        vals = {"2": 200, "5": 80 if high else 40, "6": 190}
        for code, v in vals.items():
            db_session.add(IndicatorValue(hospital_id=h.id, indicator_id=code_to_id[code], month="2026-06", value=v))
    db_session.commit()

    report = generate_root_cause_analysis(
        db_session, target.id, "2026-06",
        quality_data={"score": 80}, confidence_data={"overall_confidence": 80},
        include_history=False, compare_peers=True,
    )
    comps = report.peer_comparisons
    assert comps
    for comp in comps.values():
        assert comp.peer_governorates
        assert comp.peer_types
        assert comp.peer_governorate_counts.get("North", 0) == 4
