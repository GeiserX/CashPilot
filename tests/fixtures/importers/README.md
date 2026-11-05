# Importer fixtures

Written for these tests, with fake values (example.com emails, `fake-pass-...`,
made-up ids). They follow the key names, quoting and layout of the upstream
files below; no upstream file text is copied.

- money4band: `template/user-config.json` and `utils/generator.py` at
  https://github.com/MRColorR/money4band/tree/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8
  and the 3.x `.env.template` at https://github.com/MRColorR/money4band/blob/v3.4.1/.env.template
- CashFactory: `.env` at
  https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
- InternetIncome: `properties.conf` and the `earnapp.txt` / `proxyrack.txt`
  formats written by `internetIncome.sh` at
  https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5

Each tool's `template.*` file keeps the upstream placeholders, so the
placeholder detection is tested against what an untouched file looks like.
