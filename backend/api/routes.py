from fastapi import APIRouter, Depends, HTTPException, Query
from backend.services.espn_client import ESPNClient
from backend.services.optimizer import RosterOptimizer
from backend.services.draft_optimizer import DraftOptimizer
from pathlib import Path
import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)
router = APIRouter()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
UI_CONFIG_PATH = PROJECT_ROOT / "frontend" / "ui_config.json"
ANALYSIS_TIMEOUT_SECONDS = float(os.getenv("ANALYSIS_TIMEOUT_SECONDS", "45"))
ANALYSIS_MAX_CONCURRENT = max(1, int(os.getenv("ANALYSIS_MAX_CONCURRENT", "1")))
analysis_semaphore = asyncio.Semaphore(ANALYSIS_MAX_CONCURRENT)


def get_espn_client():
    return ESPNClient()


def get_optimizer(client: ESPNClient = Depends(get_espn_client)):
    return RosterOptimizer(client=client)


def get_draft_optimizer(client: ESPNClient = Depends(get_espn_client)):
    return DraftOptimizer(client=client)


@router.get("/api/health")
async def api_health():
    """Health check endpoint"""
    logger.debug("api_health() called: frontend/monitoring probe hit /api/health")
    return {"status": "healthy"}


@router.get("/api/ui-config")
async def get_ui_config():
    """Return frontend config used for league/year/team dropdowns."""
    logger.info("get_ui_config() called: loading UI config from %s", UI_CONFIG_PATH)
    if not UI_CONFIG_PATH.exists():
        logger.error("get_ui_config(): config file missing at %s", UI_CONFIG_PATH)
        raise HTTPException(status_code=404, detail=f"Missing config file: {UI_CONFIG_PATH}")

    try:
        with UI_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except json.JSONDecodeError as exc:
        logger.error("get_ui_config(): failed to parse %s: %s", UI_CONFIG_PATH, exc)
        raise HTTPException(status_code=500, detail=f"Invalid ui_config.json: {exc}") from exc

    if not isinstance(config, dict):
        logger.error("get_ui_config(): config root is not a JSON object")
        raise HTTPException(status_code=500, detail="ui_config.json must contain a JSON object")

    logger.debug("get_ui_config(): successfully loaded config with keys=%s", list(config.keys()))
    return config


@router.get("/api/leagues/{league_id}/teams")
async def get_league_teams(
    league_id: int,
    year: int = Query(..., ge=2015),
    client: ESPNClient = Depends(get_espn_client),
):
    """List teams in a league season to help the user select their roster."""
    logger.info("get_league_teams() called: league_id=%s year=%s (from GET /api/leagues/{league_id}/teams)", league_id, year)
    league = client.get_league(league_id=league_id, year=year)
    if league is None:
        logger.warning("get_league_teams(): ESPNClient could not connect to league_id=%s year=%s", league_id, year)
        raise HTTPException(status_code=404, detail="Could not connect to league with the provided credentials")

    teams = client.get_teams(league)
    logger.info("get_league_teams(): returning %d teams for league_id=%s year=%s", len(teams), league_id, year)
    return {
        "league_id": league_id,
        "year": year,
        "teams": teams,
    }


@router.get("/api/leagues/{league_id}/analysis")
async def analyze_roster(
    league_id: int,
    year: int = Query(..., ge=2015),
    team_id: int | None = Query(default=None),
    team_name: str | None = Query(default=None),
    optimizer: RosterOptimizer = Depends(get_optimizer),
):
    """
    Analyze a team roster against free agency and return upgrade recommendations.
    Scoring uses weighted current-season + prior-year points per game.
    """
    logger.info(
        "analyze_roster() called: league_id=%s year=%s team_id=%s team_name=%s (from GET /api/leagues/{league_id}/analysis)",
        league_id, year, team_id, team_name,
    )
    try:
        async with analysis_semaphore:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    optimizer.analyze_league,
                    league_id=league_id,
                    year=year,
                    team_id=team_id,
                    team_name=team_name,
                ),
                timeout=ANALYSIS_TIMEOUT_SECONDS,
            )
        logger.info("analyze_roster(): analysis completed for league_id=%s year=%s", league_id, year)
        return result
    except asyncio.TimeoutError as exc:
        logger.error("analyze_roster(): timed out after %ss for league_id=%s year=%s", ANALYSIS_TIMEOUT_SECONDS, league_id, year)
        raise HTTPException(
            status_code=504,
            detail=(
                "Analysis timed out while loading ESPN data. "
                "Please retry or reduce free-agent sample size."
            ),
        ) from exc
    except ValueError as exc:
        logger.warning("analyze_roster(): invalid request for league_id=%s year=%s: %s", league_id, year, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("analyze_roster(): unexpected failure for league_id=%s year=%s", league_id, year)
        raise HTTPException(status_code=500, detail=f"Unexpected analysis failure: {exc}") from exc


@router.get("/api/leagues/{league_id}/draft-recommendations")
async def draft_recommendations(
    league_id: int,
    year: int = Query(..., ge=2015),
    team_id: int | None = Query(default=None),
    team_name: str | None = Query(default=None),
    draft_slot: int | None = Query(default=None, ge=1),
    draft_optimizer: DraftOptimizer = Depends(get_draft_optimizer),
):
    """
    Recommend the next best draft pick during a live snake draft, using
    positional priority, roster needs, and weighted current+prior season scoring.
    """
    logger.info(
        "draft_recommendations() called: league_id=%s year=%s team_id=%s team_name=%s draft_slot=%s "
        "(from GET /api/leagues/{league_id}/draft-recommendations)",
        league_id, year, team_id, team_name, draft_slot,
    )
    try:
        async with analysis_semaphore:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    draft_optimizer.recommend_next_pick,
                    league_id=league_id,
                    year=year,
                    team_id=team_id,
                    team_name=team_name,
                    draft_slot=draft_slot,
                ),
                timeout=ANALYSIS_TIMEOUT_SECONDS,
            )
        logger.info("draft_recommendations(): recommendation completed for league_id=%s year=%s", league_id, year)
        return result
    except asyncio.TimeoutError as exc:
        logger.error("draft_recommendations(): timed out after %ss for league_id=%s year=%s", ANALYSIS_TIMEOUT_SECONDS, league_id, year)
        raise HTTPException(
            status_code=504,
            detail=(
                "Draft recommendation timed out while loading ESPN data. "
                "Please retry or reduce free-agent sample size."
            ),
        ) from exc
    except ValueError as exc:
        logger.warning("draft_recommendations(): invalid request for league_id=%s year=%s: %s", league_id, year, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("draft_recommendations(): unexpected failure for league_id=%s year=%s", league_id, year)
        raise HTTPException(status_code=500, detail=f"Unexpected draft recommendation failure: {exc}") from exc
