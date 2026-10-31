# Development

Contributions are welcome. To add a new service:

1. Create a YAML file in the appropriate `services/` subdirectory following `services/_schema.yml`
2. Generate the guide page with `python scripts/new_service_stub.py <slug>`, then write the parts that need a human (CI fails if a service has no guide)
3. Regenerate the service tables in the README with `python scripts/generate_readme_tables.py`, and the guide navigation and index with `python scripts/sync_docs_nav.py` (CI fails if either drifts from the YAML)
4. Submit a pull request

For bug reports and feature requests, open an issue on GitHub.

For UI work, `uv run python scripts/ui_demo_seed.py /tmp/cp-demo --serve 8100` serves the app with invented demo data (login `demo` / `demo-password-1`), and never touches a real data dir.
`node scripts/ui_screenshots.mjs http://127.0.0.1:8100 /tmp/shots both` then takes full-page shots of every page and state in both themes (`CP_SCALE=2` for retina, `CP_SHOT_ONLY=<regex>` to pick states).
