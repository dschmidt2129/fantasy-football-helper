from backend.services.optimizer import RosterOptimizer, RecommendationConfig


class FakeTeam:
    def __init__(self, team_id=1, team_name="Test Team"):
        self.team_id = team_id
        self.team_name = team_name


class FakeLeague:
    def __init__(self):
        self.teams = [FakeTeam(team_id=1, team_name="Team 1"), FakeTeam(team_id=2, team_name="Team 2")]
        self.settings = type("Settings", (), {"name": "Test League"})()


class FakeClient:
    def __init__(self, roster_players, free_agents, team_rosters=None):
        self._league = FakeLeague()
        self._team = self._league.teams[0]
        self._roster_players = roster_players
        self._free_agents = free_agents
        self._team_rosters = team_rosters or {getattr(self._team, "team_id", 1): roster_players}

    def get_league(self, league_id, year):
        return self._league

    def find_team(self, league, team_id=None, team_name=None):
        return self._team

    def get_roster_players(self, league, team_id=None, team_name=None):
        if team_id is not None and team_id in self._team_rosters:
            return [dict(player) for player in self._team_rosters[team_id]]
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


def test_analyze_league_scores_bonuses_for_injury_context_and_matchups():
    selected_team_roster = [
        {
            "key": "rb-roster",
            "name": "Roster RB",
            "position": "RB",
            "status": "",
            "pro_team": "BUF",
            "points_per_game": 4.0,
            "total_points": 40.0,
        }
    ]

    free_agents = [
        {
            "key": "rb-add",
            "name": "Add RB",
            "position": "RB",
            "status": "",
            "points_per_game": 5.0,
            "total_points": 50.0,
            "matchup_favorable": True,
        },
        {
            "key": "rb-injured-teamm-mate",
            "name": "Injured Teammate RB",
            "position": "RB",
            "status": "O",
            "pro_team": "BUF",
            "points_per_game": 2.0,
            "total_points": 20.0,
        },
    ]

    optimizer = RosterOptimizer(
        client=FakeClient(
            roster_players=selected_team_roster,
            free_agents=free_agents,
            team_rosters={1: selected_team_roster},
        ),
        config=RecommendationConfig(min_score_improvement=0.0),
    )

    result = optimizer.analyze_league(league_id=1, year=2025)

    assert result["recommendations"], "Expected at least one recommendation"
    assert result["recommendations"][0]["score_delta"] == 6.3
