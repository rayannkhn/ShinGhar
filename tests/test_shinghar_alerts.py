"""Tests for shinghar.alerts: text uses only given numbers; human review gate; nothing is sent."""
import pytest

from shinghar import alerts as a


def _alert(band="high"):
    return a.Alert("x1", "Kalam", band, 72.0, "brief", "ur", "ps")


def test_briefing_contains_inputs_and_screening_wording():
    text = a.briefing_en("Kalam", "Swat", 72.4, "high", 0.85, ["Reason one (+20 points)", "Reason two"], "2026-11-20")
    assert "72/100" in text and "HIGH" in text and "85%" in text
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
