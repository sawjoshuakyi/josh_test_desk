import tracker


def test_af_event_and_summary():
    f = {"fixture": {"id": 7, "status": {"short": "2H", "elapsed": 63}},
         "teams": {"home": {"name": "San Jose Earthquakes", "winner": None}, "away": {"name": "Houston Dynamo", "winner": None}},
         "goals": {"home": 1, "away": 0},
         "statistics": [{"team": {"id": 1}, "statistics": [{"type": "Corner Kicks", "value": 6}]},
                        {"team": {"id": 2}, "statistics": [{"type": "Corner Kicks", "value": None}, {"type": "Shots on Goal", "value": 2}]}],
         "players": [{"team": {"id": 1}, "players": [
             {"player": {"name": "C. Espinoza"}, "statistics": [{"games": {"minutes": 63, "substitute": False}, "shots": {"on": 2, "total": 3}, "goals": {}}]},
             {"player": {"name": "Bench Guy"}, "statistics": [{"games": {"minutes": None, "substitute": True}, "shots": {}, "goals": {}}]}]}]}
    ev = tracker.af_event(f)
    state, done, clock = tracker.game_status(ev)
    assert (state, done, clock) == ("in", False, "63'")
    assert [x["score"] for x in tracker.team_scores(ev)] == [1.0, 0.0]
    summ = tracker.af_summary(f)
    assert tracker.team_stat_total(summ, "wonCorners") == 6.0
    assert tracker.soccer_player_stat(summ, "C. Espinoza", "sot") == 2.0
    assert tracker.soccer_player_stat(summ, "Bench Guy", "sot") is None
