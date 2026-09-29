# Development

Contributions are welcome. To add a new service:

1. Create a YAML file in the appropriate `services/` subdirectory following `services/_schema.yml`
2. Add a guide page in `docs/guides/` for the service
3. Regenerate the service tables in the README with `python scripts/generate_readme_tables.py` (CI fails if they drift from the YAML)
4. Submit a pull request

For bug reports and feature requests, open an issue on GitHub.
