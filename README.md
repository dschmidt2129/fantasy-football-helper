# fantasy-football-helper

Desktop + API helper for ESPN fantasy football private leagues.

The app connects to your private league, loads your roster, checks free agency, and suggests add/drop improvements using weighted historical scoring from:
- current season points per game
- previous season points per game

During a live snake draft, it can also recommend your next pick using positional priority, roster needs, and the same weighted scoring model.

## What is included

- FastAPI backend in [backend/main.py](backend/main.py)
- ESPN data client in [backend/services/espn_client.py](backend/services/espn_client.py)
- Roster optimizer in [backend/services/optimizer.py](backend/services/optimizer.py)
- Draft optimizer in [backend/services/draft_optimizer.py](backend/services/draft_optimizer.py)
- React UI in [frontend/react-app](frontend/react-app)

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
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Base URL: `http://127.0.0.1:8000`

For local React development, CORS defaults to:
- `http://127.0.0.1:5173`
- `http://localhost:5173`

Override allowed frontend origins with `FRONTEND_ORIGINS` (comma-separated).

Useful endpoints:
- `GET /api/health`
- `GET /api/leagues/{league_id}/teams?year=2026`
- `GET /api/leagues/{league_id}/analysis?year=2026&team_id=1`
- `GET /api/leagues/{league_id}/analysis?year=2026&team_name=My Team`
- `GET /api/leagues/{league_id}/draft-recommendations?year=2026&team_id=1`
- `GET /api/leagues/{league_id}/draft-recommendations?year=2026&team_id=1&draft_slot=3` (use `draft_slot` before round 1 has finished, when the snake draft order can't be inferred yet)

## Run React app

```bash
cd frontend/react-app
npm install
npm run dev
```

React app URL: `http://127.0.0.1:5173`

In the UI:
1. Select `League ID`, `Season Year`, and `Team ID` from dropdowns.
2. Dropdown values are loaded from backend endpoint `GET /api/ui-config`.
3. Use the **Roster Optimizer** tab to click `Analyze Roster`, or the **Draft Optimizer** tab to click `Get Draft Recommendations`.

The **Roster Optimizer** tab displays:
- your roster with points per game and weighted score
- recommended add/drop moves
- score delta for each recommendation

The **Draft Optimizer** tab displays:
- draft status (picks made, next overall pick, picks until your turn)
- your current drafted roster
- suggested next picks, ranked by weighted score, positional priority (RB > WR > TE > QB > D/ST > K), and remaining roster needs

If round 1 of the draft hasn't finished yet, the snake draft order can't be inferred from picks made so far — enter your `Draft Slot` in the Draft Optimizer tab as a fallback.

## Recommendation logic

For each player, the optimizer computes:

`score = 0.65 * current_season_ppg + 0.35 * prior_season_ppg`

Then it:
1. Groups players by position.
2. Finds the weakest roster player at each position.
3. Compares top free agents at that position.
4. Returns suggestions where improvement is above threshold.

## Draft recommendation logic

During a live snake draft, the draft optimizer:
1. Reads picks made so far from ESPN's live draft feed and excludes already-drafted players from consideration.
2. Computes your remaining roster needs per position from your current roster vs. starting lineup slots + bench depth targets.
3. Scores each available player with the same weighted current/prior-season formula, plus a positional priority bonus (RB > WR > TE > QB > D/ST > K) and a bonus for positions you still need.
4. Infers the snake draft order from round-1 picks to estimate whose turn it is and how many picks remain until yours (or accepts a manual `draft_slot` override before round 1 finishes).

**Note**: this relies on ESPN's `league.draft` data reflecting picks made in near real time during an in-progress draft. This has not yet been validated against a live ESPN draft — if picks don't appear until the draft fully completes, recommendations will be based on stale data until then.

## Notes

- If the selected league has no teams configured, analysis will run without a team override.
- Previous season data is best-effort and depends on ESPN data availability for that league.
- The app currently focuses on add/drop suggestions; trade logic is not included yet.
- If needed, set `VITE_API_BASE_URL` in `frontend/react-app/.env` to point React at a different API host.

## References

- https://pypi.org/project/espn-api/
- https://github.com/cwendt94/espn-api/wiki