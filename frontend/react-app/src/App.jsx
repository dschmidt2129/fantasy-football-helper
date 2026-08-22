import { useEffect, useMemo, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function buildLeagueMap(config) {
  const map = {};
  const leagues = Array.isArray(config?.leagues) ? config.leagues : [];

  for (const league of leagues) {
    const leagueIdValue = league?.league_id;
    const leagueIds = Array.isArray(leagueIdValue) ? leagueIdValue : [leagueIdValue];

    for (const rawId of leagueIds) {
      const leagueId = String(rawId ?? "").trim();
      if (!leagueId) {
        continue;
      }

      map[leagueId] = {
        ...league,
        league_id: /^\d+$/.test(leagueId) ? Number(leagueId) : leagueId,
      };
    }
  }

  return map;
}

function leagueLabel(leagueId, leagueEntry = {}, globalLabels = {}) {
  const prefix = String(
    leagueEntry.league_label ||
      leagueEntry.league_name ||
      globalLabels[String(leagueId)] ||
      ""
  ).trim();
  return prefix ? `${leagueId} | ${prefix}` : String(leagueId);
}

function formatNumber(value, digits = 2) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "0.00";
}

const IR_STATUSES = new Set(["IR", "INJURY_RESERVE", "INJURED_RESERVE"]);

function normalizePosition(position) {
  const normalized = String(position || "").toUpperCase().trim();
  if (normalized === "DST") {
    return "D/ST";
  }
  return normalized;
}

function isIrStatus(status) {
  return IR_STATUSES.has(String(status || "").toUpperCase().trim());
}

function normalizeLineupSlot(slot) {
  const normalized = String(slot || "").toUpperCase().trim();
  if (!normalized) {
    return "";
  }
  if (normalized === "BE") {
    return "Bench";
  }
  if (normalized === "IR") {
    return "IR";
  }
  if (normalized === "RB/WR/TE" || normalized === "RB/WR" || normalized === "WR/TE") {
    return "FLEX";
  }
  return normalizePosition(normalized);
}

function comparePlayers(a, b) {
  const scoreDelta = Number(b.player?.score || 0) - Number(a.player?.score || 0);
  if (scoreDelta !== 0) {
    return scoreDelta;
  }

  const ppgDelta = Number(b.player?.points_per_game || 0) - Number(a.player?.points_per_game || 0);
  if (ppgDelta !== 0) {
    return ppgDelta;
  }

  const nameA = String(a.player?.name || "");
  const nameB = String(b.player?.name || "");
  const nameCompare = nameA.localeCompare(nameB);
  if (nameCompare !== 0) {
    return nameCompare;
  }

  return a.originalIndex - b.originalIndex;
}

