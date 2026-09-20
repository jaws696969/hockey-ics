# Hockey Schedule → Google Calendar (.ics)

<!-- last heartbeat: 2026-08-16 -->

This project converts online hockey league schedules into auto-updating `.ics` calendar
feeds that you can subscribe to in **Google Calendar**. Two league data providers are
supported:

- **Bond Sports API** (`provider: bondsports`)
- **TimeToScore / Black Bear API** (`provider: timetoscore`)

Once set up, your calendar will automatically stay up to date with:
- Upcoming games
- Final scores (W / L / T)
- Correct home/away formatting
- Rink locations

All using **free GitHub tooling** (GitHub Actions + GitHub Pages).

---

## Features

- Supports multiple leagues, teams, and seasons
- Config-driven (add teams by editing `config.yaml`)
- Auto-updates via GitHub Actions
- Hosted `.ics` feeds via GitHub Pages
- Stable event IDs (no duplicate calendar entries)
- **Feeds are season-agnostic for both providers**: one team's feed merges
  every season it plays (regular season *and* playoffs) into a single
  subscription URL that never needs to change; new seasons are auto-discovered,
  no config edit needed
- Handles Bond Sports API quirks (null `gameId`, bad end times, team ids that get
  reassigned each season, etc.) and TimeToScore quirks (string-typed IDs/scores,
  no explicit end time, trailing whitespace in names)
- Mix teams from both providers in one `config.yaml` — each team entry is independent
- If a feed's last known game is over 3 weeks old with no newer season found, the
  workflow opens a GitHub issue so a feed never goes stale silently

---

## How It Works

1. GitHub Action runs on a schedule (default: every 6 hours)
2. The script fetches each team's schedule JSON from its configured `provider`
3. Games are filtered to only your team
4. `.ics` calendar files are generated
5. Files are committed to `docs/`
6. GitHub Pages serves the `.ics` files
7. Google Calendar refreshes automatically

If a team's fetch fails, that team is skipped for the run with a clear `ERROR:` line
in the Action log — its previously-generated `.ics` file is left untouched rather
than the whole run failing.

---

## Repository Structure

```
.
├── README.md
├── config.yaml
├── src/
│   └── generate_ics.py
├── docs/
│   ├── *.ics                  # published feeds
│   └── _state/
│       ├── <slug>.json        # discovered seasons/stages + frozen standings snapshots
│       └── summary.json       # what each feed currently contains (staleness watchdog)
└── .github/
    └── workflows/
        └── build_ics.yml
```

---

## Configuration (`config.yaml`)

```yaml
output_dir: "docs"
default_timezone: "America/New_York"

teams:
  - name: "Alligator Skinners"        # team name exactly as Bond Sports shows it
    provider: "bondsports"            # optional, defaults to "bondsports"
    slug: "alligator-skinners"        # -> docs/alligator-skinners.ics (season-agnostic)
    aliases: ["alligator-skinners-fall2026-d3"]  # optional: extra copies (legacy URLs)
    program_id: 12070                 # Bond Sports program -> seasons auto-discovered
    seasons:                          # optional: explicit seasons, always included
      - league_name: "Winter 2026 Division 3"
        competition_id: "180251ce-9fbc-4153-b7f6-ce3530a2c7f9"
        stage_id: 153

  - name: "Brewzers"                  # team name exactly as TimeToScore shows it
    provider: "timetoscore"
    slug: "brewzers"                  # -> docs/brewzers.ics (season-agnostic)
    aliases: ["brewzers-fall2026-adultc"]  # optional: extra copies (legacy URLs)
    league_widget_url: "https://foundryadulthockey.com/iceland-schedule-widget/?season=177&stat_class=5"
```

### How Bond Sports season-agnostic feeds work

Every season of a team playing at once, with a stable subscription URL, is the
whole point: `program_id` is the number in the league's Bond Sports URL
(`bondsports.co/activity/programs/adult-hockey/12070/season/...`). On each run,
the script lists **every** season of that program, and for each one fetches its
competition and every stage under it (typically "Regular Season" and
"Playoffs" — both are just stages of the same competition, so playoffs are
picked up automatically, no separate config needed). Any stage where a team
named `name` (or an alt spelling under `team_names:`) appears gets merged into
the one feed at `slug`, sorted chronologically. Numeric team ids are resolved
by matching `name` against each stage's own schedule — Bond Sports reassigns
them every season, so nothing needs to be hunted down and updated by hand.

