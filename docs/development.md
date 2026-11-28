# Development

Contributions are welcome. To add a new service:

1. Create a YAML file in the appropriate `services/` subdirectory following `services/_schema.yml`
2. Generate the guide page with `python scripts/new_service_stub.py <slug>`, then write the parts that need a human (CI fails if a service has no guide)
3. Regenerate the service tables in the README with `python scripts/generate_readme_tables.py`, and the guide navigation and index with `python scripts/sync_docs_nav.py` (CI fails if either drifts from the YAML)
4. Submit a pull request

For bug reports and feature requests, open an issue on GitHub.

For UI work, `uv run python scripts/ui_demo_seed.py /tmp/cp-demo --serve 8100` serves the app with invented demo data (login `demo` / `demo-password-1`), and never touches a real data dir.
`node scripts/ui_screenshots.mjs http://127.0.0.1:8100 /tmp/shots all` then takes full-page shots of every page and state in every theme in `app/themes.json`: Classic night (the default, no suffix), then `-dark`, `-light`, `-sunrise` and `-warm`. Pass one theme id instead of `all` for just that one. `CP_SCALE=2` takes retina shots, `CP_SHOT_ONLY=<regex>` picks states.

## Translating the docs

The docs site is in English and 19 other languages. Each language lives at its own path (`/es/`, `/ja/`…) and is a separate build of the same pages, made by `.github/scripts/docs-i18n.py`. A page with no translation shows the English page with a note.

To translate a page, or to fix a translation:

1. Write the page at `docs/i18n/<lang>/<path>.md`, for example `docs/i18n/es/faq.md` for `docs/faq.md`. The language codes are the `lang` values of `extra.alternate` in `zensical.toml`. Use the words in `i18n/glossary.yml`.
2. Put the English page's hash in the front matter: `source_hash: <hash>`. `check` prints the hash it expects when a page has none. When the English page changes later, the translation shows a note that links the newer English page until someone updates it.
3. Never translate code blocks, inline code, commands, environment variables, file paths or link targets. Referral links stay exactly as they are, and their disclosure lines are translated in full.
   Copy each count marker such as `<!-- n:docker -->21<!-- /n -->` as it is: the build fills in the number from the catalog, and `check` fails on a count typed without its marker.
4. Keep each heading's English id, so links into the page still work: `## Preguntas frecuentes { #frequently-asked-questions }`. After an English build, `python .github/scripts/docs-i18n.py anchors faq.md` lists them.
5. Translate the navigation labels and the notes in `docs/i18n/<lang>/locale.toml`.
6. Run the same checks as CI:

```bash
python -I .github/scripts/docs-i18n.py check
python -m zensical build --clean --strict
python -I .github/scripts/docs-i18n.py build
python -I .github/scripts/site-check.py site
```

Pages that stay in English on purpose are listed in `docs/i18n/config.toml`.
