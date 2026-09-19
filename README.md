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

If a team's fetch fails (see **TimeToScore signed URLs**, below), that team is skipped
for the run with a clear `ERROR:` line in the Action log — its previously-generated
`.ics` file is left untouched rather than the whole run failing.

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
    slug: "alligator-skinners-winter-2026-d3"
    league_name: "Winter 2026 Division 3"
    api_url: "https://api.bondsports.co/v4/competitions/.../stages/.../game-scores"
    standings_api_url: "https://api.bondsports.co/v4/competitions/.../stages/.../standings"
    my_team_ids: [1254]
    my_team_names: ["Alligator Skinners"]

  - name: "Brewzers"
    provider: "timetoscore"
    slug: "brewzers-fall2026-adultc"
    league_name: "Foundry Ice Land — Adult C"
    api_url: "https://api.blackbear.timetoscore.com/get_schedule?...&auth_signature=..."
    standings_api_url: "https://api.blackbear.timetoscore.com/get_standings?...&auth_signature=..."
    my_team_ids: [11911]
    my_team_names: ["Brewzers"]
```

### TimeToScore signed URLs

TimeToScore's API is HMAC-signed (`auth_timestamp` + `auth_signature`); this script
cannot generate its own signatures, so `api_url`/`standings_api_url` for a
`timetoscore` team are exact URLs copied from the league site, and they **will
eventually stop working** (the signature covers the timestamp, so it's not just a
matter of the request being old — any change to the URL invalidates it too).

Two things to know:

- **`api_url` must be the full, un-scoped schedule request (no `team_id` param)**,
  not a single team's schedule. Opponent-games-to-date and head-to-head need to see
  every team's games, and team-scoped signatures can't be edited to remove `team_id`.
- **When a run logs `ERROR: <team>: failed to fetch/parse schedule`**, the signed URL
  has expired. To refresh: open the league's public schedule page (e.g.
  `https://foundryadulthockey.com/iceland-schedule-widget/?season=<id>&stat_class=<id>`),
  open your browser's devtools → Network tab, reload, and copy a fresh `get_schedule`
  (no `team_id`) and `get_standings` request URL. Paste them into `config.yaml` for
  every `timetoscore` team that shares that league/season.

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