function buildSortedRoster(players) {
  const indexedPlayers = Array.isArray(players)
    ? players.map((player, originalIndex) => ({
        player,
        originalIndex,
        position: normalizePosition(player?.position),
        lineupSlot: normalizeLineupSlot(player?.lineup_slot),
        isIr: isIrStatus(player?.status),
      }))
    : [];

  const hasExplicitSlots = indexedPlayers.some((item) => item.lineupSlot);
  if (hasExplicitSlots) {
    const slotRank = {
      QB: 0,
      RB: 1,
      WR: 2,
      TE: 3,
      FLEX: 4,
      "D/ST": 5,
      K: 6,
      Bench: 7,
      IR: 8,
    };

    const mapped = indexedPlayers.map((item) => {
      const slot = item.lineupSlot || (item.isIr ? "IR" : "Bench");
      const rosterLine = slot === "Bench" ? "Bench" : slot === "IR" ? "IR" : "Active";
      return {
        ...item.player,
        roster_line: rosterLine,
        roster_slot: slot,
        _rank: slotRank[slot] ?? 7,
        _originalIndex: item.originalIndex,
      };
    });

    mapped.sort((a, b) => {
      if (a._rank !== b._rank) {
        return a._rank - b._rank;
      }

      const scoreDelta = Number(b.score || 0) - Number(a.score || 0);
      if (scoreDelta !== 0) {
        return scoreDelta;
      }

      const ppgDelta = Number(b.points_per_game || 0) - Number(a.points_per_game || 0);
      if (ppgDelta !== 0) {
        return ppgDelta;
      }

      const nameCompare = String(a.name || "").localeCompare(String(b.name || ""));
      if (nameCompare !== 0) {
        return nameCompare;
      }

      return Number(a._originalIndex || 0) - Number(b._originalIndex || 0);
    });

    return mapped.map(({ _rank, _originalIndex, ...playerRow }) => playerRow);
  }

  const activePlayers = indexedPlayers.filter((item) => !item.isIr);
  const irPlayers = indexedPlayers.filter((item) => item.isIr).sort(comparePlayers);

  const buckets = new Map();
  for (const item of activePlayers) {
    if (!buckets.has(item.position)) {
      buckets.set(item.position, []);
    }
    buckets.get(item.position).push(item);
  }

  for (const bucket of buckets.values()) {
    bucket.sort(comparePlayers);
  }

  const takeBestFromPositions = (positions) => {
    let bestItem = null;

    for (const position of positions) {
      const bucket = buckets.get(position) || [];
      const candidate = bucket[0];
      if (!candidate) {
        continue;
      }
      if (!bestItem || comparePlayers(candidate, bestItem) < 0) {
        bestItem = candidate;
      }
    }

    if (!bestItem) {
      return null;
    }

    const sourceBucket = buckets.get(bestItem.position) || [];
    const sourceIndex = sourceBucket.findIndex((item) => item.originalIndex === bestItem.originalIndex);
    if (sourceIndex >= 0) {
      sourceBucket.splice(sourceIndex, 1);
    }

    return bestItem;
  };

  const starterSlots = [
    { slot: "QB", eligible: ["QB"] },
    { slot: "RB", eligible: ["RB"] },
    { slot: "RB", eligible: ["RB"] },
    { slot: "WR", eligible: ["WR"] },
    { slot: "WR", eligible: ["WR"] },
    { slot: "TE", eligible: ["TE"] },
    { slot: "FLEX", eligible: ["RB", "WR", "TE"] },
    { slot: "FLEX", eligible: ["RB", "WR", "TE"] },
    { slot: "D/ST", eligible: ["D/ST"] },
    { slot: "K", eligible: ["K"] },
  ];

  const starterRows = [];
  for (const slotConfig of starterSlots) {
    const picked = takeBestFromPositions(slotConfig.eligible);
    if (!picked) {
      continue;
    }
    starterRows.push({
      ...picked.player,
      roster_line: "Active",
      roster_slot: slotConfig.slot,
    });
  }

  const benchPositionOrder = ["QB", "RB", "WR", "TE", "D/ST", "K"];
  const bench = [];

  for (const position of benchPositionOrder) {
    const bucket = buckets.get(position) || [];
    bench.push(...bucket);
    buckets.delete(position);
  }

  for (const [_, bucket] of buckets.entries()) {
    bench.push(...bucket);
  }

  bench.sort((a, b) => {
    const posA = normalizePosition(a.player?.position);
    const posB = normalizePosition(b.player?.position);
    const idxA = benchPositionOrder.indexOf(posA);
    const idxB = benchPositionOrder.indexOf(posB);
    const orderA = idxA >= 0 ? idxA : benchPositionOrder.length;
    const orderB = idxB >= 0 ? idxB : benchPositionOrder.length;
    if (orderA !== orderB) {
      return orderA - orderB;
    }
    return comparePlayers(a, b);
  });

  const benchRows = bench.map((item) => ({
    ...item.player,
    roster_line: "Bench",
    roster_slot: "Bench",
  }));
  const irRows = irPlayers.map((item) => ({
    ...item.player,
    roster_line: "IR",
    roster_slot: "IR",
  }));

  return [...starterRows, ...benchRows, ...irRows];
}

