from src.services.emergency import screen_emergency


def test_emergency_detector_handles_vietnamese_diacritics():
    result = screen_emergency("Bệnh nhân bất tỉnh, không đánh thức được")
    assert result.emergency
    assert "EMERGENCY_UNCONSCIOUS" in result.rule_ids


def test_emergency_detector_respects_simple_negation():
    assert not screen_emergency("Tôi đã hết đau ngực dữ dội").emergency
