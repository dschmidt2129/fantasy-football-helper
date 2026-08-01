from fastapi import APIRouter, Depends, HTTPException, Query
from backend.services.espn_client import ESPNClient
from backend.services.optimizer import RosterOptimizer

router = APIRouter()


def get_espn_client():
    return ESPNClient()


def get_optimizer(client: ESPNClient = Depends(get_espn_client)):
    return RosterOptimizer(client=client)


@router.get("/api/health")
async def api_health():
    """Health check endpoint"""
    return {"status": "healthy"}


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
        return optimizer.analyze_league(
            league_id=league_id,
            year=year,
            team_id=team_id,
            team_name=team_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected analysis failure: {exc}") from exc
