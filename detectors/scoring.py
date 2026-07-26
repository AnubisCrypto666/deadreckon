"""
Scoring: detector weight x blast radius (plan-pracy-undertow.md Sec.4/5).

Weights rank the three detectors by how confidently "silent failure" holds:
D2 is the most certain (the column is provably gone, serving reads nulls
today); D1 is a strong, well-understood signal (frozen source, still
training); D3 is real but the softest to call automatically (a metadata-
only agent can see the definition changed, not that it materially changed
the feature's distribution).

Blast radius counts deployments downstream of the model, weighting PROD
above STAGING above no deployment at all (a trained-but-undeployed model
is still worth flagging, just less urgently than one already serving
traffic).
"""

from __future__ import annotations

from dataclasses import dataclass

from detectors.models import Finding, ModelSnapshot

DETECTOR_WEIGHTS = {
    "D1": 0.8,
    "D2": 1.0,
    "D3": 0.6,
}

ENVIRONMENT_WEIGHTS = {
    "PROD": 3.0,
    "STAGING": 1.0,
}
UNDEPLOYED_BLAST_RADIUS = 0.5

SEVERITY_THRESHOLDS = (
    ("HIGH", 2.0),
    ("MEDIUM", 0.8),
)


@dataclass(frozen=True)
class ModelRiskScore:
    model_urn: str
    findings: tuple[Finding, ...]
    blast_radius: float
    score: float
    severity: str


def blast_radius(model: ModelSnapshot) -> float:
    if not model.deployment_environments:
        return UNDEPLOYED_BLAST_RADIUS
    return sum(ENVIRONMENT_WEIGHTS.get(env, 1.0) for env in model.deployment_environments)


def severity_for(score: float) -> str:
    for label, threshold in SEVERITY_THRESHOLDS:
        if score >= threshold:
            return label
    return "LOW"


def score_model(model: ModelSnapshot, findings: list[Finding]) -> ModelRiskScore | None:
    if not findings:
        return None
    radius = blast_radius(model)
    max_weight = max(DETECTOR_WEIGHTS[f.detector] for f in findings)
    score = round(max_weight * radius, 2)
    return ModelRiskScore(
        model_urn=model.urn,
        findings=tuple(findings),
        blast_radius=radius,
        score=score,
        severity=severity_for(score),
    )
