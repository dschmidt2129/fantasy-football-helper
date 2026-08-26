from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from backend.services.espn_client import ESPNClient

logger = logging.getLogger(__name__)


@dataclass
class DraftOptimizerConfig:
    free_agent_sample_size: int = 200
    top_recommendations: int = 10
    current_year_weight: float = 0.6
    prior_year_weight: float = 0.1
    # Higher value = drafted earlier when value is otherwise close, per user's stated priority order.
    position_priority: Dict[str, float] = field(
        default_factory=lambda: {
            "RB": 5.0,
            "WR": 4.0,
            "TE": 3.0,
            "QB": 2.0,
            "D/ST": 1.0,
            "K": 0.0,
        }
    )
    position_priority_weight: float = 0.05
    # Starting-slot + bench depth target used to size roster needs per position.
    bench_depth_targets: Dict[str, int] = field(
        default_factory=lambda: {
            "QB": 1,
            "RB": 3,
            "WR": 3,
            "TE": 1,
            "D/ST": 1,
            "K": 1,
        }
    )
    need_weight: float = 1.0


class DraftOptimizer:
    """Recommends the next best draft pick from ESPN live draft + free agent data."""

    def __init__(self, client: Optional[ESPNClient] = None, config: Optional[DraftOptimizerConfig] = None):
        self.client = client or ESPNClient()
        self.config = config or DraftOptimizerConfig()

    @staticmethod
    def _build_snapshot_from_rows(players: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
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
        return round(weighted, 3)

    @staticmethod
    def _position_counts(players: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for player in players:
            position = str(player.get("position", "UNK")).upper()
            counts[position] = counts.get(position, 0) + 1
        return counts

    def _remaining_needs(
        self,
        drafted_for_team: List[Dict[str, Any]],
        position_slot_counts: Dict[str, int],
    ) -> Dict[str, int]:
        """Compute remaining roster need per position based on starter+bench targets."""
        drafted_counts = self._position_counts(drafted_for_team)
        needs: Dict[str, int] = {}
        for position in self.config.position_priority:
            starters = position_slot_counts.get(position, 0)
            bench = self.config.bench_depth_targets.get(position, 0)
            target = starters + bench
            drafted = drafted_counts.get(position, 0)
            needs[position] = max(0, target - drafted)
        logger.debug("_remaining_needs(): computed needs=%s", needs)
        return needs

    def _draft_value(self, player_row: Dict[str, Any], needs: Dict[str, int]) -> float:
        """Combine base score with position priority and roster-need bonuses."""
        position = str(player_row.get("position", "")).upper()
        base_score = float(player_row.get("score", 0.0))
        priority_bonus = self.config.position_priority.get(position, 0.0) * self.config.position_priority_weight
        need_bonus = self.config.need_weight if needs.get(position, 0) > 0 else 0.0
        return round(base_score + priority_bonus + need_bonus, 3)

    @staticmethod
    def _infer_draft_order(picks: List[Dict[str, Any]], team_count: Optional[int]) -> List[Optional[int]]:
        """Infer the round-1 (draft slot) team order from picks made so far."""
        logger.debug("_infer_draft_order() called: inferring order from %d picks, team_count=%s", len(picks), team_count)
        round_one = sorted(
            (p for p in picks if p.get("round_num") == 1),
            key=lambda p: p.get("round_pick") or 0,
        )
        if not round_one:
            return []

        size = team_count or max((p.get("round_pick") or 0) for p in round_one)
        order: List[Optional[int]] = [None] * size
        for pick in round_one:
            slot = pick.get("round_pick")
            if slot and 1 <= slot <= size:
                order[slot - 1] = pick.get("team_id")
        return order

    @staticmethod
    def _team_on_the_clock(draft_order: List[Optional[int]], overall_pick_number: int) -> Optional[int]:
        """Return the team_id on the clock for a given overall (1-based) snake-draft pick number."""
        team_count = len(draft_order)
        if team_count == 0:
            return None

        round_num = (overall_pick_number - 1) // team_count + 1
        slot_in_round = (overall_pick_number - 1) % team_count
        if round_num % 2 == 0:
            slot_in_round = team_count - 1 - slot_in_round
        return draft_order[slot_in_round]

    @classmethod
    def _picks_until_team_turn(
        cls,
        draft_order: List[Optional[int]],
        next_overall_pick: int,
        team_id: Optional[int],
        max_lookahead: int = 400,
    ) -> Optional[int]:
        """Count picks remaining until the given team is on the clock (0 = your turn now)."""
        if not draft_order or team_id is None:
            return None
        for offset in range(max_lookahead):
            if cls._team_on_the_clock(draft_order, next_overall_pick + offset) == team_id:
                return offset
        logger.debug("_picks_until_team_turn(): team_id=%s not found within lookahead of %d picks", team_id, max_lookahead)
        return None

    def recommend_next_pick(
        self,
        league_id: int,
        year: int,
        team_id: Optional[int] = None,
        team_name: Optional[str] = None,
        draft_slot: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Load draft/roster/free-agent state and recommend the best next pick for the team."""
        logger.info(
            "recommend_next_pick() called: league_id=%s year=%s team_id=%s team_name=%s draft_slot=%s",
            league_id, year, team_id, team_name, draft_slot,
        )
        league = self.client.get_league(league_id=league_id, year=year)
        if league is None:
            logger.warning("recommend_next_pick(): ESPNClient could not connect to league_id=%s year=%s", league_id, year)
            raise ValueError(f"Could not connect to ESPN league {league_id} for year {year}")

        selected_team = self.client.find_team(league=league, team_id=team_id, team_name=team_name)
        if selected_team is None:
            logger.warning("recommend_next_pick(): no teams found in league_id=%s", league_id)
            raise ValueError("No teams found in the provided league")
        selected_team_id = getattr(selected_team, "team_id", None)

        draft_picks = self.client.get_draft_picks(league=league)
        draft_settings = self.client.get_draft_settings(league=league)
        team_count = draft_settings.get("team_count")
        logger.debug("recommend_next_pick(): %d picks made so far, team_count=%s", len(draft_picks), team_count)

        drafted_player_keys: Set[str] = {p["player_key"] for p in draft_picks if p.get("player_key")}
        # `league.draft` picks carry no position data; roster rows do, so use those for needs.
        drafted_for_team = self.client.get_roster_players(league=league, team_id=selected_team_id)

        free_agents = self.client.get_free_agents(league=league, size=self.config.free_agent_sample_size)
        available_players = [p for p in free_agents if p.get("key") not in drafted_player_keys]
        logger.debug("recommend_next_pick(): %d available players after excluding drafted keys", len(available_players))

        current_snapshot = self._build_snapshot_from_rows(available_players)
        prior_snapshot: Dict[str, Dict[str, float]] = {}
        prior_year = year - 1
        if prior_year > 0:
            logger.debug("recommend_next_pick(): fetching prior-year snapshot for year=%s", prior_year)
            prior_snapshot = self.client.get_scoring_snapshot(
                league_id=league_id,
                year=prior_year,
                free_agent_size=self.config.free_agent_sample_size,
            )

        needs = self._remaining_needs(drafted_for_team, draft_settings.get("position_slot_counts", {}))

        for row in drafted_for_team:
            row["score"] = self._score_player(row, {}, prior_snapshot)

        for row in available_players:
            row["score"] = self._score_player(row, current_snapshot, prior_snapshot)
            row["draft_value"] = self._draft_value(row, needs)

        ranked_available = sorted(available_players, key=lambda p: p.get("draft_value", 0.0), reverse=True)
        best_player_available = sorted(available_players, key=lambda p: p.get("score", 0.0), reverse=True)

        draft_order = self._infer_draft_order(draft_picks, team_count)
        if draft_slot and team_count and 1 <= draft_slot <= team_count:
            if not draft_order:
                draft_order = [None] * team_count
            if len(draft_order) >= draft_slot and draft_order[draft_slot - 1] is None:
                draft_order[draft_slot - 1] = selected_team_id

        next_overall_pick = len(draft_picks) + 1
        team_on_clock = self._team_on_the_clock(draft_order, next_overall_pick) if draft_order else None
        picks_until_your_turn = self._picks_until_team_turn(draft_order, next_overall_pick, selected_team_id)
        logger.info(
            "recommend_next_pick(): next_overall_pick=%s team_on_clock=%s picks_until_your_turn=%s recommendations=%d",
            next_overall_pick, team_on_clock, picks_until_your_turn, min(len(ranked_available), self.config.top_recommendations),
        )

        return {
            "league": {
                "league_id": league_id,
                "league_name": getattr(getattr(league, "settings", None), "name", "Unknown League"),
                "season": year,
                "team_count": team_count,
            },
            "team": {
                "team_id": selected_team_id,
                "team_name": getattr(selected_team, "team_name", "Unknown Team"),
            },
            "draft_status": {
                "picks_made": len(draft_picks),
                "next_overall_pick": next_overall_pick,
                "team_on_the_clock": team_on_clock,
                "picks_until_your_turn": picks_until_your_turn,
                "draft_order_known": bool(draft_order) and any(slot is not None for slot in draft_order),
            },
            "roster_needs": needs,
            "current_roster": sorted(drafted_for_team, key=lambda p: (p.get("position", ""), -float(p.get("score", 0.0)))),
            "recommendations": ranked_available[: self.config.top_recommendations],
            "best_player_available": best_player_available[: self.config.top_recommendations],
        }
