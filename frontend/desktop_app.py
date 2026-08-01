import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime
import json
from typing import Any, Dict, List, Optional

# Ensure project root is importable when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.optimizer import RosterOptimizer


class FantasyDesktopApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Fantasy Football Roster Optimizer")
        self.root.geometry("1180x760")

        self.optimizer = RosterOptimizer()
        self.config_path = PROJECT_ROOT / "frontend" / "ui_config.json"
        self.ui_config = self._load_ui_config()
        self.league_map = self._build_league_map(self.ui_config)
        self.league_label_to_id: Dict[str, str] = {}
        self.team_label_to_id: Dict[str, str] = {}

        self.league_display_var = tk.StringVar()
        self.league_id_var = tk.StringVar()
        self.year_var = tk.StringVar(value=str(datetime.now().year))
        self.team_display_var = tk.StringVar()
        self.team_id_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Enter league details and click Analyze.")

        self.league_combo: Optional[ttk.Combobox] = None
        self.year_combo: Optional[ttk.Combobox] = None
        self.team_combo: Optional[ttk.Combobox] = None

        self._build_layout()
        self._initialize_dropdown_values()

    def _load_ui_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Missing UI config file: {self.config_path}. Please create frontend/ui_config.json"
            )

        with self.config_path.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)

        if not isinstance(config, dict):
            raise ValueError("ui_config.json must contain a JSON object")

        if "leagues" not in config or not isinstance(config["leagues"], list) or not config["leagues"]:
            raise ValueError("ui_config.json must include a non-empty 'leagues' array")

        return config

    @staticmethod
    def _build_league_map(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        league_map: Dict[str, Dict[str, Any]] = {}
        for league in config.get("leagues", []):
            league_id_value = league.get("league_id", "")
            league_ids = league_id_value if isinstance(league_id_value, list) else [league_id_value]

            for league_id_item in league_ids:
                league_id = str(league_id_item).strip()
                if not league_id:
                    continue

                copied = dict(league)
                copied["league_id"] = int(league_id) if league_id.isdigit() else league_id
                league_map[league_id] = copied

        if not league_map:
            raise ValueError("No valid league entries found in ui_config.json")

        return league_map

    def _initialize_dropdown_values(self):
        league_ids = list(self.league_map.keys())
        default_league_id = str(self.ui_config.get("default_league_id", "")).strip()

        league_labels: List[str] = []
        self.league_label_to_id = {}
        for league_id in league_ids:
            league_entry = self.league_map.get(league_id, {})
            label_prefix = str(
                league_entry.get("league_label")
                or league_entry.get("league_name")
                or self.ui_config.get("league_labels", {}).get(league_id, "")
            ).strip()
            label = f"{league_id} | {label_prefix}" if label_prefix else league_id
            league_labels.append(label)
            self.league_label_to_id[label] = league_id

        if default_league_id and default_league_id in self.league_map:
            self.league_id_var.set(default_league_id)
        else:
            self.league_id_var.set(league_ids[0])

        selected_label = next(
            (label for label, league_id in self.league_label_to_id.items() if league_id == self.league_id_var.get()),
            league_labels[0],
        )
        self.league_display_var.set(selected_label)

        if self.league_combo is not None:
            self.league_combo["values"] = league_labels

        self._refresh_year_values()
        self._refresh_team_values()

        if self.league_combo is not None:
            self.league_combo.bind("<<ComboboxSelected>>", lambda _event: self._on_league_change())

    def _build_layout(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        controls = ttk.LabelFrame(frame, text="League Settings", padding=10)
        controls.pack(fill="x")

        ttk.Label(controls, text="League ID").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.league_combo = ttk.Combobox(
            controls,
            textvariable=self.league_display_var,
            width=28,
            state="readonly",
        )
        self.league_combo.grid(row=1, column=0, sticky="w", padx=6)

        ttk.Label(controls, text="Season Year").grid(row=0, column=1, sticky="w", padx=6, pady=4)
        self.year_combo = ttk.Combobox(
            controls,
            textvariable=self.year_var,
            width=10,
            state="readonly",
        )
        self.year_combo.grid(row=1, column=1, sticky="w", padx=6)

        ttk.Label(controls, text="Team ID").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        self.team_combo = ttk.Combobox(
            controls,
            textvariable=self.team_display_var,
            width=28,
            state="readonly",
        )
        self.team_combo.grid(row=1, column=2, sticky="w", padx=6)

        ttk.Label(controls, text="Config File").grid(row=0, column=3, sticky="w", padx=6, pady=4)
        ttk.Label(controls, text=str(self.config_path.name)).grid(row=1, column=3, sticky="w", padx=6)

        analyze_btn = ttk.Button(controls, text="Analyze Roster", command=self.analyze)
        analyze_btn.grid(row=1, column=4, padx=10)

        status = ttk.Label(frame, textvariable=self.status_var)
        status.pack(fill="x", pady=(8, 8))

        tables = ttk.PanedWindow(frame, orient="vertical")
        tables.pack(fill="both", expand=True)

        roster_frame = ttk.LabelFrame(tables, text="Roster")
        recs_frame = ttk.LabelFrame(tables, text="Recommended Add / Drop Moves")
        tables.add(roster_frame, weight=1)
        tables.add(recs_frame, weight=1)

        self.roster_table = ttk.Treeview(
            roster_frame,
            columns=("name", "position", "team", "ppg", "score"),
            show="headings",
            height=12,
        )
        for key, label, width in (
            ("name", "Player", 260),
            ("position", "Pos", 70),
            ("team", "NFL", 80),
            ("ppg", "PPG", 90),
            ("score", "Weighted Score", 120),
        ):
            self.roster_table.heading(key, text=label)
            self.roster_table.column(key, width=width, anchor="w")
        self.roster_table.pack(fill="both", expand=True, padx=8, pady=8)

        self.recs_table = ttk.Treeview(
            recs_frame,
            columns=("position", "add", "drop", "delta", "reason"),
            show="headings",
            height=14,
        )
        for key, label, width in (
            ("position", "Pos", 70),
            ("add", "Add", 220),
            ("drop", "Drop", 220),
            ("delta", "Score Delta", 100),
            ("reason", "Reason", 460),
        ):
            self.recs_table.heading(key, text=label)
            self.recs_table.column(key, width=width, anchor="w")
        self.recs_table.pack(fill="both", expand=True, padx=8, pady=8)

    def _on_league_change(self):
        selected_label = self.league_display_var.get().strip()
        selected_league_id = self.league_label_to_id.get(selected_label)
        if selected_league_id:
            self.league_id_var.set(selected_league_id)

        self._refresh_year_values()
        self._refresh_team_values()

    def _refresh_year_values(self):
        league_id = self.league_id_var.get().strip()
        league_entry = self.league_map.get(league_id, {})

        years = [str(year) for year in league_entry.get("years", [])]
        if not years:
            years = [str(datetime.now().year)]

        default_year = str(league_entry.get("default_year", self.ui_config.get("default_year", ""))).strip()
        if default_year and default_year in years:
            self.year_var.set(default_year)
        elif self.year_var.get().strip() in years:
            pass
        else:
            self.year_var.set(years[0])

        if self.year_combo is not None:
            self.year_combo["values"] = years

    def _refresh_team_values(self):
        league_id = self.league_id_var.get().strip()
        league_entry = self.league_map.get(league_id, {})
        teams = league_entry.get("teams", [])

        team_labels: List[str] = []
        self.team_label_to_id = {}

        for team in teams:
            team_id = str(team.get("team_id", "")).strip()
            if not team_id:
                continue
            team_name = str(team.get("team_name", "")).strip()
            label = f"{team_id} | {team_name}" if team_name else team_id
            team_labels.append(label)
            self.team_label_to_id[label] = team_id

        if not team_labels:
            self.team_display_var.set("")
            self.team_id_var.set("")
            if self.team_combo is not None:
                self.team_combo["values"] = []
            return

        team_ids = list(self.team_label_to_id.values())
        default_team_id = str(league_entry.get("default_team_id", self.ui_config.get("default_team_id", ""))).strip()
        if default_team_id and default_team_id in team_ids:
            self.team_id_var.set(default_team_id)
        elif self.team_id_var.get().strip() in team_ids:
            pass
        else:
            self.team_id_var.set(team_ids[0])

        selected_team_label = next(
            (label for label, team_id in self.team_label_to_id.items() if team_id == self.team_id_var.get()),
            team_labels[0],
        )
        self.team_display_var.set(selected_team_label)

        if self.team_combo is not None:
            self.team_combo["values"] = team_labels

    def _team_name_for_selection(self, league_id: int, team_id: Optional[int]) -> Optional[str]:
        if team_id is None:
            return None
        league_entry = self.league_map.get(str(league_id), {})
        for team in league_entry.get("teams", []):
            if int(team.get("team_id", -1)) == team_id:
                return str(team.get("team_name", "")).strip() or None
        return None

    def _parse_inputs(self):
        selected_league_label = self.league_display_var.get().strip()
        selected_league_id = self.league_label_to_id.get(selected_league_label, self.league_id_var.get().strip())
        self.league_id_var.set(selected_league_id)

        selected_team_label = self.team_display_var.get().strip()
        selected_team_id = self.team_label_to_id.get(selected_team_label, self.team_id_var.get().strip())
        self.team_id_var.set(selected_team_id)

        league_id_text = self.league_id_var.get().strip()
        year_text = self.year_var.get().strip()

        if not league_id_text:
            raise ValueError("League ID is required")

        league_id = int(league_id_text)
        year = int(year_text)

        team_id_text = self.team_id_var.get().strip()
        team_id = int(team_id_text) if team_id_text else None

        team_name = self._team_name_for_selection(league_id=league_id, team_id=team_id)
        return league_id, year, team_id, team_name

    def analyze(self):
        try:
            inputs = self._parse_inputs()
        except Exception as exc:
            messagebox.showerror("Invalid Input", str(exc))
            return

        self.status_var.set("Connecting to ESPN and analyzing players...")
        threading.Thread(target=self._run_analysis, args=inputs, daemon=True).start()

    def _run_analysis(self, league_id: int, year: int, team_id: int | None, team_name: str | None):
        try:
            result = self.optimizer.analyze_league(
                league_id=league_id,
                year=year,
                team_id=team_id,
                team_name=team_name,
            )
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("Analysis Error", str(exc)))
            self.root.after(0, lambda: self.status_var.set("Analysis failed."))
            return

        self.root.after(0, lambda: self._populate_tables(result))

    def _populate_tables(self, result):
        for row_id in self.roster_table.get_children():
            self.roster_table.delete(row_id)

        for row_id in self.recs_table.get_children():
            self.recs_table.delete(row_id)

        roster = result.get("roster", [])
        recommendations = result.get("recommendations", [])

        for player in roster:
            self.roster_table.insert(
                "",
                "end",
                values=(
                    player.get("name", ""),
                    player.get("position", ""),
                    player.get("pro_team", ""),
                    f"{float(player.get('points_per_game', 0.0)):.2f}",
                    f"{float(player.get('score', 0.0)):.2f}",
                ),
            )

        for rec in recommendations:
            add_player = rec.get("add", {})
            drop_player = rec.get("drop", {})
            self.recs_table.insert(
                "",
                "end",
                values=(
                    rec.get("position", ""),
                    add_player.get("name", ""),
                    drop_player.get("name", ""),
                    f"+{float(rec.get('score_delta', 0.0)):.2f}",
                    rec.get("reason", ""),
                ),
            )

        team = result.get("team", {})
        summary = result.get("summary", {})
        self.status_var.set(
            f"Analyzed {team.get('team_name', 'team')}: {summary.get('recommendation_count', 0)} suggested moves"
        )


def main():
    root = tk.Tk()
    app = FantasyDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