export default function App() {
  const [uiConfig, setUiConfig] = useState(null);
  const [leagueMap, setLeagueMap] = useState({});

  const [leagueId, setLeagueId] = useState("");
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [teamId, setTeamId] = useState("");

  const [roster, setRoster] = useState([]);
  const [recommendations, setRecommendations] = useState([]);

  const [status, setStatus] = useState("Loading UI configuration...");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState("");

  const [activeTab, setActiveTab] = useState("roster");
  const [draftSlot, setDraftSlot] = useState("");
  const [draftedRoster, setDraftedRoster] = useState([]);
  const [draftRecommendations, setDraftRecommendations] = useState([]);
  const [draftMeta, setDraftMeta] = useState(null);

  const [draftStatus, setDraftStatus] = useState("Run draft recommendations to see suggestions.");
  const [isDrafting, setIsDrafting] = useState(false);
  const [draftError, setDraftError] = useState("");

  useEffect(() => {
    let isMounted = true;

    async function loadConfig() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/ui-config`);
        if (!response.ok) {
          throw new Error(`Failed to load UI config: ${response.status}`);
        }

        const config = await response.json();
        if (!config || !Array.isArray(config.leagues) || config.leagues.length === 0) {
          throw new Error("Backend UI config is missing a non-empty leagues array.");
        }

        const nextLeagueMap = buildLeagueMap(config);
        const leagueIds = Object.keys(nextLeagueMap);
        if (leagueIds.length === 0) {
          throw new Error("No valid league entries found in UI config.");
        }

        const defaultLeagueId = String(config.default_league_id ?? "").trim();
        const resolvedLeagueId = leagueIds.includes(defaultLeagueId) ? defaultLeagueId : leagueIds[0];

        const selectedLeague = nextLeagueMap[resolvedLeagueId] || {};
        const years = Array.isArray(selectedLeague.years)
          ? selectedLeague.years.map((item) => String(item))
          : [String(new Date().getFullYear())];

        const defaultYear = String(
          selectedLeague.default_year ?? config.default_year ?? ""
        ).trim();
        const resolvedYear = years.includes(defaultYear) ? defaultYear : years[0];

        const teams = Array.isArray(selectedLeague.teams) ? selectedLeague.teams : [];
        const teamIds = teams
          .map((team) => String(team?.team_id ?? "").trim())
          .filter(Boolean);

        const defaultTeamId = String(
          selectedLeague.default_team_id ?? config.default_team_id ?? ""
        ).trim();
        const resolvedTeamId = teamIds.includes(defaultTeamId)
          ? defaultTeamId
          : teamIds[0] || "";

        if (!isMounted) {
          return;
        }

        setUiConfig(config);
        setLeagueMap(nextLeagueMap);
        setLeagueId(resolvedLeagueId);
        setYear(resolvedYear);
        setTeamId(resolvedTeamId);
        setStatus("Select league values and run analysis.");
      } catch (loadError) {
        if (!isMounted) {
          return;
        }
        setError(loadError.message || "Failed to load config.");
        setStatus("Unable to load configuration.");
      }
    }

    loadConfig();

    return () => {
      isMounted = false;
    };
  }, []);

  const leagueOptions = useMemo(() => {
    const labels = uiConfig?.league_labels || {};
    return Object.keys(leagueMap).map((id) => ({
      value: id,
      label: leagueLabel(id, leagueMap[id], labels),
    }));
  }, [leagueMap, uiConfig]);

  const selectedLeague = leagueMap[leagueId] || {};

  const yearOptions = useMemo(() => {
    const years = Array.isArray(selectedLeague.years)
      ? selectedLeague.years.map((value) => String(value))
      : [];
    return years.length ? years : [String(new Date().getFullYear())];
  }, [selectedLeague]);

  const teamOptions = useMemo(() => {
    const teams = Array.isArray(selectedLeague.teams) ? selectedLeague.teams : [];
    return teams
      .map((team) => {
        const id = String(team?.team_id ?? "").trim();
        const name = String(team?.team_name ?? "").trim();
        if (!id) {
          return null;
        }
        return {
          value: id,
          label: name ? `${id} | ${name}` : id,
        };
      })
      .filter(Boolean);
  }, [selectedLeague]);

  const sortedRoster = useMemo(() => buildSortedRoster(roster), [roster]);

  useEffect(() => {
    if (!leagueId) {
      return;
    }

    if (!yearOptions.includes(year)) {
      setYear(yearOptions[0]);
    }

    const teamIds = teamOptions.map((option) => option.value);
    if (!teamIds.includes(teamId)) {
      setTeamId(teamIds[0] || "");
    }
  }, [leagueId, yearOptions, teamOptions, year, teamId]);

  async function handleAnalyze() {
    setError("");

    if (!leagueId) {
      setError("League ID is required.");
      return;
    }

    if (!year) {
      setError("Season year is required.");
      return;
    }

    const query = new URLSearchParams({ year: String(year) });
    if (teamId) {
      query.set("team_id", String(teamId));
    }

    setIsAnalyzing(true);
    setStatus("Connecting to ESPN and analyzing players...");

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/leagues/${encodeURIComponent(leagueId)}/analysis?${query.toString()}`
      );

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.detail || `Analysis failed with status ${response.status}`);
      }

      setRoster(Array.isArray(payload.roster) ? payload.roster : []);
      setRecommendations(Array.isArray(payload.recommendations) ? payload.recommendations : []);

      const recommendationCount = Number(payload?.summary?.recommendation_count || 0);
      const teamName = payload?.team?.team_name || "team";
      setStatus(`Analyzed ${teamName}: ${recommendationCount} suggested moves`);
    } catch (analysisError) {
      setError(analysisError.message || "Analysis failed.");
      setStatus("Analysis failed.");
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function handleDraftRecommend() {
    setDraftError("");

    if (!leagueId) {
      setDraftError("League ID is required.");
      return;
    }

    if (!year) {
      setDraftError("Season year is required.");
      return;
    }

    const query = new URLSearchParams({ year: String(year) });
    if (teamId) {
      query.set("team_id", String(teamId));
    }
    if (draftSlot) {
      query.set("draft_slot", String(draftSlot));
    }

    setIsDrafting(true);
    setDraftStatus("Connecting to ESPN and checking the live draft...");

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/leagues/${encodeURIComponent(leagueId)}/draft-recommendations?${query.toString()}`
      );

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.detail || `Draft recommendation failed with status ${response.status}`);
      }

      setDraftedRoster(Array.isArray(payload.current_roster) ? payload.current_roster : []);
      setDraftRecommendations(Array.isArray(payload.recommendations) ? payload.recommendations : []);
      setDraftMeta(payload.draft_status || null);

      const picksMade = Number(payload?.draft_status?.picks_made || 0);
      const teamName = payload?.team?.team_name || "team";
      setDraftStatus(`${teamName}: ${picksMade} picks made so far in the draft.`);
    } catch (draftRecommendError) {
      setDraftError(draftRecommendError.message || "Draft recommendation failed.");
      setDraftStatus("Draft recommendation failed.");
    } finally {
      setIsDrafting(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <p className="kicker">fantasy-football-helper</p>
        <h1>Roster Optimizer</h1>
        <p className="subtitle">
          Analyze your ESPN roster against current free agency and get weighted add/drop recommendations.
        </p>
      </header>

      <nav className="tab-bar">
        <button
          type="button"
          className={activeTab === "roster" ? "tab tab-active" : "tab"}
          onClick={() => setActiveTab("roster")}
        >
          Roster Optimizer
        </button>
        <button
          type="button"
          className={activeTab === "draft" ? "tab tab-active" : "tab"}
          onClick={() => setActiveTab("draft")}
        >
          Draft Optimizer
        </button>
      </nav>

      <section className="panel controls-panel">
        <div className="control-grid">
          <label>
            <span>League ID</span>
            <select value={leagueId} onChange={(event) => setLeagueId(event.target.value)}>
              {leagueOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Season Year</span>
            <select value={year} onChange={(event) => setYear(event.target.value)}>
              {yearOptions.map((yearOption) => (
                <option key={yearOption} value={yearOption}>
                  {yearOption}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Team ID</span>
            <select value={teamId} onChange={(event) => setTeamId(event.target.value)}>
              {teamOptions.length === 0 && <option value="">No configured teams</option>}
              {teamOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          {activeTab === "draft" ? (
            <label>
              <span>Draft Slot (if round 1 incomplete)</span>
              <input
                type="number"
                min="1"
                value={draftSlot}
                onChange={(event) => setDraftSlot(event.target.value)}
                placeholder="Optional"
              />
            </label>
          ) : null}

          {activeTab === "roster" ? (
            <button type="button" onClick={handleAnalyze} disabled={isAnalyzing}>
              {isAnalyzing ? "Analyzing..." : "Analyze Roster"}
            </button>
          ) : (
            <button type="button" onClick={handleDraftRecommend} disabled={isDrafting}>
              {isDrafting ? "Checking Draft..." : "Get Draft Recommendations"}
            </button>
          )}
        </div>

        {activeTab === "roster" ? (
          <>
            <p className="status-text">{status}</p>
            {error ? <p className="error-text">{error}</p> : null}
          </>
        ) : (
          <>
            <p className="status-text">{draftStatus}</p>
            {draftError ? <p className="error-text">{draftError}</p> : null}
          </>
        )}
      </section>

      {activeTab === "roster" ? (
        <>
          <section className="panel table-panel">
            <h2>Roster</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Slot</th>
                    <th>Player</th>
                    <th>Pos</th>
                    <th>NFL</th>
                    <th>Total Season Points</th>
                    <th>PPG</th>
                    <th>Weighted Score</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRoster.length === 0 ? (
                    <tr>
                        <td colSpan={7} className="empty-cell">
                        Run analysis to view roster data.
                      </td>
                    </tr>
                  ) : (
                    sortedRoster.map((player, index) => (
                      <tr key={`${player.name || "player"}-${index}`}>
                        <td>{player.roster_slot || ""}</td>
                        <td>{player.name || ""}</td>
                        <td>{player.position || ""}</td>
                        <td>{player.pro_team || ""}</td>
                        <td>{formatNumber(player.total_points)}</td>
                        <td>{formatNumber(player.points_per_game)}</td>
                        <td>{formatNumber(player.score)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel table-panel">
            <h2>Recommended Add / Drop Moves</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Pos</th>
                    <th>Add</th>
                    <th>Add Total Season Points</th>
                    <th>PPG</th>
                    <th>Drop</th>
                    <th>Drop Total Season Points</th>
                    <th>Score Delta</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {recommendations.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="empty-cell">
                        No recommendations yet.
                      </td>
                    </tr>
                  ) : (
                    recommendations.map((rec, index) => {
                      const addName = rec?.add?.name || "";
                      const addTotalPoints = Number(rec?.add?.total_points || 0);
                      const addPpg = Number(rec?.add?.points_per_game || 0);
                      const dropName = rec?.drop?.name || "";
                      const dropTotalPoints = Number(rec?.drop?.total_points || 0);
                      const delta = Number(rec?.score_delta || 0);

                      return (
                        <tr key={`${rec.position || "pos"}-${index}`}>
                          <td>{rec.position || ""}</td>
                          <td>{addName}</td>
                          <td>{formatNumber(addTotalPoints)}</td>
                          <td>{formatNumber(addPpg)}</td>
                          <td>{dropName}</td>
                          <td>{formatNumber(dropTotalPoints)}</td>
                          <td className="delta-cell">+{formatNumber(delta)}</td>
                          <td>{rec.reason || ""}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : (
        <>
          {draftMeta ? (
            <section className="panel table-panel">
              <h2>Draft Status</h2>
              <p className="status-text">
                Picks made: {draftMeta.picks_made ?? 0} | Next overall pick: {draftMeta.next_overall_pick ?? "-"} |{" "}
                {draftMeta.picks_until_your_turn === 0
                  ? "You are on the clock now"
                  : draftMeta.picks_until_your_turn != null
                    ? `Picks until your turn: ${draftMeta.picks_until_your_turn}`
                    : "Draft order unknown yet"}
              </p>
            </section>
          ) : null}

          <section className="panel table-panel">
            <h2>Current Drafted Roster</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Player</th>
                    <th>Pos</th>
                    <th>NFL</th>
                    <th>Total Season Points</th>
                    <th>PPG</th>
                    <th>Weighted Score</th>
                  </tr>
                </thead>
                <tbody>
                  {draftedRoster.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="empty-cell">
                        Get draft recommendations to view your drafted players.
                      </td>
                    </tr>
                  ) : (
                    draftedRoster.map((player, index) => (
                      <tr key={`${player.name || "player"}-${index}`}>
                        <td>{player.name || ""}</td>
                        <td>{player.position || ""}</td>
                        <td>{player.pro_team || ""}</td>
                        <td>{formatNumber(player.total_points)}</td>
                        <td>{formatNumber(player.points_per_game)}</td>
                        <td>{formatNumber(player.score)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel table-panel">
            <h2>Suggested Next Picks</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Player</th>
                    <th>Pos</th>
                    <th>NFL</th>
                    <th>Total Season Points</th>
                    <th>PPG</th>
                    <th>Draft Value</th>
                  </tr>
                </thead>
                <tbody>
                  {draftRecommendations.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="empty-cell">
                        No draft recommendations yet.
                      </td>
                    </tr>
                  ) : (
                    draftRecommendations.map((player, index) => (
                      <tr key={`${player.name || "player"}-${index}`}>
                        <td>{player.name || ""}</td>
                        <td>{player.position || ""}</td>
                        <td>{player.pro_team || ""}</td>
                        <td>{formatNumber(player.total_points)}</td>
                        <td>{formatNumber(player.points_per_game)}</td>
                        <td>{formatNumber(player.draft_value)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
