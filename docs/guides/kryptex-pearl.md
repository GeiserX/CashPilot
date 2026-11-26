# Kryptex Pool (Pearl)

Kryptex Pool converts Pearl rewards to Bitcoin. It credits the BTC to your
Kryptex account and holds it until you request a withdrawal.

## Set up KRig

1. [Create a Kryptex account](https://pool.kryptex.com/?ref=2444cca8) and verify your email.

    <small>Referral link: the CashPilot maintainer may earn a commission from it.</small>

2. Set up a Linux amd64 CashPilot worker with an NVIDIA GPU and
   [NVIDIA Container Toolkit](../gpu.md).
3. Select **Kryptex Pool (Pearl)** in the **Mining** catalog. Enter the verified
   account email and a worker name. Use a different name for each machine.
4. Deploy. CashPilot grants one NVIDIA GPU and connects KRig to
   `prl.kryptex.network:8048` over TLS. KRig sends the username as
   `email/worker`. Check **Pool Workers** in your Kryptex account after the
   miner starts.

The deployment is beta. The first start downloads the pinned KRig release and
checks its SHA-256. The worker needs outbound HTTPS to GitHub and its release
asset host. Keep the cache volume to reuse the download. Antivirus tools can
flag mining executables. Check the version and source in the
[pinned KRig release](https://github.com/kryptex/krig-miner/releases/tag/v1.8.2).

Check your electricity costs before mining. If you rent the worker, check the
host's mining policy.

## Fees and withdrawals

KRig has a 0% miner fee on Kryptex Pool. Kryptex lists a separate 3% Pearl PPS+
pool fee. See the [Pearl pool configuration and fees](https://pool.kryptex.com/en/prl).

Check your earned balance in Kryptex. From **Request payment**, choose a payout
method and then confirm the request by email. Bitcoin Lightning starts at
0.00001 BTC and Volet starts at $1. Check the [Kryptex withdrawal limits and fees](https://www.kryptex.com/en/fees)
for the method you choose.
