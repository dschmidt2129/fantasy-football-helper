# fantasy-football-helper

Desktop + API helper for ESPN fantasy football private leagues.

The app connects to your private league, loads your roster, checks free agency, and suggests add/drop improvements using weighted historical scoring from:
- current season points per game
- previous season points per game

## What is included

- FastAPI backend in [backend/main.py](backend/main.py)
- ESPN data client in [backend/services/espn_client.py](backend/services/espn_client.py)
- Roster optimizer in [backend/services/optimizer.py](backend/services/optimizer.py)
- Desktop UI (tkinter) in [frontend/desktop_app.py](frontend/desktop_app.py)

## Setup

1. Create a virtual environment:

```bash
python -m venv .venv
```

2. Activate the virtual environment:

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```bat
.venv\Scripts\activate.bat
```

macOS/Linux:

```bash
source .venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Configure environment variables in `.env`:
- `SWID`
- `ESPN_S2`
- `DATABASE_URL` (optional; defaults to SQLite file in `data/`)

5. Configure UI dropdown values in [frontend/ui_config.json](frontend/ui_config.json):

```json
{
	"default_league_id": 123456,
	"default_year": 2026,
	"default_team_id": 1,
	"leagues": [
		{
			"league_id": 123456,
			"years": [2024, 2025, 2026],
			"default_year": 2026,
			"default_team_id": 1,
			"teams": [
				{ "team_id": 1, "team_name": "My Team" },
				{ "team_id": 2, "team_name": "Other Team" }
			]
		}
	]
}
```

`SWID` and `ESPN_S2` are required for private leagues and come from your ESPN browser cookies.

## Run backend API

```bash
uvicorn backend.main:app --reload
```

Base URL: `http://127.0.0.1:8000`

Useful endpoints:
- `GET /api/health`
- `GET /api/leagues/{league_id}/teams?year=2026`
- `GET /api/leagues/{league_id}/analysis?year=2026&team_id=1`
- `GET /api/leagues/{league_id}/analysis?year=2026&team_name=My Team`

## Run desktop app

```bash
python frontend/desktop_app.py
```

In the UI:
1. Select `League ID`, `Season Year`, and `Team ID` from dropdowns.
2. Dropdown values come from [frontend/ui_config.json](frontend/ui_config.json).
3. Click `Analyze Roster`.

The app displays:
- your roster with points per game and weighted score
- recommended add/drop moves
- score delta for each recommendation

## Recommendation logic

For each player, the optimizer computes:

`score = 0.65 * current_season_ppg + 0.35 * prior_season_ppg`

Then it:
1. Groups players by position.
2. Finds the weakest roster player at each position.
3. Compares top free agents at that position.
4. Returns suggestions where improvement is above threshold.

## Notes

- If the selected league has no teams configured, analysis will run without a team override.
- Previous season data is best-effort and depends on ESPN data availability for that league.
- The app currently focuses on add/drop suggestions; trade logic is not included yet.

## References

- https://pypi.org/project/espn-api/
- https://github.com/cwendt94/espn-api/wiki