# Running do good talent locally

How to get the code running on your own computer, for teammates working on the project. To **use** the finished app instead, install it from the Releases page: see [FIRST_LAUNCH.md](FIRST_LAUNCH.md).

Everything runs inside Docker, so you don't need Python installed. The same steps work on Windows, macOS and Linux.

---

## 1. Install the tools (once)

- **Git**: to download the code.
- **Docker Desktop**: [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/). Start it once and leave it running while you work.
  - **Windows:** turn on "Use the WSL 2 based engine" (the default). Clone the repo **inside WSL** (for example `~/work`), not under `C:\`, or the app is slow and line endings break.
  - **Docker memory:** the app is capped at 4 GB; Docker Desktop's default limit is enough.
- **A Gemini API key** (free): sign in at [aistudio.google.com](https://aistudio.google.com) with a Google account and choose **Get API key**. Don't turn on billing for that project. Treat the key like a password.

## 2. Get the code

```
git clone https://github.com/wilsonnguyen5163/contract-headhunter.git
cd contract-headhunter
```

Work on a branch, never on `main` (it's protected: changes go in through a pull request).

## 3. Add your Gemini key

```
cp .env.example .env
```

Open `.env` in an editor and fill in the line `GEMINI_API_KEY=` (remove the `#` in front of it). `.env` is git-ignored: never commit it, paste it in chat, or put the key anywhere else.

You can also skip this step and enter the key later in the app's **Settings** screen.

## 4. Build

```
docker compose build
```

The first build downloads Python and the packages and takes a few minutes; later builds are quick. Build again only when `pyproject.toml` or `uv.lock` changes (after a `git pull` that touches them). Code changes in `src/` and `tests/` don't need a rebuild: those folders are mounted into the container.

## 5. Start the app

```
docker compose run --rm --service-ports --name dgt-preview app python -m jobmatch.app --browser --host 0.0.0.0
```

Then open **http://localhost:8080** in your browser. It's the same app as the desktop version, in a browser tab.

- **Stop it:** press `Ctrl+C` in the terminal. If the terminal was closed, run `docker stop dgt-preview`.
- **After changing code:** stop it and start it again (it doesn't reload by itself).
- The page is only reachable from your own computer (127.0.0.1).

## 6. Get some data in

Your copy starts empty: `data/` is git-ignored because it holds contractors' personal information.

- **Contractors:** on **Find matches**, choose the contractor folder: one `.xlsx` or `.csv` file, plus an optional `resume/` folder of PDFs named by talent ID (for example `TAL-12.pdf`). Then click **Ingest**.
- **Jobs:** on **Find matches**, click **Get CSV template**, fill it in, and choose it; or use **Add a job by hand**.
- **Match:** click **Find matches**. Each job uses Gemini calls from your free daily quota; the app asks first when a run would use most of it.
- **Copying a teammate's data:** they use **Settings › Export** (a password-protected `.zip`), send you the file and tell you the password separately, and you use **Settings › Import**. Import replaces your current data (yours is kept in `data/backups/` first).

## 7. Run the checks before a pull request

```
docker compose run --rm app pytest
docker compose run --rm app ruff check .
docker compose run --rm app ruff format --check .
```

The tests use fake Gemini answers and never touch the network or your `data/` folder. They take about half a minute. GitHub runs the same checks on every push (a red ✗ on a commit means one failed).

Also add an entry to [LOG-UPDATE.md](LOG-UPDATE.md) for every commit: what it solves and how to use it.

---

## Optional: the command line

The same pipeline without the screens, for scripting and debugging. Every command starts with `docker compose run --rm app python -m jobmatch`:

```
docker compose run --rm app python -m jobmatch --help                 # every command
docker compose run --rm app python -m jobmatch validate-data          # check every CSV in data/
docker compose run --rm app python -m jobmatch llm-judge --dry-run    # calls needed, quota check; sends nothing
docker compose run --rm app python -m jobmatch run-once               # import + match, like Find matches
docker compose run --rm app python -m jobmatch export-llm-matches     # shortlists to exports/*.csv
```

More in [quick_start.md](quick_start.md) and [DEVELOPMENT.md](DEVELOPMENT.md).

## Troubleshooting

| Problem | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Start Docker Desktop and wait until it says it's running. |
| `port is already allocated` / `address already in use` (8080) | The app is already running somewhere: `docker stop dgt-preview`, or stop the other program using port 8080. |
| `Conflict. The container name "/dgt-preview" is already in use` | `docker rm -f dgt-preview`, then start again. |
| `ModuleNotFoundError` after a `git pull` | The packages changed: `docker compose build`. |
| `$'\r': command not found` in a script | The file got Windows line endings. Clone inside WSL, and run `git config --global core.autocrlf input`. |
| "Add your Gemini key in Settings" | The key is missing from `.env`: add it there or in **Settings**, then restart the app. |
| Gemini says the daily limit is reached | The free quota resets daily (midnight Pacific time). Try again tomorrow, or match fewer jobs. |

## Keep personal data safe

- Contractor files, résumés, `data/` and `exports/` contain personal information. Keep them on your own password-protected, encrypted computer; never commit them, upload them, or share them outside the team.
- Exports from **Settings › Export** are encrypted: send the password through a different channel than the file.
- Only Gemini is called, with anonymous contractor cards (no names, contact details or rates). Don't add other online services to the code without agreement (see [CLAUDE.md](../CLAUDE.md)).
