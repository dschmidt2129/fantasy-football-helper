import os
from espn_api.football import League
from typing import Optional, Dict, Any, List, Iterable, Tuple
import logging

logger = logging.getLogger(__name__)


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


class ESPNClient:
    """Client for interacting with ESPN Fantasy Football API"""

    def __init__(self):
        self.swid = os.getenv("SWID")
        self.espn_s2 = os.getenv("ESPN_S2")

    def get_league(self, league_id: int, year: int) -> Optional[League]:
        """Fetch a league from ESPN API"""
        try:
            league = League(
                league_id=league_id,
                year=year,
                espn_s2=self.espn_s2,
                swid=self.swid,
                debug=False
            )
            return league
        except Exception as e:
            logger.error(f"Failed to fetch league {league_id} for year {year}: {e}")
            return None

    def get_teams(self, league: League) -> List[Dict[str, Any]]:
        """Return teams in the league with ids and display names."""
        teams: List[Dict[str, Any]] = []
        for team in getattr(league, "teams", []):
            team_id = getattr(team, "team_id", None)
            team_name = getattr(team, "team_name", "Unknown Team")
            owner = ""
            owners = getattr(team, "owners", [])
            if owners:
                first_owner = owners[0]
                owner = first_owner.get("displayName", "") if isinstance(first_owner, dict) else ""
            teams.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "owner": owner,
                }
            )
        return teams

    def find_team(self, league: League, team_id: Optional[int] = None, team_name: Optional[str] = None):
        """Find a team by id or name; defaults to the first team when not specified."""
        teams = getattr(league, "teams", [])
        if not teams:
            return None

        if team_id is not None:
            for team in teams:
                if getattr(team, "team_id", None) == team_id:
                    return team

        if team_name:
            wanted = _normalize_name(team_name)
            for team in teams:
                if _normalize_name(getattr(team, "team_name", "")) == wanted:
                    return team

        return teams[0]

    @staticmethod
    def _player_position(player: Any) -> str:
        return str(
            getattr(player, "position", None)
            or getattr(player, "eligibleSlots", ["UNK"])[0]
            or "UNK"
        )

    @staticmethod
    def _player_key(player: Any) -> str:
        espn_id = getattr(player, "playerId", None) or getattr(player, "player_id", None)
        if espn_id is not None:
            return f"id:{espn_id}"
        name = _normalize_name(str(getattr(player, "name", "unknown")))
        pos = str(getattr(player, "position", "UNK"))
        return f"name:{name}|{pos}"

    @staticmethod
    def _extract_games_played(player: Any) -> int:
        """Best-effort extraction of games played from stats containers."""
        stats_obj = getattr(player, "stats", None)
        if not stats_obj:
            return 0

        if isinstance(stats_obj, dict):
            week_keys = [k for k in stats_obj.keys() if isinstance(k, int)]
            return len(week_keys)

        return 0

    @staticmethod
    def _extract_total_points(player: Any) -> float:
        """Best-effort extraction of season points for a player object."""
        for attr_name in ("total_points", "totalPoints", "points"):
            value = getattr(player, attr_name, None)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass

        stats_obj = getattr(player, "stats", None)
        if isinstance(stats_obj, dict):
            total = 0.0
            for _, item in stats_obj.items():
                if isinstance(item, dict):
                    points = item.get("points")
                    if points is not None:
                        try:
                            total += float(points)
                        except (TypeError, ValueError):
                            continue
            return total

        return 0.0

    def serialize_player(self, player: Any) -> Dict[str, Any]:
        """Serialize an ESPN player object to a stable dictionary."""
        espn_id = getattr(player, "playerId", None) or getattr(player, "player_id", None)
        points = self._extract_total_points(player)
        games = max(self._extract_games_played(player), 1)

        return {
            "key": self._player_key(player),
            "espn_id": espn_id,
            "name": str(getattr(player, "name", "Unknown Player")),
            "position": self._player_position(player),
            "pro_team": getattr(player, "proTeam", ""),
            "total_points": points,
            "games_played": games,
            "points_per_game": points / games,
        }

    def get_roster_players(
        self,
        league: League,
        team_id: Optional[int] = None,
        team_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return serialized roster players for a selected team."""
        team = self.find_team(league, team_id=team_id, team_name=team_name)
        if team is None:
            return []

        return [self.serialize_player(player) for player in getattr(team, "roster", [])]

    def _collect_free_agents_for_positions(
        self,
        league: League,
        size: int,
        positions: Iterable[str],
    ) -> List[Any]:
        """Collect free agents for each position and dedupe by player key."""
        seen = set()
        free_agents: List[Any] = []

        for position in positions:
            try:
                players = league.free_agents(size=size, position=position)
            except TypeError:
                # API compatibility fallback for older/newer versions.
                players = league.free_agents(size=size)
            except Exception as exc:
                logger.warning("Failed to fetch free agents for %s: %s", position, exc)
                continue

            for player in players:
                key = self._player_key(player)
                if key in seen:
                    continue
                seen.add(key)
                free_agents.append(player)

        return free_agents

    def get_free_agents(
        self,
        league: League,
        size: int = 40,
        positions: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return serialized free agents for relevant fantasy positions."""
        if positions is None:
            positions = ("QB", "RB", "WR", "TE", "K", "D/ST")

        free_agents = self._collect_free_agents_for_positions(league, size=size, positions=positions)
        return [self.serialize_player(player) for player in free_agents]

    def get_scoring_snapshot(
        self,
        league_id: int,
        year: int,
        free_agent_size: int = 40,
    ) -> Dict[str, Dict[str, float]]:
        """
        Build a key->metrics map from teams + free agency for a league season.
        This provides historical totals used in recommendation scoring.
        """
        league = self.get_league(league_id=league_id, year=year)
        if not league:
            return {}

        player_rows: List[Dict[str, Any]] = []
        for team in getattr(league, "teams", []):
            for player in getattr(team, "roster", []):
                player_rows.append(self.serialize_player(player))

        player_rows.extend(self.get_free_agents(league=league, size=free_agent_size))

        snapshot: Dict[str, Dict[str, float]] = {}
        for row in player_rows:
            snapshot[row["key"]] = {
                "total_points": float(row.get("total_points", 0.0)),
                "points_per_game": float(row.get("points_per_game", 0.0)),
            }

        return snapshot

    def get_player_stats(self, league_id: int, year: int) -> Dict[str, Any]:
        """Fetch player statistics for a league and year"""
        league = self.get_league(league_id, year)
        if not league:
            return {}

        all_players: List[Dict[str, Any]] = []
        for team in getattr(league, "teams", []):
            for player in getattr(team, "roster", []):
                all_players.append(self.serialize_player(player))

        return {
            "league_name": league.settings.name,
            "year": year,
            "teams": self.get_teams(league),
            "players": all_players,
        }
