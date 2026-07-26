from detectors.models import Finding, ModelSnapshot
from detectors.scoring import blast_radius, is_at_risk, score_model, severity_for

MODEL_URN = "urn:li:mlModel:m"


def _model(envs: tuple[str, ...]) -> ModelSnapshot:
    return ModelSnapshot(urn=MODEL_URN, name="m", training_runs=(), features=(), deployment_environments=envs)


def test_blast_radius_prod_beats_staging():
    assert blast_radius(_model(("PROD",))) > blast_radius(_model(("STAGING",)))


def test_blast_radius_undeployed_is_nonzero_but_low():
    radius = blast_radius(_model(()))
    assert 0 < radius < blast_radius(_model(("STAGING",)))


def test_blast_radius_sums_multiple_deployments():
    assert blast_radius(_model(("PROD", "STAGING"))) == blast_radius(_model(("PROD",))) + blast_radius(_model(("STAGING",)))


def test_score_none_when_no_findings():
    assert score_model(_model(("PROD",)), []) is None


def test_score_uses_highest_weight_detector_when_multiple_findings():
    findings = [
        Finding(detector="D3", model_urn=MODEL_URN, summary="s1"),
        Finding(detector="D2", model_urn=MODEL_URN, summary="s2"),
    ]
    result = score_model(_model(("PROD",)), findings)
    assert result is not None
    assert result.score == round(1.0 * blast_radius(_model(("PROD",))), 2)
    assert len(result.findings) == 2


def test_severity_thresholds_are_ordered():
    assert severity_for(3.0) == "HIGH"
    assert severity_for(1.0) == "MEDIUM"
    assert severity_for(0.1) == "LOW"


def test_prod_d2_is_high_severity():
    result = score_model(_model(("PROD",)), [Finding(detector="D2", model_urn=MODEL_URN, summary="s")])
    assert result is not None
    assert result.severity == "HIGH"


def test_undeployed_d3_is_low_severity():
    result = score_model(_model(()), [Finding(detector="D3", model_urn=MODEL_URN, summary="s")])
    assert result is not None
    assert result.severity == "LOW"


def test_only_medium_and_high_are_taggable():
    assert is_at_risk("HIGH") is True
    assert is_at_risk("MEDIUM") is True
    assert is_at_risk("LOW") is False


def test_undeployed_model_is_not_taggable_even_with_a_finding():
    result = score_model(_model(()), [Finding(detector="D2", model_urn=MODEL_URN, summary="s")])
    assert result is not None
    assert is_at_risk(result.severity) is False
