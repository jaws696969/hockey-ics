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
- Handles Bond Sports API quirks (null `gameId`, bad end times, etc.) and TimeToScore
  quirks (string-typed IDs/scores, no explicit end time, trailing whitespace in names)
- Mix teams from both providers in one `config.yaml` — each team entry is independent

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
│   └── *.ics
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
  - name: "Alligator Skinners"
    provider: "bondsports"          # optional, defaults to "bondsports"
    slug: "alligator-skinners-fall2026-d3"
    league_name: "Fall 2026 Division 3"
    api_url: "https://api.bondsports.co/v4/competitions/.../stages/.../game-scores"
    standings_api_url: "https://api.bondsports.co/v4/competitions/.../stages/.../standings"
    my_team_ids: [7345]
    my_team_names: ["Alligator Skinners"]

  - name: "Brewzers"
    provider: "timetoscore"
    slug: "brewzers-fall2026-adultc"
    league_name: "Foundry Ice Land — Adult C"
    widget_url: "https://foundryadulthockey.com/iceland-schedule-widget/?season=177&stat_class=5"
    my_team_ids: [11911]
    my_team_names: ["Brewzers"]
```

### How TimeToScore auth works (no manual URL refreshing)

TimeToScore's API is HMAC-signed (`auth_timestamp` + `auth_signature`) by
client-side code on the league's own site, and this script doesn't replicate that
signing itself. Instead, `widget_url` points at the league's **public**
schedule-widget page — the same one any visitor sees. At each run, a real headless
browser (Playwright/Chromium) loads that page, and the script captures the
`get_schedule`/`get_standings` responses the page's own official widget code
fetches. That gives a freshly, validly signed response on every run, with nothing
to copy/paste or refresh by hand.

One `widget_url` covers a whole league/season/stat_class, so multiple teams in the
same league (e.g. Brewzers and The Owls) share one browser page load per run.

Requires the `playwright` Python package plus `playwright install --with-deps
chromium` (already wired into `.github/workflows/build_ics.yml`); for local runs,
install both once:

```bash
pip install playwright
playwright install chromium
```

### Moving a team to a new season

When a season ends and a new one starts (new Bond Sports competition/stage,
new TimeToScore season, or team IDs that got reassigned), **don't edit the old
team entry in place** — that reuses its `slug`, so the next run overwrites the
completed season's `.ics` file with new-season data and the old record is lost.
Instead:

1. Delete (or comment out) the old team's entry from `teams:`, leaving its
   `docs/<slug>.ics` (and `docs/_state/<slug>.json`) file in place untouched —
   removing it from `teams:` is enough to stop it from ever being regenerated.
2. Add a **new** entry with a **new** `slug` (e.g. append the new season name)
   pointing at the new season's URLs/IDs.

Bond Sports team IDs are commonly reassigned each season — re-pull them from
the new season's `game-scores` response rather than reusing the old ones.

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
