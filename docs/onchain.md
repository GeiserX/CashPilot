# On-chain payout balances

Open **Payouts** to see the balance at a public payout address. Bitcoin uses
[mempool.space](https://mempool.space/docs/api/rest) and Kaspa uses
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon and Solana use
public RPC nodes. CashPilot can read these addresses without a key.

| What you see | What it means |
|---|---|
| An amount | The explorer reported a balance. A reported zero appears as zero. Hover over the amount to see the source. |
| Pending | On Bitcoin, the explorer sees an unconfirmed change. A plus means funds are incoming. A minus means funds are being spent. The confirmed amount is shown separately. |
| Could not check | The explorer failed to respond or sent data CashPilot could not read. |
| Address not valid | The address failed a format check. CashPilot skipped the request. |
| Private chain | Reading a Monero balance needs your private view key. Check the balance in your wallet. CashPilot never asks you for this key. |
| A dash | There is no address or reader for this row, or the lookup is off. When a setting turns the lookup off, hover over the dash to see which one. |

Kaspa's public endpoint reports one balance. It supplies no separate pending
amount.

The on-chain column shows the balance at the address right now. It can include
transfers from other sources. The pool's unpaid balance shows what the pool
still holds for you. An OCEAN payout over Lightning does not appear in the
on-chain balance. The balance also cannot tell you which transfers came from
your pool.

## Choose where the lookup goes

Each lookup shares your public payout address and the UI server's IP with the
explorer. The explorer can link addresses you check from the same IP.

Set the base URL in the UI container's environment if you run your own node.
Leave the variable unset to use the default. Set it to an empty value to turn
off the lookup for that chain.

For example, a Compose override for the UI service could contain:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Use the Esplora or Kaspa API base URL when configuring Bitcoin or Kaspa.
For Ethereum, Polygon and Solana, set the corresponding variables
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` or
`CASHPILOT_ONCHAIN_URL_SOLANA` to a node's RPC URL. Use an HTTP or HTTPS URL
without credentials, a query string or a fragment. Apply the change by
recreating the UI container with the new environment.
