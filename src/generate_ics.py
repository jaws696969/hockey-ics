#!/usr/bin/env python3
"""
hockey-ics: generate .ics feeds from Bond Sports API.

Feature 1) Opponent games before this matchup:
  - Include ALL opponent games whose start < this matchup start (even future games between now and matchup).
  - If scores exist: include W/L/T X-Y
  - If scores missing: include the game line but omit the result.

Feature 2) Standings snapshot per event:
  - Future events: standings updated each run (as-of timestamp included)
  - Past events (game start passed): standings frozen (kept as it was first time it crossed into the past)
  - Snapshots persisted under: docs/_state/<calendar-namespace>.json

Formatting improvements:
  - ASCII separators for sections
  - Compact opponent list lines with local (config) timezone display
  - Head-to-head section vs opponent

Config expected:
output_dir: "docs"
default_timezone: "America/New_York"
teams:
  - name: ...
    slug: ...
    league_name: ...
    api_url: ... game-scores
    standings_api_url: ... standings   # recommended
    my_team_ids: [ ... ]               # supports multiple IDs
    my_team_names: [ ... ]             # same length as ids
    opponent_recent_max: 12            # optional
    head_to_head_max: 5                # optional
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# -------------------------
# Helpers
# -------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def parse_iso_z(dt_str: str) -> datetime:
    # "2026-01-20T01:30:00.000Z" or without ms
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)

def fmt_dt_utc_for_ics(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")

def ics_escape(text: str) -> str:
    text = text.replace("\\", "\\\\")
    text = text.replace("\n", "\\n")
    text = text.replace(";", r"\;")
    text = text.replace(",", r"\,")
    return text

def stable_uid(namespace: str, event_id: Any) -> str:
    raw = f"{namespace}:{event_id}".encode("utf-8")
    h = hashlib.sha256(raw).hexdigest()[:24]
    return f"{h}@hockey-ics"

def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "calendar"

def fetch_json(url: str, timeout: int = 30) -> Any:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def ascii_rule(title: str, width: int = 40) -> List[str]:
    line = "-" * width
    return [line, title, line]

def ordinal(n: int) -> str:
    # 1st/2nd/3rd/4th...
    if 10 <= (n % 100) <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"

def fmt_month_day_local(dt: datetime, tz: timezone) -> str:
    # e.g. "Jan 20th"
    d = dt.astimezone(tz)
    mon = d.strftime("%b")
    day = int(d.strftime("%d"))
    return f"{mon} {ordinal(day)}"

def fmt_start_local(dt: datetime, tz: timezone) -> str:
    # e.g. "2026-01-19 20:30 EST"
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")


# -------------------------
# Models
# -------------------------

@dataclass
class TeamRef:
    id: int
    name: str
    score: Optional[int]

@dataclass
class SpaceRef:
    name: Optional[str]

@dataclass
class Game:
    event_id: Any
    game_id: Any
    stage_name: Optional[str]
    status: str
    start: datetime
    end: datetime
    home: TeamRef
    away: TeamRef
    space: SpaceRef

    def involves_team_id(self, team_id: int) -> bool:
        return self.home.id == team_id or self.away.id == team_id

    @property
    def has_result(self) -> bool:
        return self.home.score is not None and self.away.score is not None

    @property
    def is_final(self) -> bool:
        return (self.status or "").lower() == "final" and self.has_result


def parse_games(raw_games: List[Dict[str, Any]]) -> List[Game]:
    games: List[Game] = []
    for g in raw_games:
        start = parse_iso_z(g["startDateTime"])
        end = parse_iso_z(g["endDateTime"])
        if end <= start:
            end = start + timedelta(minutes=80)

        games.append(
            Game(
                event_id=g.get("eventId"),
                game_id=g.get("gameId"),
                stage_name=g.get("stageName"),
                status=g.get("status") or "scheduled",
                start=start,
                end=end,
                home=TeamRef(
                    id=int(g["homeTeam"]["id"]),
                    name=str(g["homeTeam"]["name"]),
                    score=g["homeTeam"].get("score"),
                ),
                away=TeamRef(
                    id=int(g["awayTeam"]["id"]),
                    name=str(g["awayTeam"]["name"]),
                    score=g["awayTeam"].get("score"),
                ),
                space=SpaceRef(name=(g.get("space") or {}).get("name")),
            )
        )
    return games


# -------------------------
# Feature: results helpers
# -------------------------

def result_for_team(game: Game, team_id: int) -> Optional[str]:
    """Return 'W 5-3' / 'L 2-6' / 'T 3-3' if scores exist, else None."""
    if not game.has_result:
        return None

    if game.home.id == team_id:
        gf, ga = game.home.score, game.away.score
    elif game.away.id == team_id:
        gf, ga = game.away.score, game.home.score
    else:
        return None

    if gf is None or ga is None:
        return None

    if gf > ga:
        prefix = "W"
    elif gf < ga:
        prefix = "L"
    else:
        prefix = "T"
    return f"{prefix} {gf}-{ga}"


# -------------------------
# Feature 1: opponent games (compact, local dates)
# -------------------------

def opponent_games_lines_compact(
    all_games: List[Game],
    opponent_id: int,
    cutoff_start: datetime,
    tz: timezone,
    max_lines: int = 12,
) -> List[str]:
    """
    Include ALL opponent games with start < cutoff_start (regardless of status).

    Compact format (no repeating opponent name):
        "    Jan 20th vs Backdoor Bandits (W 10-5)"
        "    Feb 3rd @ Dirty Mike and the Boys"
    """
    prior = [g for g in all_games if g.involves_team_id(opponent_id) and g.start < cutoff_start]
    prior.sort(key=lambda g: g.start)

    lines: List[str] = []
    for g in prior[-max_lines:]:
        opp_is_home = (g.home.id == opponent_id)
        other = g.away if opp_is_home else g.home
        at_vs = "vs" if opp_is_home else "@"

        res = result_for_team(g, opponent_id)
        date_str = fmt_month_day_local(g.start, tz)

        if res:
            lines.append(f"    {date_str} {at_vs} {other.name} ({res})")
        else:
            lines.append(f"    {date_str} {at_vs} {other.name}")
    return lines


# -------------------------
# Feature: head-to-head vs opponent (compact, local dates)
# -------------------------

def head_to_head_lines(
    all_games: List[Game],
    my_team_id: int,
    opponent_id: int,
    cutoff_start: datetime,
    tz: timezone,
    max_lines: int = 5,
) -> List[str]:
    """
    Prior matchups between my team and opponent, before cutoff_start.
    Compact formatting from my team perspective.
    """
    h2h = [
        g for g in all_games
        if g.start < cutoff_start
        and g.involves_team_id(my_team_id)
        and g.involves_team_id(opponent_id)
    ]
    h2h.sort(key=lambda g: g.start)

    lines: List[str] = []
    for g in h2h[-max_lines:]:
        my_is_home = (g.home.id == my_team_id)
        at_vs = "vs" if my_is_home else "@"
        opp_name = g.away.name if my_is_home else g.home.name

        res = result_for_team(g, my_team_id)
        date_str = fmt_month_day_local(g.start, tz)

        if res:
            lines.append(f"    {date_str} {at_vs} {opp_name} ({res})")
        else:
            lines.append(f"    {date_str} {at_vs} {opp_name}")
    return lines


# -------------------------
# Feature 2: standings parsing & formatting
# -------------------------

def pick_division_standings(raw: Any, my_team_id: int) -> List[Dict[str, Any]]:
    """
    Raw standings example:
    [
      { divisionId, divisionName, standings: [ {team:{id,name}, rank, points, wins, losses, ...}, ... ] },
      ...
    ]

    We pick the division that contains my team id if possible.
    If not found, fallback to first division's standings.
    """
    if not isinstance(raw, list) or not raw:
        return []

    for div in raw:
        if not isinstance(div, dict):
            continue
        rows = div.get("standings")
        if not isinstance(rows, list):
            continue
        for r in rows:
            team = (r or {}).get("team") if isinstance(r, dict) else None
            if isinstance(team, dict) and int(team.get("id", -1)) == my_team_id:
                return rows

    for div in raw:
        if isinstance(div, dict) and isinstance(div.get("standings"), list):
            return div["standings"]

    return []

def format_standings_lines(rows: List[Dict[str, Any]], max_rows: int = 12) -> List[str]:
    def key(r: Dict[str, Any]) -> Tuple[int, str]:
        try:
            rk = int(r.get("rank", 9999))
        except Exception:
            rk = 9999
        team = r.get("team") if isinstance(r, dict) else None
        name = team.get("name") if isinstance(team, dict) else ""
        return (rk, str(name))

    rows_sorted = sorted(rows, key=key)[:max_rows]
    out: List[str] = []
    for r in rows_sorted:
        team = r.get("team") if isinstance(r, dict) else None
        name = team.get("name") if isinstance(team, dict) else "Unknown"
        rank = r.get("rank")
        wins = r.get("wins")
        losses = r.get("losses")
        points = r.get("points")

        bits = []
        if rank is not None:
            bits.append(f"{rank}.")
        bits.append(str(name))

        rec = []
        if wins is not None and losses is not None:
            rec.append(f"{wins}-{losses}")
        if points is not None:
            rec.append(f"{points} pts")

        if rec:
            bits.append("(" + ", ".join(map(str, rec)) + ")")

        out.append(" ".join(bits))
    return out


# -------------------------
# ICS building
# -------------------------

def build_ics_calendar(cal_name: str, events: List[str]) -> str:
    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//hockey-ics//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(cal_name)}",
    ]
    footer = ["END:VCALENDAR"]
    return "\r\n".join(header + events + footer) + "\r\n"

def build_vevent(
    uid: str,
    summary: str,
    dtstart: datetime,
    dtend: datetime,
    description: str,
    location: str,
    last_modified: datetime,
) -> str:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{ics_escape(uid)}",
        f"DTSTAMP:{fmt_dt_utc_for_ics(utc_now())}",
        f"LAST-MODIFIED:{fmt_dt_utc_for_ics(last_modified)}",
        f"DTSTART:{fmt_dt_utc_for_ics(dtstart)}",
        f"DTEND:{fmt_dt_utc_for_ics(dtend)}",
        f"SUMMARY:{ics_escape(summary)}",
    ]
    if location:
        lines.append(f"LOCATION:{ics_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{ics_escape(description)}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines)

def my_title(my_team_id: int, my_team_name: str, game: Game) -> Tuple[str, Optional[str], int, str]:
    """Return (title, my_result, opp_id, opp_name). Title always lists my team first."""
    if game.home.id == my_team_id:
        opp_id, opp_name = game.away.id, game.away.name
        core = f"{my_team_name} vs {opp_name}"
    else:
        opp_id, opp_name = game.home.id, game.home.name
        core = f"{my_team_name} @ {opp_name}"

    res = result_for_team(game, my_team_id)
    if res:
        return f"{core} ({res})", res, opp_id, opp_name
    return core, None, opp_id, opp_name


# -------------------------
# State: standings snapshots
# -------------------------

def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"events": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"events": {}}

def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

def freeze_for_game(game: Game, now: datetime) -> bool:
    return now >= game.start


# -------------------------
# Main
# -------------------------

def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "config.yaml"

    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    output_dir = repo_root / str(cfg.get("output_dir", "docs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    state_dir = output_dir / "_state"
    state_dir.mkdir(parents=True, exist_ok=True)

    tz_name = str(cfg.get("default_timezone", "America/New_York"))
    if ZoneInfo is not None:
        try:
            local_tz = ZoneInfo(tz_name)
        except Exception:
            local_tz = timezone.utc
            tz_name = "UTC"
    else:
        local_tz = timezone.utc
        tz_name = "UTC"

    teams = cfg.get("teams", [])
    if not teams:
        raise SystemExit("No teams found in config.yaml under 'teams'.")

    now = utc_now()
    run_asof = now.strftime("%Y-%m-%d %H:%M UTC")

    for team_entry in teams:
        league_name = str(team_entry.get("league_name", team_entry.get("name", "League")))
        slug = str(team_entry.get("slug", slugify(team_entry.get("name", league_name))))
        games_url = str(team_entry["api_url"])
        standings_url = team_entry.get("standings_api_url")
        max_recent = int(team_entry.get("opponent_recent_max", 12))
        h2h_max = int(team_entry.get("head_to_head_max", 5))

        my_ids: List[int] = [int(x) for x in (team_entry.get("my_team_ids") or [])]
        my_names: List[str] = [str(x) for x in (team_entry.get("my_team_names") or [])]

        if len(my_ids) != len(my_names) or not my_ids:
            raise SystemExit(f"Config error for {slug}: my_team_ids and my_team_names must exist and be same length.")

        raw_games = fetch_json(games_url)
        all_games = parse_games(raw_games)

        for my_team_id, my_team_name in zip(my_ids, my_names):
            cal_name = f"{my_team_name} — {league_name}"
            out_file = f"{slug}-{slugify(my_team_name)}.ics" if len(my_ids) > 1 else f"{slug}.ics"
            namespace = slugify(out_file.replace(".ics", ""))

            state_path = state_dir / f"{namespace}.json"
            state = load_state(state_path)
            state_events: Dict[str, Any] = state.setdefault("events", {})

            standings_lines_current: List[str] = []
            if standings_url:
                standings_raw = fetch_json(str(standings_url))
                rows = pick_division_standings(standings_raw, my_team_id=my_team_id)
                standings_lines_current = format_standings_lines(rows)

            my_games = [g for g in all_games if g.involves_team_id(my_team_id)]
            my_games.sort(key=lambda g: g.start)

            vevents: List[str] = []
            for g in my_games:
                title, my_res, opp_id, opp_name = my_title(my_team_id, my_team_name, g)
                uid = stable_uid(namespace, g.event_id)

                desc: List[str] = []
                desc.extend(ascii_rule("GAME INFO"))
                desc.append(f"League: {league_name}")
                if g.stage_name:
                    desc.append(f"Stage: {g.stage_name}")
                desc.append(f"Status: {g.status}")
                desc.append(f"Start ({tz_name}): {fmt_start_local(g.start, local_tz)}")
                if g.space.name:
                    desc.append(f"Rink: {g.space.name}")
                if my_res:
                    desc.append(f"Result: {my_res}")

                # Head-to-head (prior matchups vs opponent)
                h2h_lines = head_to_head_lines(
                    all_games=all_games,
                    my_team_id=my_team_id,
                    opponent_id=opp_id,
                    cutoff_start=g.start,
                    tz=local_tz,
                    max_lines=h2h_max,
                )
                if h2h_lines:
                    desc.append("")
                    desc.extend(ascii_rule(f"Head-to-head vs {opp_name}"))
                    desc.extend(h2h_lines)

                # Feature 1: opponent games before this matchup (compact)
                opp_lines = opponent_games_lines_compact(
                    all_games=all_games,
                    opponent_id=opp_id,
                    cutoff_start=g.start,
                    tz=local_tz,
                    max_lines=max_recent,
                )
                if opp_lines:
                    desc.append("")
                    desc.extend(ascii_rule(f"{opp_name} games before this matchup"))
                    desc.extend(opp_lines)

                # Feature 2: standings snapshot (frozen for past games)
                if standings_url and standings_lines_current:
                    key = str(g.event_id)
                    if freeze_for_game(g, now):
                        if key not in state_events:
                            state_events[key] = {"as_of": run_asof, "lines": standings_lines_current}
                        snap = state_events[key]
                    else:
                        state_events[key] = {"as_of": run_asof, "lines": standings_lines_current}
                        snap = state_events[key]

                    snap_asof = snap.get("as_of", run_asof)
                    snap_lines = snap.get("lines", [])
                    if snap_lines:
                        desc.append("")
                        desc.extend(ascii_rule(f"Standings (as of {snap_asof})"))
                        desc.extend([str(x) for x in snap_lines])

                vevents.append(
                    build_vevent(
                        uid=uid,
                        summary=title,
                        dtstart=g.start,
                        dtend=g.end,
                        description="\n".join(desc),
                        location=(g.space.name or ""),
                        last_modified=now,
                    )
                )

            ics_text = build_ics_calendar(cal_name=cal_name, events=vevents)
            (output_dir / out_file).write_text(ics_text, encoding="utf-8")
            save_state(state_path, state)

    print("Done. Calendars updated.")


if __name__ == "__main__":
    main()
