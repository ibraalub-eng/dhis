"""Projection of a layered detection result onto the legacy AnomalyResult row.

There is ONE outlier engine: app.engine.anomaly.layered computes every layer
(raw, rate, historical, volume, peer), classifies the finding and returns the
numbers behind it. The ``anomaly_results`` table predates it and is still read
by the dashboard, the audit benchmark, root cause and the outlier drill-down,
so instead of running a second detector that could disagree (it computed the
same rates with a different peer group), its rows are DERIVED from the layered
result — a projection, exactly like a database view.

Nothing in this module computes a statistic. Every number it writes comes from
the LayerResult it is handed, which is why the Quality report, Outlier
Diagnostics, the audit screen and the Quality Score cannot disagree anymore.
"""
from typing import Any, Dict, Iterable, List, Mapping, Optional

from app.engine.anomaly.layered import LayerResult, is_detection_outlier
from app.engine.anomaly.zscore import AnomalyResultData

# Fields the legacy readers round to two decimals; keep that shape so stored
# rows look exactly like the ones the retired detector wrote.
def _r2(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):       # pragma: no cover - defensive
        return None


def _indicator_code(result: LayerResult, resolved: Any) -> str:
    """The code the legacy table keyed the row by: the registry definition's
    code when there is one, else the (first) numerator code, else the analysis
    code of the spec."""
    if resolved is not None and getattr(resolved, "code", None):
        return resolved.code
    spec = result.spec
    if spec.numerator_codes:
        return spec.numerator_codes[0]
    return spec.analysis_code


def project_rate_rows(
    results: Iterable[LayerResult],
    resolved_by_code: Optional[Mapping[str, Any]] = None,
    hospital_names: Optional[Mapping[Any, str]] = None,
) -> List[AnomalyResultData]:
    """Legacy rows for every derived rate the layered engine analysed.

    Only rate specs are projected: a data element has no ``AnomalyResult``
    consumer (the report reads its layered row directly), and inventing rate
    rows for counts would duplicate them on the outlier screen.

    ``resolved_by_code`` maps an analysis/rate code to an
    ``indicator_service.ResolvedIndicator`` so ``indicator_id`` (``derived:12``
    / ``rate:zscore:...``), ``formula`` and ``formula_version`` keep pointing at
    the live registry definition — the Quality report's stale-formula check
    depends on it. ``hospital_names`` names the peers in ``peers_detail``.
    """
    resolved_by_code = resolved_by_code or {}
    hospital_names = hospital_names or {}

    best: Dict[str, AnomalyResultData] = {}
    for result in results:
        spec = result.spec
        if not spec.is_rate:
            continue
        rate = result.rate.rate
        if rate is None:
            # Missing / zero denominator: there is no rate to compare, and a 0
            # would read as a real measurement. The layered row still exists.
            continue

        resolved = resolved_by_code.get(spec.analysis_code)
        peer = result.peer
        historical = result.historical
        benchmark = (peer.peer_mean if peer.peer_mean is not None
                     else historical.mean)
        z_score = peer.z if peer.z is not None else historical.z_score

        peers_detail = None
        if peer.peer_values:
            peers_detail = [
                {"hospital": hospital_names.get(hid, f"#{hid}"),
                 "rate": round(float(value), 4)}
                for hid, value in sorted(peer.peer_values.items(),
                                         key=lambda kv: kv[1])
            ]

        row = AnomalyResultData(
            indicator_code=_indicator_code(result, resolved),
            rate_name=spec.name,
            value=_r2(rate),
            benchmark=_r2(benchmark),
            z_score=_r2(z_score),
            is_outlier=is_detection_outlier(
                result.classification.outlier_level),
            peer_count=(peer.peer_count or None) if peer.peer_count else None,
            peer_std=_r2(peer.peer_std),
            peer_min=_r2(peer.peer_min),
            peer_max=_r2(peer.peer_max),
            peer_median=_r2(peer.peer_median),
            peers_detail=peers_detail,
            indicator_id=getattr(resolved, "indicator_id", None),
            formula=getattr(resolved, "formula", None),
            formula_version=getattr(resolved, "formula_version", None),
        )

        # One row per indicator code (the legacy table's key): several specs can
        # resolve to the same code (mortality against deliveries vs live
        # births). Keep the strongest signal — an outlier before a normal row,
        # then the larger |z| — instead of whichever came first.
        previous = best.get(row.indicator_code)
        if previous is None or _strength(row) > _strength(previous):
            best[row.indicator_code] = row

    return sorted(best.values(),
                  key=lambda r: (not r.is_outlier, -(abs(r.z_score or 0.0)),
                                 r.indicator_code))


def _strength(row: AnomalyResultData) -> tuple:
    return (1 if row.is_outlier else 0, abs(row.z_score or 0.0))
