from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.services.espn_client import ESPNClient


@dataclass
class RecommendationConfig:
    free_agent_sample_size: int = 60
    top_free_agents_per_position: int = 12
    top_recommendations: int = 10
    min_score_improvement: float = 0.75
    current_year_weight: float = 0.65
    prior_year_weight: float = 0.35


class RosterOptimizer:
    """Computes roster upgrade suggestions from ESPN league data."""

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
        key = player_row.get("key")
        current_ppg = float(player_row.get("points_per_game", 0.0))

        if key in current_snapshot:
            current_ppg = float(current_snapshot[key].get("points_per_game", current_ppg))

        prior_ppg = float(prior_snapshot.get(key, {}).get("points_per_game", 0.0))

        weighted = (
            self.config.current_year_weight * current_ppg
            + self.config.prior_year_weight * prior_ppg
        )
        return round(weighted, 3)

    @staticmethod
    def _by_position(players: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for player in players:
            position = player.get("position", "UNK")
            grouped.setdefault(position, []).append(player)
        return grouped

    def analyze_league(
        self,
        league_id: int,
        year: int,
        team_id: Optional[int] = None,
        team_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        league = self.client.get_league(league_id=league_id, year=year)
        if league is None:
            raise ValueError(f"Could not connect to ESPN league {league_id} for year {year}")

        selected_team = self.client.find_team(league=league, team_id=team_id, team_name=team_name)
        if selected_team is None:
            raise ValueError("No teams found in the provided league")

        roster_players = self.client.get_roster_players(
            league=league,
            team_id=getattr(selected_team, "team_id", None),
        )

        free_agents = self.client.get_free_agents(
            league=league,
            size=self.config.free_agent_sample_size,
        )

        current_snapshot = self.client.get_scoring_snapshot(
            league_id=league_id,
            year=year,
            free_agent_size=self.config.free_agent_sample_size,
        )

        prior_snapshot: Dict[str, Dict[str, float]] = {}
        prior_year = year - 1
        if prior_year > 0:
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

            # Compare against the weakest same-position roster player.
            drop_candidate = sorted(candidates, key=lambda p: p.get("score", 0.0))[0]

            top_free_agents = sorted(
                free_agent_list,
                key=lambda p: p.get("score", 0.0),
                reverse=True,
            )[: self.config.top_free_agents_per_position]

            for add_candidate in top_free_agents:
                improvement = float(add_candidate.get("score", 0.0)) - float(drop_candidate.get("score", 0.0))
                if improvement < self.config.min_score_improvement:
                    continue

                recommendations.append(
                    {
                        "position": position,
                        "add": add_candidate,
                        "drop": drop_candidate,
                        "score_delta": round(improvement, 3),
                        "reason": (
                            "Weighted score uses this season performance and previous year "
                            "as historical baseline."
                        ),
                    }
                )

        recommendations.sort(key=lambda item: item.get("score_delta", 0.0), reverse=True)
        recommendations = recommendations[: self.config.top_recommendations]

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
                "formula": "score = current_year_weight * current_ppg + prior_year_weight * prior_year_ppg",
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
