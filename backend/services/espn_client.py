import os
from espn_api.football import League
from typing import Optional, Dict, Any, List, Iterable, Tuple
import logging

logger = logging.getLogger(__name__)


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


class ESPNClient:
    """Client for interacting with ESPN Fantasy Football API"""

    _UNAVAILABLE_PLAYER_STATUSES = {
        "OUT",
        "O",
        "IR",
        "INJURY_RESERVE",
        "INJURED_RESERVE",
    }

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
    def _extract_total_points(player: Any) -> float:
        """Extract season points for a player object using ESPN's stats structure."""
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
                if not isinstance(item, dict):
                    continue

                points = item.get("points")
                if points is None:
                    points = item.get("projected_points")

                if points is not None:
                    try:
                        total += float(points)
                    except (TypeError, ValueError):
                        continue
            return total

        return 0.0

    @staticmethod
    def _extract_points_per_game(player: Any) -> float:
        """Extract ESPN's average points-per-game value for a player."""
        for attr_name in ("avg_points", "projected_avg_points", "points_per_game"):
            value = getattr(player, attr_name, None)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass

        stats_obj = getattr(player, "stats", None)
        if isinstance(stats_obj, dict):
            for _, item in stats_obj.items():
                if not isinstance(item, dict):
                    continue

                avg_points = item.get("avg_points")
                if avg_points is None:
                    avg_points = item.get("projected_avg_points")

                if avg_points is not None:
                    try:
                        return float(avg_points)
                    except (TypeError, ValueError):
                        continue

        return 0.0

    @staticmethod
    def _normalized_player_status(player: Any) -> str:
        """Return a normalized availability status from known ESPN attributes."""
        for attr_name in ("injuryStatus", "injury_status", "status"):
            value = getattr(player, attr_name, None)
            if not value:
                continue
            return str(value).strip().upper().replace(" ", "_").replace("-", "_")
        return ""

    def _is_recommendable_free_agent(self, player: Any) -> bool:
        """Exclude players who are currently Out or on Injured Reserve."""
        status = self._normalized_player_status(player)
        return status not in self._UNAVAILABLE_PLAYER_STATUSES

    def serialize_player(self, player: Any) -> Dict[str, Any]:
        """Serialize an ESPN player object to a stable dictionary."""
        espn_id = getattr(player, "playerId", None) or getattr(player, "player_id", None)
        points = self._extract_total_points(player)
        points_per_game = self._extract_points_per_game(player)
        lineup_slot = str(getattr(player, "lineupSlot", "") or "")

        return {
            "key": self._player_key(player),
            "espn_id": espn_id,
            "name": str(getattr(player, "name", "Unknown Player")),
            "position": self._player_position(player),
            "lineup_slot": lineup_slot,
            "status": self._normalized_player_status(player),
            "pro_team": getattr(player, "proTeam", ""),
            "total_points": points,
            "points_per_game": points_per_game,
        }

    def _get_team_lineup_slots(self, league: League, team_id: int) -> Dict[str, str]:
        """Return player key -> lineup slot for the selected team from current box score data."""
        try:
            box_scores = league.box_scores()
        except Exception as exc:
            logger.debug("Unable to load box scores for lineup slots: %s", exc)
            return {}

        slots_by_key: Dict[str, str] = {}
        for matchup in box_scores:
            for matchup_team_id, lineup in (
                (getattr(matchup, "home_team", None), getattr(matchup, "home_lineup", [])),
                (getattr(matchup, "away_team", None), getattr(matchup, "away_lineup", [])),
            ):
                if matchup_team_id != team_id:
                    continue

                for player in lineup:
                    key = self._player_key(player)
                    slot = str(getattr(player, "slot_position", "") or "").strip().upper()
                    if key and slot:
                        slots_by_key[key] = slot

        return slots_by_key

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

        target_team_id = getattr(team, "team_id", None)
        slots_by_key = self._get_team_lineup_slots(league, target_team_id) if target_team_id is not None else {}

        players = [self.serialize_player(player) for player in getattr(team, "roster", [])]
        if not slots_by_key:
            return players

        for row in players:
            player_key = row.get("key")
            if not player_key:
                continue
            lineup_slot = slots_by_key.get(player_key)
            if lineup_slot:
                row["lineup_slot"] = lineup_slot

        return players

    def _collect_rostered_player_keys(self, league: League) -> set[str]:
        """Collect player keys for every player currently assigned to a team roster."""
        keys = set()
        for team in getattr(league, "teams", []):
            for player in getattr(team, "roster", []):
                key = self._player_key(player)
                if key:
                    keys.add(key)
        return keys

    def _collect_free_agents_for_positions(
        self,
        league: League,
        size: int,
        positions: Iterable[str],
        excluded_player_keys: Optional[set[str]] = None,
    ) -> List[Any]:
        """Collect free agents for each position and dedupe by player key."""
        seen = set()
        free_agents: List[Any] = []
        excluded_player_keys = excluded_player_keys or set()

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
                if not self._is_recommendable_free_agent(player):
                    continue
                key = self._player_key(player)
                if key in seen or key in excluded_player_keys:
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

        excluded_player_keys = self._collect_rostered_player_keys(league)
        free_agents = self._collect_free_agents_for_positions(
            league,
            size=size,
            positions=positions,
            excluded_player_keys=excluded_player_keys,
        )
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
