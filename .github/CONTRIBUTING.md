# Contributing to CashPilot

Contributions are welcome! Here's how to get started.

## Adding a Service (easiest contribution)

This is the most impactful way to contribute. Each service is a single YAML file.

1. Create `services/{category}/{slug}.yml` following the schema in `services/_schema.yml`
2. Add a guide page at `docs/guides/{slug}.md` with setup instructions
3. Update the service table in `README.md`
4. Submit a PR

Look at any existing YAML file in `services/` for reference. Categories: `bandwidth`, `depin`, `storage`, `compute`.

## Adding an Earnings Collector

Collectors fetch balance/earnings from service APIs. See `app/collectors/` for examples.

1. Create `app/collectors/{slug}.py` extending `BaseCollector` from `app/collectors/base.py`
2. Register it in `app/collectors/__init__.py`
3. Add required credentials as `?optional` or required params

## Bug Fixes and Features

1. Fork the repo and create a branch (`fix/description` or `feature/description`)
2. Make your changes
3. Run linting: `ruff check app/ && ruff format --check app/`
4. Submit a PR with a clear description

## Code Style

- **Linter:** [Ruff](https://docs.astral.sh/ruff/) with pycodestyle, pyflakes, isort, pyupgrade, bugbear, simplify
- **Line length:** 120
- **Formatting:** Ruff formatter (double quotes, 4-space indent)

Run before committing:

```bash
ruff check app/ --fix
ruff format app/
```

## Commit Messages

Use conventional commits: `type(scope): description`

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Examples:
- `feat(collector): add Bitping earnings collector`
- `fix(deploy): handle missing Docker socket gracefully`
- `docs(service): add ProxyBase setup guide`
