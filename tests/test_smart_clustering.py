import pytest
from app.engine.smart.clustering import run_clustering


@pytest.fixture
def sample_data():
    return {
        "Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0, "smm_total": 5.0, "mat_deaths": 1.0, "nd": 2.0, "sb": 1.0, "preterm": 10.0, "lbw": 8.0, "total_births": 200.0, "high_risk": 15.0, "adolescent": 3.0}},
        "Hospital B": {"hospital_id": 2, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 28.0, "smm_total": 4.5, "mat_deaths": 0.8, "nd": 1.8, "sb": 0.9, "preterm": 9.5, "lbw": 7.5, "total_births": 195.0, "high_risk": 14.0, "adolescent": 2.8}},
        "Hospital C": {"hospital_id": 3, "governorate": "North Gaza", "hospital_type": "general", "values": {"cs_rate": 32.0, "smm_total": 5.5, "mat_deaths": 1.2, "nd": 2.2, "sb": 1.1, "preterm": 10.5, "lbw": 8.5, "total_births": 205.0, "high_risk": 16.0, "adolescent": 3.2}},
        "Hospital D": {"hospital_id": 4, "governorate": "Khan Younis", "hospital_type": "specialist", "values": {"cs_rate": 15.0, "smm_total": 2.0, "mat_deaths": 0.0, "nd": 0.5, "sb": 0.2, "preterm": 5.0, "lbw": 4.0, "total_births": 120.0, "high_risk": 8.0, "adolescent": 1.0}},
        "Hospital E": {"hospital_id": 5, "governorate": "Rafah", "hospital_type": "general", "values": {"cs_rate": 18.0, "smm_total": 2.5, "mat_deaths": 0.1, "nd": 0.8, "sb": 0.3, "preterm": 5.5, "lbw": 4.5, "total_births": 130.0, "high_risk": 9.0, "adolescent": 1.2}},
    }


@pytest.fixture
def default_config():
    return {"dbscan_eps": 1.5, "dbscan_min_samples": 2}


def test_returns_clustering_result(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    assert result is not None
    assert result.n_clusters >= 1


def test_all_hospitals_assigned(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    assigned = [c.hospital_name for c in result.clusters]
    noise = result.noise_hospitals
    all_names = assigned + noise
    assert set(all_names) == set(sample_data.keys())


def test_pca_coordinates_present(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    for name in sample_data:
        assert name in result.pca_coordinates
        assert "x" in result.pca_coordinates[name]
        assert "y" in result.pca_coordinates[name]


def test_too_few_returns_none(default_config):
    data = {"Hospital A": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    result = run_clustering(data, default_config)
    assert result is None


def test_disabled_returns_none(default_config):
    result = run_clustering({}, default_config, enabled=False)
    assert result is None


def test_silhouette_score_valid(sample_data, default_config):
    result = run_clustering(sample_data, default_config)
    assert -1.0 <= result.silhouette_score <= 1.0


def test_cluster_profiles_generated(sample_data, default_config):
    """كل عنقود يحصل على ملف تعريف بمؤشرات مميزة وجملة عربية."""
    result = run_clustering(sample_data, default_config)
    assert result is not None
    assert len(result.profiles) >= 1
    for p in result.profiles:
        assert p.size >= 1
        assert len(p.hospitals) == p.size
        assert p.distinguishing_features
        assert p.summary_ar
        # المؤشرات المميزة مرتبة تنازلياً حسب |الانحراف|
        devs = [abs(d["deviation_pct"]) for d in p.distinguishing_features]
        assert devs == sorted(devs, reverse=True)


def test_clustering_profiles_consistent_with_clusters(sample_data, default_config):
    """أعضاء الملفات المميزة تطابق أعضاء clusters المخصصة."""
    result = run_clustering(sample_data, default_config)
    assigned = {}
    for c in result.clusters:
        assigned.setdefault(c.cluster_id, []).append(c.hospital_name)
    for p in result.profiles:
        assert set(p.hospitals) == set(assigned.get(p.cluster_id, []))


def test_clustering_serialization_includes_profiles(sample_data, default_config):
    """التسلسل للواجهة يحوّل profiles إلى قواميس JSON صافية."""
    from app.api.smart_analytics import _clustering_to_dict
    result = run_clustering(sample_data, default_config)
    serialized = _clustering_to_dict(result)
    assert isinstance(serialized, dict)
    assert "profiles" in serialized
    for p in serialized["profiles"]:
        assert isinstance(p, dict)
        assert "cluster_id" in p and "size" in p and "summary_ar" in p
        assert all(isinstance(d, dict) for d in p["distinguishing_features"])


@pytest.fixture
def client(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_realistic_hospital_data(db_session):
    """بذر 10 مستشفيات بقيم مؤشرات مشتقة تُنتج تجميعاً بملفات تعريف."""
    from app.models import Hospital, IndicatorValue, Indicator
    from app.cache import cache
    cache.invalidate("smart_overview_")  # تجنب كاش قديم من اختبارات أخرى
    code_to_id = {ind.code: ind.id for ind in db_session.query(Indicator).all()}
    hospitals = []
    for i in range(10):
        h = Hospital(name=f"Hospital {i}", is_active=True)
        db_session.add(h)
        hospitals.append(h)
    db_session.flush()
    for i, h in enumerate(hospitals):
        base = 20 + (i % 4) * 12
        vals = {"2": 200, "5": base / 100 * 200, "6": 190, "10": 2 + i,
                "11": 1, "17": 2, "7": 1, "6.f": 10 + i, "6.g": 8 + i,
                "2.n": 10, "2.c": 3, "2.d": 2}
        for code, val in vals.items():
            db_session.add(IndicatorValue(
                hospital_id=h.id, indicator_id=code_to_id[code], month="2026-06", value=val
            ))
    db_session.commit()


def test_overview_endpoint_returns_cluster_profiles_json(client, db_session):
    """انحدار numpy.int64: /smart/overview يُرجع ملفات التعريف كـ JSON سليم مع cluster_id صحيح النوع."""
    import json
    _seed_realistic_hospital_data(db_session)
    response = client.get("/smart/overview/2026-06")
    assert response.status_code == 200
    clustering = response.json()["data"]["clustering"]
    profiles = clustering["profiles"]
    assert isinstance(profiles, list) and len(profiles) >= 1
    for p in profiles:
        assert isinstance(p["cluster_id"], int) and not isinstance(p["cluster_id"], bool)
        assert p["size"] >= 1
        assert p["summary_ar"]
        assert all(isinstance(d["deviation_pct"], float) for d in p["distinguishing_features"])
    # تمر كامل جسم الاستجابة عبر jsonable_encoder/json بسلامة
    json.dumps(response.json(), ensure_ascii=False)


def test_comprehensive_report_endpoint_json_with_seeded_data(client, db_session):
    """انحدار تسريب numpy في _to_dict: التقرير الشامل مع بيانات حقيقية يُرجع JSON سليم."""
    import json
    from unittest.mock import patch
    _seed_realistic_hospital_data(db_session)
    with patch("app.engine.comparative.report_generator._call_api", return_value="تقرير تجريبي"):
        response = client.get("/comparative/comprehensive-report/2026-06")
    assert response.status_code == 200
    body = response.json()
    json.dumps(body, ensure_ascii=False)
    assert body["data"]["clustering"]["profiles"]
