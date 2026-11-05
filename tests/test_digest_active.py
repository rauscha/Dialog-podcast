import json
from datetime import datetime, timezone
from pathlib import Path

import generate_podcast as gp
from digest_shows import load_shows

# A Monday, so a "mon" show would otherwise be due.
_MONDAY = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
_SHOW = {"schedule": {"weekday": "mon", "hour": 5}}


def test_inactive_show_is_never_due():
    show = {**_SHOW, "active": False}
    assert gp._show_is_due(show, {}, today=_MONDAY)[0] is False
    assert gp._show_is_due(show, {}, force=True, today=_MONDAY)[0] is False


def test_active_defaults_to_true():
    assert gp._show_is_due(_SHOW, {}, today=_MONDAY) == (True, "scheduled today")


def test_real_shows_are_all_inactive():
    shows = load_shows(Path(gp.__file__).parent)
    assert shows and all(s["active"] is False for s in shows.values())


def test_load_shows_keeps_active_flag():
    raw = json.loads((Path(gp.__file__).parent / "digests.json").read_text())
    assert all(s.get("active") is False for s in raw["shows"].values())
