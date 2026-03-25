# CashPilot - Agent Instructions

## Project Overview

CashPilot is a self-hosted passive income orchestrator. It deploys, monitors, and manages Docker containers for bandwidth-sharing, DePIN, storage, and compute services -- all from a single web dashboard. Think of it as Portainer meets a passive-income aggregator.

## Architecture

- **Backend:** FastAPI (Python 3.12)
- **Frontend:** Jinja2 templates served by FastAPI, with static CSS/JS
- **Database:** SQLite (stored in `/data/cashpilot.db`)
- **Container management:** Docker SDK for Python, communicating via the Docker socket
- **Service definitions:** YAML files under `services/`

## Directory Structure

```
cashpilot/
  app/                  # FastAPI application
    main.py             # App entrypoint, routes
    collectors/         # Earnings collectors (one per service)
    templates/          # Jinja2 HTML templates
    static/             # CSS, JS, images
  services/             # Service YAML definitions (source of truth)
    _schema.yml         # Schema documentation for service YAMLs
    bandwidth/          # Bandwidth-sharing services (honeygain, etc.)
    compute/            # Compute-sharing services
    depin/              # DePIN services
    storage/            # Storage-sharing services
  docs/                 # User-facing documentation
    guides/             # Per-service setup guides
  scripts/              # Dev/ops helper scripts
  Dockerfile            # Multi-stage build
  docker-compose.yml    # Production deployment
  requirements.txt      # Python dependencies
```

## Service YAMLs Are the Source of Truth

Every supported income service is defined as a YAML file under `services/{category}/{slug}.yml`. These files drive:

- The web UI (service list, setup forms, environment variables)
- Container deployment (image, env, ports, volumes)
- Earnings collection (collector type and hints)
- Documentation generation (guides, README tables)

Before adding a service anywhere in the codebase, create its YAML definition first. See `services/_schema.yml` for the full schema.

## Key Conventions

- **Container naming:** All managed containers are named `cashpilot-{slug}` (e.g., `cashpilot-honeygain`).
- **Labels:** Managed containers get the label `cashpilot.managed=true` and `cashpilot.service={slug}`.
- **Data directory:** The `/data` volume holds the SQLite database and any persistent configuration. Never write outside `/data` at runtime.
- **Credentials:** User-provided secrets (service passwords, API keys) are encrypted at rest using `CASHPILOT_SECRET_KEY`.

## Development

### Running Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

The Docker socket must be accessible for container management features to work.

### Running with Docker

```bash
docker compose up -d --build
```

## Testing

- Place tests in a `tests/` directory mirroring the `app/` structure.
- Use `pytest` as the test runner.
- Mock the Docker SDK in tests; never require a live Docker socket for unit tests.
- Service YAML validation tests should load every file in `services/` and validate against the schema.

## Contribution Rules

- One PR per feature or fix. Do not bundle unrelated changes.
- Service YAMLs must follow the schema defined in `services/_schema.yml`. Missing required fields will fail CI.
- **Never edit the service table in README.md directly.** It is auto-generated. Edit the YAML in `services/`, then run `python scripts/generate_docs.py`.
- Never hardcode service-specific logic in `app/`; it belongs in the YAML or the collector.
- Keep the Docker image small (target under 100 MB). No dev dependencies in the final stage.
- All Python code must pass linting (ruff) with no errors.
