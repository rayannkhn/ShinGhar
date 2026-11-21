"""Tests for shinghar.alerts: text uses only given numbers; human review gate; nothing is sent."""
import pytest

from shinghar import alerts as a


def _alert(band="high"):
    return a.Alert("x1", "Kalam", band, 72.0, "brief", "ur", "ps")


def test_briefing_contains_inputs_and_screening_wording():
    text = a.briefing_en("Kalam", "Swat", 72.4, "high", 0.85, ["Reason one (+20 points)", "Reason two"], "2026-11-20")
    assert "72.4/100" in text and "HIGH" in text and "85%" in text
    assert "  - Reason one (+20 points)" in text and "  - Reason two" in text
    assert "not a forecast" in text and "has not been sent" in text


def test_community_messages_fill_village_and_number_and_skip_low():
    ur = a.community_message("ur", "high", "کالام")
    ps = a.community_message("ps", "watch", "کالام")
    assert "کالام" in ur and "1122" in ur
    assert "کالام" in ps and "1122" in ps
    assert a.community_message("ur", "low", "کالام") is None


def test_high_alert_cannot_be_ready_without_review():
    al = _alert("high")
    with pytest.raises(a.ReviewError):
        a.mark_ready(al)
    a.mark_reviewed(al, "Dr. Expert")
    a.mark_ready(al)
    assert al.state == "ready" and al.sent is False
    assert [h["event"] for h in al.history][0] == "reviewed by expert"


def test_watch_alert_can_go_ready_directly_and_review_needs_a_name():
    al = _alert("watch")
    with pytest.raises(a.ReviewError):
        a.mark_reviewed(al, "  ")
    a.mark_ready(al)
    assert al.state == "ready"
    with pytest.raises(a.ReviewError):
        a.mark_reviewed(al, "someone")


def test_store_round_trip_keeps_unicode(tmp_path):
    store = a.AlertStore(tmp_path / "alerts.json")
    assert store.load() == {}
    al = a.Alert("x1", "Kalam", "high", 70.0, "b", a.community_message("ur", "high", "کالام"), None)
    store.save({"x1": al})
    back = store.load()["x1"]
    assert back.message_ur == al.message_ur and back.state == "draft"
    assert "کالام" in (tmp_path / "alerts.json").read_text(encoding="utf-8")


def test_community_messages_carry_each_villages_own_reason_and_number():
    comps_a = [{"name": "forest_loss_upslope", "raw": 5.76, "points": 7.2, "weight": .25},
               {"name": "loss_slope", "raw": 35.7, "points": 15.0, "weight": .15},
               {"name": "flood_path", "raw": 34.2, "points": 7.0, "weight": .2}]
    comps_b = [{"name": "flood_path", "raw": 9.9, "points": 17.8, "weight": .2},
               {"name": "forest_loss_upslope", "raw": 3.73, "points": 4.7, "weight": .25}]
    fa, fb = a.top_facts(comps_a), a.top_facts(comps_b)
    assert fa == [("forest_loss_upslope", 5.76), ("loss_slope", 35.7)]       # area before its slope
    assert fb == [("flood_path", 9.9), ("forest_loss_upslope", 3.73)]
    for lang in ("ur", "ps"):
        ma = a.community_message(lang, "watch", "الف", fa)
        mb = a.community_message(lang, "watch", "ب", fb)
        assert "5.8" in ma and "36" in ma and "10" in mb and "3.7" in mb and ma != mb
        assert "1122" in ma and a.NOT_FORECAST[lang] in ma


def test_low_band_message_only_for_a_labelled_example():
    f = [("forest_loss_upslope", 5.76)]
    assert a.community_message("ur", "low", "الف", f) is None
    assert "5.8" in a.community_message("ur", "low", "الف", f, example=True)
    text = a.briefing_en("Kalam", "Swat", 29.8, "low", 1.0, ["r"], "x", example=True)
    assert text.startswith("EXAMPLE ONLY") and "29.8/100" in text
