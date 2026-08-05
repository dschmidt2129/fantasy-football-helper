from backend.services.optimizer import RosterOptimizer, RecommendationConfig


class FakeTeam:
    def __init__(self, team_id=1, team_name="Test Team"):
        self.team_id = team_id
        self.team_name = team_name


class FakeLeague:
    def __init__(self):
        self.teams = [FakeTeam()]
        self.settings = type("Settings", (), {"name": "Test League"})()


class FakeClient:
    def __init__(self, roster_players, free_agents):
        self._league = FakeLeague()
        self._team = self._league.teams[0]
        self._roster_players = roster_players
        self._free_agents = free_agents

    def get_league(self, league_id, year):
        return self._league

    def find_team(self, league, team_id=None, team_name=None):
        return self._team

    def get_roster_players(self, league, team_id=None, team_name=None):
        return [dict(player) for player in self._roster_players]

    def get_free_agents(self, league, size=40, positions=None):
        return [dict(player) for player in self._free_agents]

    def get_scoring_snapshot(self, league_id, year, free_agent_size=40):
        return {}


def test_analyze_league_prioritizes_ir_player_for_drop():
    roster_players = [
        {
            "key": "rb-healthy",
            "name": "Healthy RB",
            "position": "RB",
            "status": "",
            "points_per_game": 5.0,
            "total_points": 50.0,
        },
        {
            "key": "rb-ir",
            "name": "IR RB",
            "position": "RB",
            "status": "IR",
            "points_per_game": 9.0,
            "total_points": 90.0,
        },
    ]

    free_agents = [
        {
            "key": "rb-add",
            "name": "Add RB",
            "position": "RB",
            "status": "",
            "points_per_game": 10.0,
            "total_points": 100.0,
        }
    ]

    optimizer = RosterOptimizer(
        client=FakeClient(roster_players=roster_players, free_agents=free_agents),
        config=RecommendationConfig(min_score_improvement=0.0),
    )

    result = optimizer.analyze_league(league_id=1, year=2025)

    assert result["recommendations"], "Expected at least one recommendation"
    assert result["recommendations"][0]["drop"]["name"] == "IR RB"
