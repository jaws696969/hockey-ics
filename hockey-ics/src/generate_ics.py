#!/usr/bin/env python3
"""
generate_ics.py

Fetch Bond Sports "game-scores" JSON for one or more leagues/teams (configured in config.yaml),
filter to games involving your team, and write .ics files into docs/ (or configured output_dir).

Designed for GitHub Actions + GitHub Pages publishing.

Dependencies:
  pip install requests pyyaml

Config example (config.yaml):
  output_dir: "docs"
  default_timezone: "America/New_York"
  teams:
    - name: "Alligator Skinners"
      slug: "alligator-skinners-winter-2026-d3"
      league_name: "Winter 2026 Division 3"
      api_url: "https://api.bondsports.co/v4/competitions/.../stages/.../game-scores"
      my_team_ids: [1254]
      my_team_names: ["Alligator Skinners"]
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from zoneinfo import ZoneInfo


# -----------------------------
# Data model
# -----------------------------

@dataclass(frozen=True)
class Game:
    uid_source: str               # stable id (eventId preferred when gameId is null)
    start: datetime               # tz-aware
    end: datetime                 # tz-aware
    home_team: str
    away_team: str
    home_team_id: Optional[int]
    away_team_id: Optional[int]
    home_score: Optional[int]
    away_score: Optional[int]
    status: Optional[str]         # "scheduled" / "final" / etc
    location: Optional[str]       # space.name
    stage_name: Optional[str]


# -----------------------------
# ICS helpers
# -----------------------------

def _ics_escape(s: str) -> str:
    # RFC 5545 escaping for text
    return (
        s.replace("\\", "\\\\")
         .replace(";", r"\;")
         .replace(",", r"\,")
         .replace("\n", r"\n")
    )


def _dt_to_ics_utc(dt: datetime) -> str:
    # Normalize to UTC Z format
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _stable_uid(team_slug: str, uid_source: str) -> str:
    # Stable UID means Google updates events instead of duplicating them
    raw = f"{team_slug}:{uid_source}".encode("utf-8")
    h = hashlib.sha256(raw).hexdigest()[:24]
    return f"{h}@bond-hockey-ics"


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _parse_iso_z(dt_str: str) -> datetime:
    # Handles "2026-01-20T01:30:00.000Z"
    # fromisoformat needs +00:00
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def _safe_int(x: Any) -> Optional[int]:
    if isinstance(x, int):
        return x
    if isinstance(x, str) and x.strip().isdigit():
        return int(x.strip())
    return None


def _result_string(my_is_home: bool, home_score: Optional[int], away_score: Optional[int]) -> Optional[str]:
    if home_score is None or away_score is None:
        return None
    my_score = home_score if my_is_home else away_score
    opp_score = away_score if my_is_home else home_score

    if my_score > opp_score:
        prefix = "W"
    elif my_score < opp_score:
        prefix = "L"
    else:
        prefix = "T"

    return f"{prefix} {my_score}-{opp_score}"


def _build_summary(my_team: str, opponent: str, my_is_home: bool, result: Optional[str]) -> str:
    base = f"{my_team} vs {opponent}" if my_is_home else f"{my_team} @ {opponent}"
    return f"{base} ({result})" if result else base


def _is_my_team_by_name(team_name: str, my_team_names: List[str]) -> bool:
    tn = _normalize(team_name)
    return any(tn == _normalize(x) for x in my_team_names)


# -----------------------------
# Bond Sports parsing
# -----------------------------

def parse_bond_game_scores(payload: Any) -> List[Game]:
    """
    Bond Sports /v4/.../game-scores returns a JSON array of objects like:
      {
        "gameId": 1040,
        "eventId": 4416839,
        "homeTeam": {"id": 1254, "name": "...", "score": 6},
        "awayTeam": {"id": 1258, "name": "...", "score": 3},
        "status": "final",
        "startDateTime": "2026-01-20T01:30:00.000Z",
        "endDateTime": "2026-01-20T02:50:00.000Z",
        "space": {"name": "West Rink"},
        "stageName": "Regular Season"
      }
    """
    if not isinstance(payload, list):
        raise ValueError("Bond Sports game-scores endpoint expected to return a JSON array (list).")

    games: List[Game] = []
    default_duration = timedelta(minutes=80)  # matches your typical 01:30 -> 02:50 slot

    for g in payload:
        if not isinstance(g, dict):
            continue

        game_id = g.get("gameId")
        event_id = g.get("eventId")
        uid_source = str(game_id) if game_id is not None else str(event_id)

        start_str = g.get("startDateTime")
        if not start_str:
            continue
        start = _parse_iso_z(start_str)

        end_str = g.get("endDateTime")
        end = _parse_iso_z(end_str) if end_str else (start + default_duration)

        # Guard for bad upstream data: some items have endDateTime earlier than startDateTime
        if end <= start:
            end = start + default_duration

        home = g.get("homeTeam") or {}
        away = g.get("awayTeam") or {}

        home_team = str(home.get("name") or "")
        away_team = str(away.get("name") or "")
        home_team_id = _safe_int(home.get("id"))
        away_team_id = _safe_int(away.get("id"))

        home_score = _safe_int(home.get("score"))
        away_score = _safe_int(away.get("score"))

        status = g.get("status")
        status = str(status) if status is not None else None

        stage_name = g.get("stageName")
        stage_name = str(stage_name) if stage_name is not None else None

        space = g.get("space") or {}
        location = space.get("name")
        location = str(location) if location is not None else None

        games.append(
            Game(
                uid_source=uid_source,
                start=start,
                end=end,
                home_team=home_team,
                away_team=away_team,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                home_score=home_score,
                away_score=away_score,
                status=status,
                location=location,
                stage_name=stage_name,
            )
        )

    return games


# -----------------------------
# Filtering + ICS generation
# -----------------------------

def filter_games_for_team(
    games: List[Game],
    my_team_name: str,
    my_team_ids: List[int],
    my_team_names: List[str],
) -> List[Tuple[Game, str, bool, Optional[str]]]:
    """
    Returns list of (game, opponent_name, my_is_home, result_str)
    Matching priority:
      1) team ID (if provided)
      2) team name (case-insensitive, normalized)
    """
    my_ids = set(int(x) for x in my_team_ids if isinstance(x, int))
    my_names = my_team_names or [my_team_name]

    out: List[Tuple[Game, str, bool, Optional[str]]] = []

    for g in games:
        if my_ids:
            home_is_me = g.home_team_id in my_ids
            away_is_me = g.away_team_id in my_ids
        else:
            home_is_me = _is_my_team_by_name(g.home_team, my_names)
            away_is_me = _is_my_team_by_name(g.away_team, my_names)

        if not (home_is_me or away_is_me):
            continue

        my_is_home = home_is_me
        opponent = g.away_team if my_is_home else g.home_team
        result = _result_string(
            my_is_home=my_is_home,
            home_score=g.home_score,
            away_score=g.away_score,
        )
        out.append((g, opponent, my_is_home, result))

    # Stable ordering
    out.sort(key=lambda x: x[0].start)
    return out


def build_ics(
    team_slug: str,
    calendar_name: str,
    description_prefix: Optional[str],
    items: List[Tuple[Game, str, bool, Optional[str]]],
) -> str:
    """
    Build RFC5545 .ics text.
    We write DTSTART/DTEND in UTC Z timestamps for maximum compatibility.
    """
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines: List[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//bond-hockey-ics//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(calendar_name)}",
        "X-WR-TIMEZONE:UTC",
    ]

    for g, opponent, my_is_home, result in items:
        uid = _stable_uid(team_slug, g.uid_source)
        summary = _build_summary(calendar_name, opponent, my_is_home, result)

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART:{_dt_to_ics_utc(g.start)}",
            f"DTEND:{_dt_to_ics_utc(g.end)}",
            f"SUMMARY:{_ics_escape(summary)}",
        ])

        if g.location:
            lines.append(f"LOCATION:{_ics_escape(g.location)}")

        # A useful DESCRIPTION for debugging / info in calendar
        desc_parts: List[str] = []
        if description_prefix:
            desc_parts.append(description_prefix)
        if g.stage_name:
            desc_parts.append(f"Stage: {g.stage_name}")
        if g.status:
            desc_parts.append(f"Status: {g.status}")
        desc_parts.append(f"Home: {g.home_team}")
        desc_parts.append(f"Away: {g.away_team}")
        if g.home_score is not None and g.away_score is not None:
            desc_parts.append(f"Score (Away-Home): {g.away_score}-{g.home_score}")

        lines.append(f"DESCRIPTION:{_ics_escape(' | '.join(desc_parts))}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    # RFC wants CRLF
    return "\r\n".join(lines) + "\r\n"


# -----------------------------
# Main
# -----------------------------

def main() -> None:
    # Load config
    with open("config.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    output_dir = str(cfg.get("output_dir", "docs"))
    os.makedirs(output_dir, exist_ok=True)

    default_tz_name = str(cfg.get("default_timezone", "America/New_York"))
    default_tz = ZoneInfo(default_tz_name)

    teams_cfg = cfg.get("teams", [])
    if not isinstance(teams_cfg, list) or not teams_cfg:
        raise ValueError("config.yaml must contain a non-empty 'teams' list.")

    for t in teams_cfg:
        if not isinstance(t, dict):
            continue

        team_name = str(t.get("name", "")).strip()
        team_slug = str(t.get("slug", "")).strip()
        api_url = str(t.get("api_url", "")).strip()

        if not team_name or not team_slug or not api_url:
            raise ValueError("Each team entry must have: name, slug, api_url")

        league_name = str(t.get("league_name", "")).strip()
        tz_name = str(t.get("timezone", default_tz_name))
        tz = ZoneInfo(tz_name) if tz_name else default_tz  # kept for future use

        # Matching info
        my_team_ids = t.get("my_team_ids", []) or []
        if not isinstance(my_team_ids, list):
            my_team_ids = []
        my_team_ids_int: List[int] = []
        for x in my_team_ids:
            xi = _safe_int(x)
            if xi is not None:
                my_team_ids_int.append(xi)

        my_team_names = t.get("my_team_names", []) or []
        if not isinstance(my_team_names, list):
            my_team_names = []
        my_team_names_str = [str(x) for x in my_team_names if str(x).strip()]

        # Fetch
        resp = requests.get(api_url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        # Parse (Bond Sports)
        games = parse_bond_game_scores(payload)

        # Filter
        items = filter_games_for_team(
            games=games,
            my_team_name=team_name,
            my_team_ids=my_team_ids_int,
            my_team_names=my_team_names_str,
        )

        # Calendar naming:
        # - Keep your team first as the "calendar name" so SUMMARY starts with team.
        calendar_name = team_name
        description_prefix = league_name or None

        ics_text = build_ics(
            team_slug=team_slug,
            calendar_name=calendar_name,
            description_prefix=description_prefix,
            items=items,
        )

        out_path = os.path.join(output_dir, f"{team_slug}.ics")
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(ics_text)

        print(f"Wrote {out_path} with {len(items)} events (source: {api_url})")

    print("Done.")


if __name__ == "__main__":
    main()
