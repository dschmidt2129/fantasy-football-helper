from backend.services.draft_optimizer import DraftOptimizer, DraftOptimizerConfig


class FakeTeam:
    def __init__(self, team_id, team_name):
        self.team_id = team_id
        self.team_name = team_name


class FakeSettings:
    def __init__(self, name="Test League"):
        self.name = name


class FakeLeague:
    def __init__(self, teams):
        self.teams = teams
        self.settings = FakeSettings()


class FakeClient:
    def __init__(
        self,
        teams,
        selected_team_id,
        draft_picks,
        draft_settings,
        free_agents,
        scoring_snapshot=None,
        roster_players=None,
    ):
        self._league = FakeLeague(teams=teams)
        self._selected_team_id = selected_team_id
        self._draft_picks = draft_picks
        self._draft_settings = draft_settings
        self._free_agents = free_agents
        self._scoring_snapshot = scoring_snapshot or {}
        self._roster_players = roster_players or []

    def get_league(self, league_id, year):
        return self._league

    def find_team(self, league, team_id=None, team_name=None):
        for team in league.teams:
            if team.team_id == self._selected_team_id:
                return team
        return league.teams[0] if league.teams else None

    def get_draft_picks(self, league):
        return [dict(pick) for pick in self._draft_picks]

    def get_draft_settings(self, league):
        return dict(self._draft_settings)

    def get_roster_players(self, league, team_id=None, team_name=None):
        return [dict(player) for player in self._roster_players]

    def get_free_agents(self, league, size=40, positions=None):
        return [dict(player) for player in self._free_agents]

    def get_scoring_snapshot(self, league_id, year, free_agent_size=40):
        return dict(self._scoring_snapshot)


def _pick(team_id, player_id, player_name, round_num, round_pick):
    return {
        "team_id": team_id,
        "team_name": f"Team {team_id}",
        "player_id": player_id,
        "player_name": player_name,
        "player_key": f"id:{player_id}",
        "round_num": round_num,
        "round_pick": round_pick,
        "is_keeper": False,
    }


def test_recommend_next_pick_excludes_already_drafted_players():
    teams = [FakeTeam(1, "My Team"), FakeTeam(2, "Rival Team")]
    draft_picks = [_pick(team_id=2, player_id=501, player_name="Drafted WR", round_num=1, round_pick=1)]
    free_agents = [
        {"key": "id:501", "name": "Drafted WR", "position": "WR", "total_points": 300.0, "points_per_game": 20.0},
        {"key": "id:502", "name": "Available RB", "position": "RB", "total_points": 250.0, "points_per_game": 16.0},
    ]

    optimizer = DraftOptimizer(
        client=FakeClient(
            teams=teams,
            selected_team_id=1,
            draft_picks=draft_picks,
            draft_settings={"team_count": 2, "position_slot_counts": {}, "keeper_count": 0},
            free_agents=free_agents,
        ),
        config=DraftOptimizerConfig(free_agent_sample_size=10, top_recommendations=5),
    )

    result = optimizer.recommend_next_pick(league_id=1, year=2025, team_id=1)

    recommended_names = [p["name"] for p in result["recommendations"]]
    assert "Drafted WR" not in recommended_names
    assert "Available RB" in recommended_names


def test_recommend_next_pick_prioritizes_rb_over_lower_priority_position_at_similar_value():
    teams = [FakeTeam(1, "My Team")]
    free_agents = [
        {"key": "id:601", "name": "Value RB", "position": "RB", "total_points": 200.0, "points_per_game": 12.0},
        {"key": "id:602", "name": "Value K", "position": "K", "total_points": 200.0, "points_per_game": 12.0},
    ]

    optimizer = DraftOptimizer(
        client=FakeClient(
            teams=teams,
            selected_team_id=1,
            draft_picks=[],
            draft_settings={"team_count": 1, "position_slot_counts": {}, "keeper_count": 0},
            free_agents=free_agents,
        ),
        config=DraftOptimizerConfig(free_agent_sample_size=10, top_recommendations=5),
    )

    result = optimizer.recommend_next_pick(league_id=1, year=2025, team_id=1)

    assert result["recommendations"][0]["name"] == "Value RB"


def test_roster_needs_reflect_already_drafted_players_at_position():
    teams = [FakeTeam(1, "My Team")]
    draft_picks = [
        _pick(team_id=1, player_id=701, player_name="My QB", round_num=1, round_pick=1),
    ]
    roster_players = [
        {"key": "id:701", "name": "My QB", "position": "QB", "total_points": 150.0, "points_per_game": 15.0},
    ]
    free_agents = [
        {"key": "id:702", "name": "Available QB", "position": "QB", "total_points": 100.0, "points_per_game": 10.0},
    ]

    optimizer = DraftOptimizer(
        client=FakeClient(
            teams=teams,
            selected_team_id=1,
            draft_picks=draft_picks,
            draft_settings={"team_count": 1, "position_slot_counts": {"QB": 1}, "keeper_count": 0},
            free_agents=free_agents,
            roster_players=roster_players,
        ),
        config=DraftOptimizerConfig(
            free_agent_sample_size=10,
            top_recommendations=5,
            bench_depth_targets={"QB": 0, "RB": 3, "WR": 3, "TE": 1, "D/ST": 1, "K": 1},
        ),
    )

    result = optimizer.recommend_next_pick(league_id=1, year=2025, team_id=1)

    assert result["roster_needs"]["QB"] == 0


def test_snake_draft_order_inferred_from_round_one_picks():
    teams = [FakeTeam(1, "Team A"), FakeTeam(2, "Team B"), FakeTeam(3, "Team C")]
    draft_picks = [
        _pick(team_id=1, player_id=1, player_name="P1", round_num=1, round_pick=1),
        _pick(team_id=2, player_id=2, player_name="P2", round_num=1, round_pick=2),
        _pick(team_id=3, player_id=3, player_name="P3", round_num=1, round_pick=3),
    ]

    optimizer = DraftOptimizer(
        client=FakeClient(
            teams=teams,
            selected_team_id=3,
            draft_picks=draft_picks,
            draft_settings={"team_count": 3, "position_slot_counts": {}, "keeper_count": 0},
            free_agents=[],
        ),
    )

    result = optimizer.recommend_next_pick(league_id=1, year=2025, team_id=3)

    # Snake draft: pick 4 (round 2) goes back to team 3 (last pick of round 1).
    assert result["draft_status"]["next_overall_pick"] == 4
    assert result["draft_status"]["team_on_the_clock"] == 3
    assert result["draft_status"]["picks_until_your_turn"] == 0


def test_draft_slot_override_used_when_round_one_incomplete():
    teams = [FakeTeam(1, "Team A"), FakeTeam(2, "Team B")]

    optimizer = DraftOptimizer(
        client=FakeClient(
            teams=teams,
            selected_team_id=2,
            draft_picks=[],
            draft_settings={"team_count": 2, "position_slot_counts": {}, "keeper_count": 0},
            free_agents=[],
        ),
    )

    result = optimizer.recommend_next_pick(league_id=1, year=2025, team_id=2, draft_slot=2)

    assert result["draft_status"]["draft_order_known"] is True
    assert result["draft_status"]["picks_until_your_turn"] == 1
