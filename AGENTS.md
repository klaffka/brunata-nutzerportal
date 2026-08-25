# AGENTS.md

Personal project: fetch heat/hot-water consumption from the Brunata München customer portal (SAP OData) and expose it via a Home Assistant custom integration. The repo follows the HACS custom-integration layout and is published to GitHub (`klaffka`).

## Layout

- `custom_components/brunata_nutzerportal/` — the integration (single source of truth, HACS layout).
- `main.py` — standalone login + API probe script (SAP OData `$batch` login flow). Reads `.env` for `BRU_EMAIL` / `BRU_PASSWORD`.
- `test/docker-compose.yaml` — Home Assistant container (`homeassistant`, port 8123) used to test the integration; it mounts `custom_components/` into `/config/custom_components`.
- `test/ha-config/` — real HA config dir, mounted into the container as `/config` (runtime state is git-ignored).
- `test/test_coordinator_logic.py` — mock-based logic tests, no HA needed: `venv/bin/python test/test_coordinator_logic.py`.
- `notes` — raw curl captures of the portal login flow; reference material only (git-ignored, contains tokens).
- `logo.png` / `icon.png` — logo images (flame + water drop). `icon.png` (45×45) in the integration dir is picked up by HA automatically.

## Commands

- `venv/bin/python main.py` — run the standalone login script (requires `.env` with `BRU_EMAIL`, `BRU_PASSWORD`).
- `venv/bin/python test/test_coordinator_logic.py` — coordinator logic tests (mocked client + stubbed HA modules).
- `docker compose -f test/docker-compose.yaml up -d` — start HA, then use http://localhost:8123; logs in `test/ha-config/home-assistant.log` (component logging already set to debug in `configuration.yaml`).
- `docker restart homeassistant` — required after ANY change to the integration code (custom components don't reload).
- Release flow: bump `manifest.json` `version`, tag `v<version>`, push tags — HACS tracks git tags.

## Gotchas

- `venv/` is a Python 3.14 venv with `main.py` deps plus `brunata-nutzerportal-api` installed for ad-hoc API probes. If homebrew python is upgraded again, the venv breaks silently (old one died this way via python@3.13) — recreate it and reinstall `requirements.txt` + `brunata-nutzerportal-api==0.3.0`.
- `brunata_api` (imported by the integration) is NOT in this repo. It is the PyPI package `brunata-nutzerportal-api==0.3.0`, auto-installed by HA via the integration's manifest `requirements`. Never create a local `brunata_api/` package.
- Upstream bug in `brunata-nutzerportal-api==0.3.0`: the regex that inspects the inner HTTP status of the credential `$batch` has doubled backslashes and never matches — a rejected login (inner 401) is instead detected via empty `UserContextSet` results. Do not "fix" it locally; the coordinator handles it via the login-phase `LoginError`.
- The integration lives inside the HA config dir; code changes require restarting the container (`docker restart homeassistant`), not just HA's "reload".
- The SAP `$batch` request body is CRLF-sensitive (see `build_batch_body` in `main.py`) — do not "normalize" newlines. A successful login responds 202, not 200.
- `coordinator.py` maps `LoginError` raised during `client.login()` to `ConfigEntryAuthFailed` (re-auth prompt); other `LoginError`s (data fetch) become `UpdateFailed`. Don't reintroduce substring matching on error messages — the upstream package's messages are unstable.
- `.env` and `notes` contain real credentials and (expired) session tokens — never print, paste, or commit them.
- The portal account in `.env` only has a heating cost type (`HZ01`); hot-water (`WW*`) paths are untestable with it.