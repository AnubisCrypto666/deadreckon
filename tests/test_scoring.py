from itertools import combinations

from detectors.models import DetectorResult, DetectorStatus, Finding, MissingSignal, ModelSnapshot
from detectors.scoring import (
    DETECTOR_WEIGHTS,
    ENVIRONMENT_WEIGHTS,
    LATENT_RISK_FLOOR,
    MAX_POSSIBLE_SCORE,
    SEVERITY_THRESHOLDS,
    blast_radius,
    coverage_for,
    is_at_risk,
    score_model,
    severity_for,
)

MODEL_URN = "urn:li:mlModel:m"
MEDIUM_THRESHOLD = dict(SEVERITY_THRESHOLDS)["MEDIUM"]
PROD_FLOOR = min(DETECTOR_WEIGHTS.values()) * ENVIRONMENT_WEIGHTS["PROD"]


def _model(envs: tuple[str, ...]) -> ModelSnapshot:
    return ModelSnapshot(urn=MODEL_URN, name="m", training_runs=(), features=(), deployment_environments=envs)


def _finding(detector: str) -> Finding:
    return Finding(detector=detector, model_urn=MODEL_URN, summary="s")


def _finding_result(detector: str, count: int = 1) -> DetectorResult:
    return DetectorResult(detector=detector, status=DetectorStatus.FINDING,
                           findings=tuple(_finding(detector) for _ in range(count)), checked=1)


def _pass_result(detector: str) -> DetectorResult:
    return DetectorResult(detector=detector, status=DetectorStatus.PASS, checked=1)


def _nodata_result(detector: str, missing: str = "some.aspect") -> DetectorResult:
    return DetectorResult(detector=detector, status=DetectorStatus.INSUFFICIENT_DATA,
                           missing=(MissingSignal(subject_urn="urn:li:dataset:x", missing=missing),))


# --- blast radius (A3: max over environments, not sum) ---------------------

def test_blast_radius_prod_beats_staging():
    assert blast_radius(_model(("PROD",))) > blast_radius(_model(("STAGING",)))


def test_blast_radius_undeployed_is_nonzero_but_below_staging():
    assert 0 < blast_radius(_model(())) < blast_radius(_model(("STAGING",)))
    assert blast_radius(_model(())) == LATENT_RISK_FLOOR


def test_blast_radius_takes_worst_environment_not_the_sum():
    # A model already in PROD is not made riskier by also sitting in
    # STAGING - the production exposure dominates entirely.
    assert blast_radius(_model(("PROD", "STAGING"))) == blast_radius(_model(("PROD",)))


def test_max_possible_score_is_actually_reachable():
    worst = _model(("PROD",))
    strongest = max(DETECTOR_WEIGHTS, key=lambda d: DETECTOR_WEIGHTS[d])
    result = score_model(worst, [_finding_result(strongest)])
    assert result.score == MAX_POSSIBLE_SCORE


# --- band invariant (A1) ---------------------------------------------------

def test_no_detector_combination_can_cross_an_environment_band():
    """Environment picks the band, detector confidence only orders within
    it. If this breaks, a STAGING model could outrank a PROD one and the
    whole "blast radius dominates" thesis stops holding."""
    all_detector_sets = [c for n in range(1, len(DETECTOR_WEIGHTS) + 1)
                          for c in combinations(sorted(DETECTOR_WEIGHTS), n)]

    def scores_for(envs):
        return [score_model(_model(envs), [_finding_result(d) for d in ds]).score
                for ds in all_detector_sets]

    undeployed = scores_for(())
    staging = scores_for(("STAGING",))
    prod = scores_for(("PROD",))

    assert max(undeployed) < min(staging)
    assert max(staging) < min(prod)


def test_undeployed_can_never_reach_medium():
    all_detector_sets = [c for n in range(1, len(DETECTOR_WEIGHTS) + 1)
                          for c in combinations(sorted(DETECTOR_WEIGHTS), n)]
    for ds in all_detector_sets:
        result = score_model(_model(()), [_finding_result(d) for d in ds])
        assert not is_at_risk(result.severity)


def test_medium_threshold_sits_in_a_gap_not_on_a_reachable_score():
    """A threshold balanced exactly on a reachable value flips whole
    classes of models on a rounding-scale change to any weight."""
    reachable = {round(w * r, 2)
                 for w in DETECTOR_WEIGHTS.values()
                 for r in list(ENVIRONMENT_WEIGHTS.values()) + [LATENT_RISK_FLOOR]}
    assert MEDIUM_THRESHOLD not in reachable


# --- scoring ---------------------------------------------------------------

def test_score_uses_highest_weight_detector_when_multiple_findings():
    results = [_finding_result("D3"), _finding_result("D2")]
    scored = score_model(_model(("PROD",)), results)
    assert scored.score == round(DETECTOR_WEIGHTS["D2"] * ENVIRONMENT_WEIGHTS["PROD"], 2)
    assert scored.finding_count == 2


def test_score_is_zero_when_all_detectors_pass():
    scored = score_model(_model(("PROD",)), [_pass_result(d) for d in DETECTOR_WEIGHTS])
    assert scored.score == 0.0
    assert scored.severity == "LOW"
    assert scored.coverage.is_fully_covered


def test_insufficient_data_does_not_move_the_score():
    with_gaps = score_model(_model(("PROD",)), [_finding_result("D1"), _nodata_result("D2"), _nodata_result("D3")])
    without_gaps = score_model(_model(("PROD",)), [_finding_result("D1"), _pass_result("D2"), _pass_result("D3")])
    assert with_gaps.score == without_gaps.score


