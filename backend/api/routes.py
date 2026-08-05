from fastapi import APIRouter, Depends, HTTPException, Query
from backend.services.espn_client import ESPNClient
from backend.services.optimizer import RosterOptimizer
from pathlib import Path
import asyncio
import json
import os

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


@router.get("/api/health")
async def api_health():
    """Health check endpoint"""
    return {"status": "healthy"}


@router.get("/api/ui-config")
async def get_ui_config():
    """Return frontend config used for league/year/team dropdowns."""
    if not UI_CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Missing config file: {UI_CONFIG_PATH}")

    try:
        with UI_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid ui_config.json: {exc}") from exc

    if not isinstance(config, dict):
        raise HTTPException(status_code=500, detail="ui_config.json must contain a JSON object")

    return config


@router.get("/api/leagues/{league_id}/teams")
async def get_league_teams(
    league_id: int,
    year: int = Query(..., ge=2015),
    client: ESPNClient = Depends(get_espn_client),
):
    """List teams in a league season to help the user select their roster."""
    league = client.get_league(league_id=league_id, year=year)
    if league is None:
        raise HTTPException(status_code=404, detail="Could not connect to league with the provided credentials")

    return {
        "league_id": league_id,
        "year": year,
        "teams": client.get_teams(league),
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
    try:
        async with analysis_semaphore:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    optimizer.analyze_league,
                    league_id=league_id,
                    year=year,
                    team_id=team_id,
                    team_name=team_name,
                ),
                timeout=ANALYSIS_TIMEOUT_SECONDS,
            )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                "Analysis timed out while loading ESPN data. "
                "Please retry or reduce free-agent sample size."
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected analysis failure: {exc}") from exc
