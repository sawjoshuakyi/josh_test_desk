from desk.soccer.apifootball import parse_fixture

FIX = {"fixture": {"id": 101, "date": "2026-11-23T15:00:00+00:00", "status": {"short": "FT"}},
       "league": {"id": 39, "season": 2026, "round": "Regular Season - 13"},
       "teams": {"home": {"id": 55, "name": "Brentford"}, "away": {"id": 45, "name": "Everton"}},
       "goals": {"home": 2, "away": 1},
       "statistics": [
           {"team": {"id": 55}, "statistics": [{"type": "Shots on Goal", "value": 6}, {"type": "Total Shots", "value": 14},
                                                {"type": "Corner Kicks", "value": 7}, {"type": "Ball Possession", "value": "48%"},
                                                {"type": "expected_goals", "value": "1.84"}]},
           {"team": {"id": 45}, "statistics": [{"type": "Shots on Goal", "value": 3}, {"type": "Total Shots", "value": 9},
                                                {"type": "Corner Kicks", "value": None}, {"type": "Ball Possession", "value": "52%"}]}],
       "players": [{"team": {"id": 55}, "players": [
           {"player": {"id": 9, "name": "I. Thiago"}, "statistics": [{"games": {"minutes": 90, "position": "F", "substitute": False},
                                                                      "shots": {"total": 4, "on": 3}, "goals": {"total": 1, "assists": None}}]},
           {"player": {"id": 10, "name": "Unused Sub"}, "statistics": [{"games": {"minutes": None, "position": "M", "substitute": True},
                                                                        "shots": {"total": None, "on": None}, "goals": {"total": None}}]}]}]}


def test_parse_fixture():
    rows, players = parse_fixture(FIX)
    h, a = rows
    assert (h["league"], h["team_id"], h["opp_id"], h["home"], h["goals"], h["goals_against"]) == ("epl", "55", "45", 1, 2, 1)
    assert (h["shotsOnTarget"], h["wonCorners"], h["possessionPct"], h["xg"]) == (6.0, 7.0, 48.0, 1.84)
    assert a["wonCorners"] == 0.0 and a["xg"] is None
    assert len(players) == 1 and players[0]["sot"] == 3 and players[0]["starter"] == 1 and players[0]["pos"] == "F"


def test_update_end_to_end(tmp_path, monkeypatch):
    import copy
    from desk.soccer import apifootball as af
    monkeypatch.setattr(af, "DIR", str(tmp_path))
    monkeypatch.setattr(af, "MATCHES", str(tmp_path / "matches"))
    monkeypatch.setattr(af, "PLAYERS", str(tmp_path / "players"))
    calls = []

    def fake_get(path, **params):
        calls.append((path, params))
        if path == "leagues":
            return [{"league": {"id": 39}, "seasons": [{"year": 2026, "current": True}]}]
        if path == "fixtures" and "ids" in params:
            return [copy.deepcopy(FIX)]
        return [{"fixture": {"id": 101, "date": "2026-11-23T15:00:00+00:00", "status": {"short": "FT"}}},
                {"fixture": {"id": 102, "date": "2026-11-30T15:00:00+00:00", "status": {"short": "NS"}}}]

    monkeypatch.setattr(af, "get", fake_get)
    import datetime as dt
    rep = af.update(dt.date(2026, 11, 24), leagues=[39], backfill=True)
    assert rep["fixtures_loaded"] == 1 and len(af.matches()) == 2 and len(af.players()) == 1
    rep2 = af.update(dt.date(2026, 11, 24), leagues=[39])      # second run skips stored fixture
    assert rep2["fixtures_loaded"] == 0
