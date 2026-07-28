"""
Scoring: detector weight x blast radius (plan-pracy-undertow.md Sec.4/5).

Weights rank the three detectors by how confidently "silent failure" holds:
D2 is the most certain (the column is provably gone, serving reads nulls
today); D1 is a strong, well-understood signal (frozen source, still
training); D3 is real but the softest to call automatically (a metadata-
only agent can see the definition changed, not that it materially changed
the feature's distribution).

Blast radius is the *worst* environment the model is currently served
from, not a count of environments. These weights are deliberate tiers,
not measured quantities - PROD is not literally "three times worse" than
STAGING, the number just has to keep every PROD finding above every
STAGING finding (see the band invariant below, enforced by a test).

Design invariant, load-bearing for both of the above: environment picks
the band, detector confidence orders findings *within* a band. No
detector weight can move a model across an environment boundary. That is
intentional - a maybe-broken model serving production traffic outranks a
definitely-broken model serving nobody, because the first one costs money
in expectation today and the second costs nothing until it's promoted.
"""

from __future__ import annotations

from dataclasses import dataclass

from detectors.models import DetectorResult, Finding, MissingSignal, ModelSnapshot

DETECTOR_WEIGHTS = {
    "D1": 0.8,
    "D2": 1.0,
    "D3": 0.6,
}

ENVIRONMENT_WEIGHTS = {
    "PROD": 3.0,
    "STAGING": 1.0,
}

# An undeployed model has a blast radius of *zero* - nothing is serving,
# so nothing is being harmed today. This is not a measured radius; it's a
# floor that keeps latent risk (the problem ships with the model when it
# is eventually promoted) ranked below anything actually in front of
# traffic, while still leaving it scoreable. Named for what it is rather
# than pretending to be "half a STAGING deployment".
LATENT_RISK_FLOOR = 0.5

# MEDIUM sits at 0.7, in the empty gap between D3-on-STAGING (0.6) and
# D1-on-STAGING (0.8), rather than exactly on 0.8 as it originally did.
# The score space is discrete - 9 reachable values, not a continuum - so a
# threshold that lands *on* a reachable value is balanced on a knife edge:
# nudging D1's weight from 0.8 to 0.79 would have silently dropped every
# "frozen source in STAGING" model out of the tagged set. Classification is
# identical for every reachable score either way; 0.7 just isn't fragile.
# HIGH at 2.0 was already well placed, in the 1.8 -> 2.4 gap.
SEVERITY_THRESHOLDS = (
    ("HIGH", 2.0),
    ("MEDIUM", 0.7),
)

# The real, reachable ceiling: strongest detector x worst environment.
# Computed rather than hardcoded so it cannot go stale if the weights
# change. This used to multiply by the *sum* of environment weights, which
# advertised a 4.0 nobody could reach - see blast_radius() for why summing
# environments was wrong in the first place.
MAX_POSSIBLE_SCORE = round(max(DETECTOR_WEIGHTS.values()) * max(ENVIRONMENT_WEIGHTS.values()), 2)

# Which severities are worth the `undertow:at-risk` tag - i.e. worth a
# visual flag an owner has to act on, not just a recorded score. LOW is
# everything below the MEDIUM threshold: either an undeployed model at any
# detector weight (max 1.0 x 0.5 = 0.5 - nothing is serving yet, so there's
# no live blast radius to page anyone about), or a model deployed only to
# STAGING with nothing but a D3 (softest, semantic-only) finding
# (0.6 x 1.0 = 0.6). Both are real findings worth recording (the document
# and structured properties are written regardless), just not worth the
# same visual alarm as a PROD model or a harder D1/D2 signal.
TAGGABLE_SEVERITIES = frozenset({"MEDIUM", "HIGH"})


def is_at_risk(severity: str) -> bool:
    return severity in TAGGABLE_SEVERITIES


@dataclass(frozen=True)
class AssessmentCoverage:
    """How much of the model we could actually assess, tracked separately
    from risk on purpose: "risky" and "unknown" must not collapse into one
    scalar, or both stop meaning anything. INSUFFICIENT_DATA never moves
    riskScore - it shows up here instead."""

    conclusive: int
    total: int
    missing: tuple[MissingSignal, ...] = ()

    @property
    def is_fully_covered(self) -> bool:
        return self.conclusive == self.total

    @property
    def is_unassessable(self) -> bool:
        """No detector reached a verdict at all - the model is opaque to
        us, which is itself worth flagging (it means the metadata needed
        to govern it isn't there)."""
        return self.conclusive == 0

    def __str__(self) -> str:
        return f"{self.conclusive}/{self.total}"


@dataclass(frozen=True)
class ModelRiskScore:
    model_urn: str
    findings: tuple[Finding, ...]
    blast_radius: float
    score: float
    severity: str
    coverage: AssessmentCoverage

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def sort_key(self) -> tuple[float, int]:
        """Ranking key for the risk table. score alone leaves ties - two
        PROD models both flagged by D2 both land on 3.0 regardless of
        whether one has a single finding and the other four. Rather than
        inflating the scalar (which would push the ceiling above the
        genuinely reachable MAX_POSSIBLE_SCORE and reintroduce a range
        nobody can occupy), multiplicity breaks ties here, where it costs
        the score's meaning nothing. Descending on both."""
        return (-self.score, -self.finding_count)


def blast_radius(model: ModelSnapshot) -> float:
    """Worst environment the model is served from - a max, not a sum.

    A model already in PROD is not made meaningfully riskier by also
    sitting in STAGING; the production exposure dominates entirely, and
    summing would claim staging adds a third again as much harm on top.
    (Summing would be right if these values were deployment *instances* -
    PROD-EU plus PROD-US genuinely is double the reach - but this
    vocabulary is tiers, and tiers max.)
    """
    if not model.deployment_environments:
        return LATENT_RISK_FLOOR
    return max(ENVIRONMENT_WEIGHTS.get(env, 1.0) for env in model.deployment_environments)


def severity_for(score: float) -> str:
    for label, threshold in SEVERITY_THRESHOLDS:
        if score >= threshold:
            return label
    return "LOW"


def coverage_for(results: list[DetectorResult]) -> AssessmentCoverage:
    missing = tuple(m for r in results for m in r.missing)
    return AssessmentCoverage(
        conclusive=sum(1 for r in results if r.is_conclusive),
        total=len(results),
        missing=missing,
    )


def score_model(model: ModelSnapshot, results: list[DetectorResult]) -> ModelRiskScore:
    """Score a model from its detector results.

    Only FINDING results contribute to the score. INSUFFICIENT_DATA is
    absence of evidence, not evidence of safety *or* of risk, so it moves
    the score not at all and is reported through coverage instead. A model
    where every detector came back INSUFFICIENT_DATA therefore scores 0
    with coverage 0/3 - which reads correctly as "we could not assess
    this", rather than as "this is fine".

    Always returns a score object (never None), because a PASS with full
    coverage is a real, publishable result - "checked, clean" is worth
    recording, and it's what makes the risk table trustworthy.
    """
    findings = [f for r in results for f in r.findings]
    radius = blast_radius(model)
    if findings:
        max_weight = max(DETECTOR_WEIGHTS[f.detector] for f in findings)
        score = round(max_weight * radius, 2)
    else:
        score = 0.0
    return ModelRiskScore(
        model_urn=model.urn,
        findings=tuple(findings),
        blast_radius=radius,
        score=score,
        severity=severity_for(score),
        coverage=coverage_for(results),
    )
