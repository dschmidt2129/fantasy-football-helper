from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.services.espn_client import ESPNClient

logger = logging.getLogger(__name__)


@dataclass
class RecommendationConfig:
    free_agent_sample_size: int = 30
    top_free_agents_per_position: int = 12
    top_recommendations: int = 10
    min_score_improvement: float = 0.75
    current_year_weight: float = 0.6
    prior_year_weight: float = 0.1
    injury_context_weight: float = 0.2
    matchup_weight: float = 0.1


class RosterOptimizer:
    """Computes roster upgrade suggestions from ESPN league data."""

    _IR_STATUSES = {"IR", "INJURY_RESERVE", "INJURED_RESERVE"}
    _INJURY_CONTEXT_STATUSES = _IR_STATUSES | {"O", "OUT"}

    def __init__(self, client: Optional[ESPNClient] = None, config: Optional[RecommendationConfig] = None):
        self.client = client or ESPNClient()
        self.config = config or RecommendationConfig()

    @staticmethod
    def _position_group(position: str) -> str:
        pos = (position or "").upper()
        if pos in {"QB", "RB", "WR", "TE", "K", "D/ST", "DST"}:
            return "D/ST" if pos == "DST" else pos
        return "BENCH"

    @staticmethod
    def _average(values: List[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _score_player(
        self,
        player_row: Dict[str, Any],
        current_snapshot: Dict[str, Dict[str, float]],
        prior_snapshot: Dict[str, Dict[str, float]],
    ) -> float:
        """Compute a weighted current+prior season score for a single player row."""
        key = player_row.get("key")
        current_points = float(player_row.get("total_points", player_row.get("points_per_game", 0.0)))

        if key in current_snapshot:
            current_points = float(
                current_snapshot[key].get("total_points", current_snapshot[key].get("points_per_game", current_points))
            )

        prior_points = float(
            prior_snapshot.get(key, {}).get("total_points", prior_snapshot.get(key, {}).get("points_per_game", 0.0))
        )

        weighted = (
            self.config.current_year_weight * current_points
            + self.config.prior_year_weight * prior_points
        )
        score = round(weighted, 3)
        logger.debug("_score_player(): key=%s current=%.2f prior=%.2f -> score=%.3f", key, current_points, prior_points, score)
        return score

    @staticmethod
    def _by_position(players: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for player in players:
            position = player.get("position", "UNK")
            grouped.setdefault(position, []).append(player)
        return grouped

    @staticmethod
    def _build_snapshot_from_rows(players: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
        """Build a key->metrics snapshot from already-fetched player rows."""
        logger.debug("_build_snapshot_from_rows() called: building snapshot from %d rows", len(players))
        snapshot: Dict[str, Dict[str, float]] = {}
        for row in players:
            key = row.get("key")
            if not key:
                continue
            snapshot[key] = {
                "total_points": float(row.get("total_points", 0.0)),
                "points_per_game": float(row.get("points_per_game", 0.0)),
            }
        return snapshot

    @classmethod
    def _is_ir_player(cls, player_row: Dict[str, Any]) -> bool:
        status = str(player_row.get("status", "")).strip().upper()
        return status in cls._IR_STATUSES

    @classmethod
    def _is_injury_context_player(cls, player_row: Dict[str, Any], roster_players: Optional[List[Dict[str, Any]]] = None) -> bool:
        if not roster_players:
            return False

        player_position = str(player_row.get("position", "")).strip().upper()
        player_team = str(player_row.get("pro_team", "") or "").strip().upper()
        if not player_position or not player_team:
            return False

        for roster_player in roster_players:
            if roster_player is player_row:
                continue

            roster_position = str(roster_player.get("position", "")).strip().upper()
            roster_team = str(roster_player.get("pro_team", "") or "").strip().upper()
            if roster_position != player_position or roster_team != player_team:
                continue

            status = str(roster_player.get("status", "")).strip().upper()
            if status in cls._INJURY_CONTEXT_STATUSES:
                return True

        return False

    @staticmethod
    def _has_favorable_matchup(player_row: Dict[str, Any]) -> bool:
        favorable = player_row.get("matchup_favorable")
        if isinstance(favorable, bool):
            return favorable

        matchup_rank = player_row.get("matchup_rank")
        if isinstance(matchup_rank, (int, float)):
            return float(matchup_rank) >= 16.0

        return False

    @classmethod
    def _drop_sort_key(cls, player_row: Dict[str, Any]) -> Tuple[int, float]:
        # IR players are prioritized for drop regardless of score.
        ir_priority = 0 if cls._is_ir_player(player_row) else 1
        return (ir_priority, float(player_row.get("score", 0.0)))

    def analyze_league(
        self,
        league_id: int,
        year: int,
        team_id: Optional[int] = None,
        team_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch league/roster/free-agent data and build upgrade recommendations for a team."""
        logger.info(
            "analyze_league() called: league_id=%s year=%s team_id=%s team_name=%s",
            league_id, year, team_id, team_name,
        )
        league = self.client.get_league(league_id=league_id, year=year)
        if league is None:
            logger.warning("analyze_league(): ESPNClient could not connect to league_id=%s year=%s", league_id, year)
            raise ValueError(f"Could not connect to ESPN league {league_id} for year {year}")

        selected_team = self.client.find_team(league=league, team_id=team_id, team_name=team_name)
        if selected_team is None:
            logger.warning("analyze_league(): no teams found in league_id=%s", league_id)
            raise ValueError("No teams found in the provided league")

        roster_players = self.client.get_roster_players(
            league=league,
            team_id=getattr(selected_team, "team_id", None),
        )
        logger.debug("analyze_league(): loaded %d roster players for selected team", len(roster_players))

        league_roster_players: List[Dict[str, Any]] = []
        for team in getattr(league, "teams", []):
            team_roster = self.client.get_roster_players(
                league=league,
                team_id=getattr(team, "team_id", None),
            )
            if team_roster:
                league_roster_players.extend(team_roster)
        logger.debug("analyze_league(): loaded %d total rostered players league-wide", len(league_roster_players))

        free_agents = self.client.get_free_agents(
            league=league,
            size=self.config.free_agent_sample_size,
        )
        logger.debug("analyze_league(): loaded %d free agents (sample size=%s)", len(free_agents), self.config.free_agent_sample_size)
        context_players = list(league_roster_players) + list(free_agents)

        # Reuse the already-fetched current-year roster + free agents and avoid
        # a second full league fetch on every analyze request.
        current_snapshot = self._build_snapshot_from_rows(roster_players + free_agents)

        prior_snapshot: Dict[str, Dict[str, float]] = {}
        prior_year = year - 1
        if prior_year > 0:
            logger.debug("analyze_league(): fetching prior-year snapshot for year=%s", prior_year)
            prior_snapshot = self.client.get_scoring_snapshot(
                league_id=league_id,
                year=prior_year,
                free_agent_size=self.config.free_agent_sample_size,
            )

        for row in roster_players:
            row["score"] = self._score_player(row, current_snapshot, prior_snapshot)
            row["position_group"] = self._position_group(str(row.get("position", "")))

        for row in free_agents:
            row["score"] = self._score_player(row, current_snapshot, prior_snapshot)
            row["position_group"] = self._position_group(str(row.get("position", "")))

        roster_by_position = self._by_position(roster_players)
        free_agents_by_position = self._by_position(free_agents)

        recommendations: List[Dict[str, Any]] = []

        for position, free_agent_list in free_agents_by_position.items():
            candidates = [p for p in roster_by_position.get(position, []) if p.get("position_group") != "BENCH"]
            if not candidates:
                continue

            # Compare against the highest-priority drop candidate.
            # IR players are chosen first; otherwise use the weakest score.
            drop_candidate = sorted(candidates, key=self._drop_sort_key)[0]

            top_free_agents = sorted(
                free_agent_list,
                key=lambda p: p.get("score", 0.0),
                reverse=True,
            )[: self.config.top_free_agents_per_position]

            for add_candidate in top_free_agents:
                improvement = float(add_candidate.get("score", 0.0)) - float(drop_candidate.get("score", 0.0))
                if self._is_injury_context_player(drop_candidate, context_players):
                    improvement += self.config.injury_context_weight
                if self._has_favorable_matchup(add_candidate):
                    improvement += self.config.matchup_weight
                if improvement < self.config.min_score_improvement:
                    continue

                recommendations.append(
                    {
                        "position": position,
                        "add": add_candidate,
                        "drop": drop_candidate,
                        "score_delta": round(improvement, 3),
                        "reason": (
                            "Weighted score uses current season production, prior-season history, "
                            "injury context, and matchup strength."
                        ),
                    }
                )

        recommendations.sort(key=lambda item: item.get("score_delta", 0.0), reverse=True)
        recommendations = recommendations[: self.config.top_recommendations]
        logger.info("analyze_league(): generated %d recommendations for league_id=%s", len(recommendations), league_id)

        roster_avg = self._average([float(p.get("score", 0.0)) for p in roster_players])
        free_agent_avg = self._average([float(p.get("score", 0.0)) for p in free_agents])

        team_name = getattr(selected_team, "team_name", "Unknown Team")
        team_id = getattr(selected_team, "team_id", None)

        return {
            "league": {
                "league_id": league_id,
                "league_name": getattr(getattr(league, "settings", None), "name", "Unknown League"),
                "season": year,
                "comparison_prior_year": prior_year,
            },
            "team": {
                "team_id": team_id,
                "team_name": team_name,
            },
            "scoring_method": {
                "current_year_weight": self.config.current_year_weight,
                "prior_year_weight": self.config.prior_year_weight,
                "injury_context_weight": self.config.injury_context_weight,
                "matchup_weight": self.config.matchup_weight,
                "formula": "score = current_year_weight * current_points + prior_year_weight * prior_year_points + injury_context_weight * is_out_or_ir + matchup_weight * favorable_matchup",
            },
            "summary": {
                "roster_size": len(roster_players),
                "free_agents_evaluated": len(free_agents),
                "roster_average_score": round(roster_avg, 3),
                "free_agent_average_score": round(free_agent_avg, 3),
                "recommendation_count": len(recommendations),
            },
            "roster": sorted(roster_players, key=lambda p: (p.get("position", ""), -float(p.get("score", 0.0)))),
            "recommendations": recommendations,
        }
