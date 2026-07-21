import pytest
import numpy as np
from app.engine.smart.stratified import run_stratified_analysis


@pytest.fixture
def sample_data():
    np.random.seed(42)
    data = {}
    for i in range(8):
        gov = ["Gaza", "Gaza", "Gaza", "Gaza", "North Gaza", "North Gaza", "Khan Younis", "Khan Younis"][i]
        typ = ["general", "general", "general", "general", "general", "general", "specialist", "specialist"][i]
        data[f"Hospital {i}"] = {
            "hospital_id": i,
            "governorate": gov,
            "hospital_type": typ,
            "values": {
                "cs_rate": 25.0 + i * 2 + np.random.normal(0, 1),
                "smm_total": 5.0 + np.random.normal(0, 0.5),
                "mat_deaths": 1.0 + np.random.normal(0, 0.2),
                "nd": 2.0 + np.random.normal(0, 0.3),
                "sb": 1.0 + np.random.normal(0, 0.1),
                "preterm": 10.0 + np.random.normal(0, 1),
                "lbw": 8.0 + np.random.normal(0, 0.5),
                "total_births": 200.0 + np.random.normal(0, 10),
                "high_risk": 15.0 + np.random.normal(0, 2),
                "adolescent": 3.0 + np.random.normal(0, 0.5),
            },
        }
    return data


def test_returns_list_of_comparisons(sample_data):
    results = run_stratified_analysis(sample_data, {})
    assert isinstance(results, list)
    assert len(results) > 0


def test_peer_group_size(sample_data):
    results = run_stratified_analysis(sample_data, {})
    for r in results:
        assert r.peer_group_size >= 1


def test_rank_within_peer_group(sample_data):
    results = run_stratified_analysis(sample_data, {})
    for r in results:
        assert 1 <= r.rank_in_peer_group <= r.peer_group_size


def test_label_valid(sample_data):
    results = run_stratified_analysis(sample_data, {})
    valid_labels = {"above_average", "average", "below_average", "significantly_above", "significantly_below"}
    for r in results:
        assert r.label in valid_labels


def test_too_few_hospitals():
    data = {"H1": {"hospital_id": 1, "governorate": "Gaza", "hospital_type": "general", "values": {"cs_rate": 30.0}}}
    results = run_stratified_analysis(data, {})
    assert results == []
