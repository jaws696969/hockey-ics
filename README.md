# Hockey Schedule → Google Calendar (.ics)

This project converts online hockey league schedules (via the **Bond Sports API**) into
auto-updating `.ics` calendar feeds that you can subscribe to in **Google Calendar**.

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
- Handles Bond Sports API quirks (null `gameId`, bad end times, etc.)

---

## How It Works

1. GitHub Action runs on a schedule (default: every 6 hours)
2. The script fetches Bond Sports `game-scores` JSON
3. Games are filtered to only your team
4. `.ics` calendar files are generated
5. Files are committed to `docs/`
6. GitHub Pages serves the `.ics` files
7. Google Calendar refreshes automatically

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
    slug: "alligator-skinners-winter-2026-d3"
    league_name: "Winter 2026 Division 3"
    api_url: "https://api.bondsports.co/v4/competitions/.../stages/.../game-scores"
    my_team_ids: [1254]
    my_team_names: ["Alligator Skinners"]
```

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
