from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.services.espn_client import ESPNClient

router = APIRouter()

def get_espn_client():
    return ESPNClient()

@router.get("/api/health")
async def api_health():
    """Health check endpoint"""
    return {"status": "healthy"}

@router.get("/api/espn/test")
async def test_espn_connection(client: ESPNClient = Depends(get_espn_client)):
    """Test ESPN API connection"""
    # Placeholder: Test with a sample league
    result = client.get_player_stats(league_id=123456, year=2025)
    return {"test": "ESPN connection test endpoint", "data": result}