Discovered seasons/stages are cached in `docs/_state/<slug>.json` under a
`discovery` key: once a team is confirmed in a stage, that's remembered forever
(so the feed keeps history even if Bond Sports later stops listing an old
season), while stages where the team *hasn't* shown up yet keep getting
re-checked on every run until the season ends (schedules/playoff brackets are
often published late). `seasons:` lists explicit seasons that are always
included too, regardless of discovery — useful as a fallback if the discovery
API ever changes shape.

Optional per-team keys: `team_names` (alternate spellings to match against),
`calendar_name`, `opponent_recent_max`, `head_to_head_max`. A season entry can
also skip `competition_id`/`stage_id` and give `api_url`/`standings_api_url`
directly, or `team_id` if name-matching ever picks the wrong team.

Each season's head-to-head / opponent-games-to-date / standings are computed
from that season's own stage (mixing across seasons/divisions wouldn't make
sense) — only the final list of events is merged into one calendar.

### How TimeToScore auth works (no manual URL refreshing)

TimeToScore's API is HMAC-signed (`auth_timestamp` + `auth_signature`) by
client-side code on the league's own site, and this script doesn't replicate that
signing itself. Instead, `league_widget_url` points at the league's **public**
schedule-widget page — the same one any visitor sees. At each run, a real headless
browser (Playwright/Chromium) loads that page, and the script captures the
`get_schedule`/`get_standings`/`get_leagues` responses the page's own official
widget code fetches. That gives a freshly, validly signed response on every run,
with nothing to copy/paste or refresh by hand.

Requires the `playwright` Python package plus `playwright install --with-deps
chromium` (already wired into `.github/workflows/build_ics.yml`); for local runs,
install both once:

```bash
pip install playwright
playwright install chromium
```

### How TimeToScore season-agnostic feeds work

Same idea as Bond Sports, adapted to TimeToScore's shape. A `league_id` (visible
in the widget URL's query string, though you don't need to read it — just reuse
any existing widget URL for the league) keeps a persistent list of every
`season_id` it's ever run, via `get_leagues` — the same "one program, many
seasons" concept Bond Sports has. Unlike Bond, there's no separate stage to walk:
fetching a season at `stat_class=7` ("Adult Total") already returns regular
season + playoffs merged in one call.

On each run, the script loads `league_widget_url` (one browser page — teams
sharing a league, like Brewzers and The Owls, share this fetch), reads the
season list from the `get_leagues` response that comes back, and for each season
not yet ruled out, re-fetches that season at `stat_class=7` and checks whether a
team named `name` (or `team_names:`) appears. Matching seasons merge into the
one feed at `slug`, sorted chronologically, exactly like Bond Sports.

**Unlike Bond Sports team ids** (reassigned every season), a TimeToScore team id
stayed identical for the same team across seasons in testing — but a league can
reuse a generic team *name* for a completely different roster in an older
season: confirmed here, where a different "Brewzers" (same team id!) existed in
this league a full year before the configured team joined it. To avoid silently
folding in a stranger team's history, **only the current season is auto-included
on first discovery** — seasons that already existed at that point are left
alone. Every season from that point forward is picked up automatically with no
config change. `seasons:` can list a specific older season explicitly (same
fallback pattern as Bond Sports) if you've confirmed it's really the same team
and want it included anyway.

Discovered seasons are cached in `docs/_state/<slug>.json` under a `discovery`
key the same way Bond Sports stages are: once positive, remembered forever;
while negative, re-checked every run only for the current season (schedules
are sometimes published late).

### Moving a legacy single-season TimeToScore team

The old style — `widget_url` + `my_team_ids`/`my_team_names`, one fixed
league/season/stat_class — still works for a team entry that doesn't set
`league_widget_url`. For that style only, **don't edit the entry in place**
when the season ends (it reuses `slug`, overwriting the prior season's `.ics`).
Delete/comment out the old entry (its `docs/<slug>.ics` stays untouched) and
add a new entry with a new `slug`. Prefer `league_widget_url` for anything new.

---

## GitHub Pages Setup

1. Repo → Settings → Pages  
2. Source: Deploy from a branch  
3. Branch: `main`  
4. Folder: `/docs`  

Your calendar feed will be available at:

```
https://<github-username>.github.io/<repo-name>/<slug>.ics
```

---

## Google Calendar Subscription

Google Calendar → Other calendars → `+` → From URL  
Paste the `.ics` URL.

---

## License

MIT
