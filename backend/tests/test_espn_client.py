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
    def __init__(self, roster, team_id=None, team_name="Unknown Team"):
        self.roster = roster
        self.team_id = team_id
        self.team_name = team_name


class FakePick:
    def __init__(self, team, player_id, player_name, round_num, round_pick, keeper_status=False):
        self.team = team
        self.playerId = player_id
        self.playerName = player_name
        self.round_num = round_num
        self.round_pick = round_pick
        self.keeper_status = keeper_status


class FakeSettings:
    def __init__(self, team_count=None, position_slot_counts=None, keeper_count=None):
        self.team_count = team_count
        self.position_slot_counts = position_slot_counts or {}
        self.keeper_count = keeper_count


class FakeLeague:
    def __init__(self, teams, free_agents_by_position, draft=None, settings=None):
        self.teams = teams
        self._free_agents_by_position = free_agents_by_position
        self.draft = draft or []
        self.settings = settings

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


def test_get_draft_picks_serializes_picks_in_order():
    client = ESPNClient()

    team_one = FakeTeam(roster=[], team_id=1, team_name="Team One")
    team_two = FakeTeam(roster=[], team_id=2, team_name="Team Two")
    draft = [
        FakePick(team=team_one, player_id=1001, player_name="First Pick RB", round_num=1, round_pick=1),
        FakePick(team=team_two, player_id=1002, player_name="Second Pick WR", round_num=1, round_pick=2, keeper_status=True),
    ]

    league = FakeLeague(teams=[team_one, team_two], free_agents_by_position={}, draft=draft)

    result = client.get_draft_picks(league)

    assert result == [
        {
            "team_id": 1,
            "team_name": "Team One",
            "player_id": 1001,
            "player_name": "First Pick RB",
            "player_key": "id:1001",
            "round_num": 1,
            "round_pick": 1,
            "is_keeper": False,
        },
        {
            "team_id": 2,
            "team_name": "Team Two",
            "player_id": 1002,
            "player_name": "Second Pick WR",
            "player_key": "id:1002",
            "round_num": 1,
            "round_pick": 2,
            "is_keeper": True,
        },
    ]


def test_get_draft_picks_returns_empty_list_before_draft_starts():
    client = ESPNClient()
    league = FakeLeague(teams=[], free_agents_by_position={}, draft=[])

    assert client.get_draft_picks(league) == []


def test_get_draft_settings_reads_from_league_settings():
    client = ESPNClient()
    settings = FakeSettings(team_count=10, position_slot_counts={"RB": 2, "WR": 2}, keeper_count=1)
    league = FakeLeague(teams=[], free_agents_by_position={}, settings=settings)

    result = client.get_draft_settings(league)

    assert result == {
        "team_count": 10,
        "position_slot_counts": {"RB": 2, "WR": 2},
        "keeper_count": 1,
    }