def test_severity_thresholds_are_ordered():
    assert severity_for(3.0) == "HIGH"
    assert severity_for(1.0) == "MEDIUM"
    assert severity_for(0.1) == "LOW"


def test_prod_d2_is_high_severity():
    assert score_model(_model(("PROD",)), [_finding_result("D2")]).severity == "HIGH"


def test_only_medium_and_high_are_taggable():
    assert is_at_risk("HIGH") is True
    assert is_at_risk("MEDIUM") is True
    assert is_at_risk("LOW") is False


# --- coverage (B seam: INSUFFICIENT_DATA lives here, not in the score) -----

def test_coverage_counts_conclusive_detectors():
    coverage = coverage_for([_finding_result("D1"), _pass_result("D2"), _nodata_result("D3")])
    assert (coverage.conclusive, coverage.total) == (2, 3)
    assert str(coverage) == "2/3"
    assert not coverage.is_fully_covered
    assert not coverage.is_unassessable


def test_coverage_is_unassessable_only_when_nothing_was_conclusive():
    all_missing = coverage_for([_nodata_result(d) for d in DETECTOR_WEIGHTS])
    assert all_missing.is_unassessable
    assert str(all_missing) == "0/3"

    partial = coverage_for([_pass_result("D1"), _nodata_result("D2"), _nodata_result("D3")])
    assert not partial.is_unassessable


def test_coverage_collects_what_was_missing():
    coverage = coverage_for([_nodata_result("D1", "operation.lastUpdatedTimestamp"),
                              _nodata_result("D2", "deadreckon.schemaChangedAt"),
                              _pass_result("D3")])
    assert {m.missing for m in coverage.missing} == {
        "operation.lastUpdatedTimestamp", "deadreckon.schemaChangedAt"}


def test_unassessable_model_scores_zero_but_is_not_reported_as_clean():
    scored = score_model(_model(("PROD",)), [_nodata_result(d) for d in DETECTOR_WEIGHTS])
    assert scored.score == 0.0
    assert scored.coverage.is_unassessable
    # The score alone would read as "fine" - coverage is what stops that
    # from being mistaken for a clean bill of health.
    assert not scored.coverage.is_fully_covered


# --- ranking (A2: multiplicity breaks ties, not the scalar) ----------------

def test_finding_count_breaks_ties_without_changing_the_score():
    one = score_model(_model(("PROD",)), [_finding_result("D2", count=1)])
    four = score_model(_model(("PROD",)), [_finding_result("D2", count=4)])

    assert one.score == four.score
    assert four.sort_key < one.sort_key  # sorts ahead


def test_score_dominates_finding_count_in_the_ranking():
    high_score_one_finding = score_model(_model(("PROD",)), [_finding_result("D2", count=1)])
    low_score_many_findings = score_model(_model(("STAGING",)), [_finding_result("D2", count=9)])

    assert high_score_one_finding.sort_key < low_score_many_findings.sort_key


# --- latent risk floor -----------------------------------------------------
# No seeded model is undeployed (the control model is deployed to STAGING
# on purpose, so "clean" can't be read as "not serving anything"). That
# means this tier never appears in the demo data and these tests are its
# only coverage - keep them exhaustive rather than illustrative.

def test_latent_floor_produces_exact_expected_scores_per_detector():
    for detector, weight in DETECTOR_WEIGHTS.items():
        scored = score_model(_model(()), [_finding_result(detector)])
        assert scored.blast_radius == LATENT_RISK_FLOOR
        assert scored.score == round(weight * LATENT_RISK_FLOOR, 2)


def test_undeployed_model_with_a_finding_is_still_scored_and_ranked():
    """An undeployed model must not silently drop out of the table - the
    finding is real, it just isn't serving traffic yet."""
    scored = score_model(_model(()), [_finding_result("D2")])
    assert scored.score > 0
    assert scored.finding_count == 1
    assert scored.sort_key is not None
    assert not is_at_risk(scored.severity)


def test_undeployed_always_ranks_below_any_deployed_model_with_a_finding():
    strongest_undeployed = score_model(_model(()), [_finding_result(d) for d in DETECTOR_WEIGHTS])
    weakest_staging = score_model(_model(("STAGING",)),
                                   [_finding_result(min(DETECTOR_WEIGHTS, key=DETECTOR_WEIGHTS.get))])
    assert weakest_staging.sort_key < strongest_undeployed.sort_key


def test_latent_floor_is_strictly_between_zero_and_the_lowest_deployed_score():
    lowest_deployed = min(DETECTOR_WEIGHTS.values()) * min(ENVIRONMENT_WEIGHTS.values())
    highest_latent = max(DETECTOR_WEIGHTS.values()) * LATENT_RISK_FLOOR
    assert 0 < highest_latent < lowest_deployed


# --- clean models stay in the table ---------------------------------------

def test_clean_model_scores_zero_but_still_produces_a_sortable_result():
    """The control model scores 0.0 - it must still be a first-class row
    (document + properties get written for it) rather than vanishing."""
    scored = score_model(_model(("STAGING",)), [_pass_result(d) for d in DETECTOR_WEIGHTS])
    assert scored.score == 0.0
    assert scored.finding_count == 0
    assert scored.coverage.is_fully_covered
    assert not is_at_risk(scored.severity)
    assert not scored.coverage.is_unassessable


def test_clean_model_sorts_last_behind_every_model_with_a_finding():
    clean = score_model(_model(("PROD",)), [_pass_result(d) for d in DETECTOR_WEIGHTS])
    faintest_finding = score_model(_model(()), [_finding_result(min(DETECTOR_WEIGHTS, key=DETECTOR_WEIGHTS.get))])
    assert faintest_finding.sort_key < clean.sort_key
