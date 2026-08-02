<!--
Adding a service? It should be ONE YAML file plus an optional collector.
The README table and the guide are generated — do not hand-edit them.
-->

## Which service

- **Name:**
- **Slug:**
- **Category:** bandwidth / depin / storage / compute

## Checklist

- [ ] `services/<category>/<slug>.yml` follows `services/_schema.yml`
- [ ] Includes a `cashout` section (mandatory — how does a user get paid?)
- [ ] `referral.signup_url` is set, **with the referral code included**
- [ ] Guide generated: `python scripts/new_service_stub.py <slug>`
- [ ] README regenerated: `python scripts/generate_readme_tables.py`
- [ ] Optional: a collector in `app/collectors/` + a contract fixture in
      `tests/fixtures/collectors/<slug>.json`

## Sourcing

Values that are not in the provider's own documentation must be **left out**,
not guessed. An absent field degrades a warning; a wrong one tells the user
something false with full confidence.

- [ ] `devices_per_ip`, `residential_ip` and `vps_ip` either come from a
      first-party source, or are omitted
- [ ] If you sourced a limit, add the URL to
      `docs/research/per-ip-device-limits.md`

## Anything a human needs to know

<!-- Captcha quirks, account gotchas, whether the provider bans containers. -->
