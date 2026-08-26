from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class HospitalCluster:
    hospital_name: str
    cluster_id: int
    distance_to_centroid: float


@dataclass
class ClusteringResult:
    clusters: List[HospitalCluster]
    k: int
    silhouette_score: Optional[float]
    centroids: List[Dict[str, float]]
    features_used: List[str]
    pca_coordinates: Dict[str, Dict[str, float]] = field(default_factory=dict)
    pca_explained_variance: List[float] = field(default_factory=list)


@dataclass
class MLAnomalyResult:
    hospital_name: str
    anomaly_score: float
    is_outlier: bool
    method: str
    contributing_features: List[str] = field(default_factory=list)


@dataclass
class PCAResult:
    explained_variance: List[float]
    cumulative_variance: List[float]
    loadings: Dict[int, Dict[str, float]]
    top_features: Dict[int, List[str]]
    n_components: int
