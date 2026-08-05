from backend.services.espn_client import ESPNClient


class FakePlayer:
    def __init__(self, player_id, name, position="RB", status=None, injury_status=None):
        self.playerId = player_id
        self.name = name
        self.position = position
        self.proTeam = "FA"
        self.stats = {}
        self.status = status
        self.injuryStatus = injury_status


class FakeTeam:
    def __init__(self, roster):
        self.roster = roster


class FakeLeague:
    def __init__(self, teams, free_agents_by_position):
        self.teams = teams
        self._free_agents_by_position = free_agents_by_position

    def free_agents(self, size=40, position=None):
        if position is None:
            return []
        return self._free_agents_by_position.get(position, [])


def test_get_free_agents_excludes_players_already_on_any_team():
    client = ESPNClient()

    roster_player = FakePlayer(player_id=101, name="Roster QB", position="QB")
    assigned_player = FakePlayer(player_id=101, name="Roster QB", position="QB")
    available_player = FakePlayer(player_id=999, name="Available QB", position="QB")

    league = FakeLeague(
        teams=[FakeTeam(roster=[roster_player])],
        free_agents_by_position={"QB": [assigned_player, available_player]},
    )

    result = client.get_free_agents(league, size=5, positions=("QB",))

    assert [player["name"] for player in result] == ["Available QB"]


def test_get_free_agents_excludes_out_and_ir_players():
    client = ESPNClient()

    healthy_player = FakePlayer(player_id=501, name="Healthy RB", position="RB")
    out_player = FakePlayer(player_id=502, name="Out RB", position="RB", status="O")
    ir_player = FakePlayer(
        player_id=503,
        name="IR RB",
        position="RB",
        injury_status="INJURY_RESERVE",
    )

    league = FakeLeague(
        teams=[FakeTeam(roster=[])],
        free_agents_by_position={"RB": [healthy_player, out_player, ir_player]},
    )

    result = client.get_free_agents(league, size=10, positions=("RB",))

    assert [player["name"] for player in result] == ["Healthy RB"]
