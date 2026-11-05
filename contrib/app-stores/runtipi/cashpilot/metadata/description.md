# CashPilot

CashPilot runs passive income services on your own server and shows what they earn in one web dashboard. It covers bandwidth sharing, DePIN, storage and GPU compute services.

- Start a service from the catalog with one click, with no compose file to write.
- Balances are kept as history. A balance drop is offered to you as a probable payout to confirm.
- Stored credentials are encrypted at rest.
- One worker per server and one dashboard run a whole fleet.

## Before you install

- The app has two containers. Only the worker mounts the Docker socket, which it needs to start and stop the service containers. The Docker socket gives root on the host.
- The dashboard can command the worker, so keep it on your LAN or VPN and do not expose it to the internet.
- For that reason the package turns off Runtipi's reverse proxy options (public and local domains). Open the dashboard at your server's address on the app port.
- On the first visit CashPilot asks for a setup token. Find it in the logs of the `cashpilot` container, in the line that says "setup token". It then creates the owner account and opens the setup wizard.
- Back up `data/ui/.fernet_key` in the app's data folder. Without it the stored credentials cannot be decrypted.

## Links

- Source: https://github.com/GeiserX/CashPilot
- Documentation: https://geiserx.github.io/CashPilot/
