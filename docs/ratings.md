# Provider ratings

Every provider CashPilot can run or track gets a letter grade. The grade comes from the same ten questions, asked of every provider the same way, and each answer rests on a source you can open: the provider's own terms or help pages, its replies to users, a repeated pattern in user reports, or what happened when we ran it and cashed out.

Nobody types a grade. Each provider's entry in the catalog records a verdict per question (good, fair, poor or unknown) with the cons and pros behind it, and the code turns those verdicts into the letter. The entry has no field for a grade or an override, and a catalog entry that tries is shown as not rated and fails our checks. The web app and CashPilot-Desktop both show the grade, computed from the same published method.

## Why nothing gets an A

No provider gets an A. An A would mean we vouch for a provider, and we cannot: we can check what it publishes and what its users report, not what it will do with your account or your connection tomorrow. The best grade is B.

## How to read a grade

- **B**: the provider does most things well and the evidence says so. Still read the cons.
- **C**: real drawbacks, or too little evidence to say more.
- **D**: serious drawbacks, or most of the criteria could not be checked.
- **F**: the evidence we have is poor, or almost nothing could be checked. The "Unchecked" column tells the two apart: a low grade with many unchecked criteria means "we could not verify this provider", not "we found it bad".

**Unknown is not a pass.** When we could not find evidence either way, the verdict is unknown and it scores the same as poor. A provider with four or more unknowns is capped at C for thin evidence, and its score usually puts it lower still. New and token-based projects often land at D or F this way: that says how little can be verified about them, which is itself worth knowing before you hand one your connection.

## Which complaints count

Review sites collect plenty of single angry posts. One post is not evidence. A con from user reports needs a pattern: at least three reviewers or posters describing the same specific problem, or two backed by an independent second source. Fewer than that, and the verdict stays unknown with a note saying what we found. A provider's own reply that confirms the rule behind a ban counts as the provider's word. Every con and pro shows the date we checked it, because review pages change.

## Disputing a grade

If a con is wrong or out of date, open an issue at https://github.com/GeiserX/CashPilot/issues with a source that shows it. A grade changes only when a verdict changes, and a verdict changes only on evidence. That applies to providers too.

<!-- BEGIN GENERATED: ratings -->

## The criteria

| Criterion | The question | Good | Fair | Poor |
|---|---|---|---|---|
| Payout record | Do payouts arrive, and on time? | Payouts arrive, shown by our own payout or by many matching user reports, and reports of late or missing ones are rare. | Payouts arrive, but there is a repeated pattern of delays or of payouts held for review. | Repeated, specific reports of payouts that never arrived, or the provider stopped paying. |
| Payout terms | How high is the minimum, which methods are there, what are the fees, and does a balance expire? | A low minimum, a common method such as PayPal or bank transfer, small fees and no expiry. | One of these is a real obstacle, such as a high minimum, crypto only, a large fee or an expiring balance. | Several of them at once, or terms that let the provider keep a balance you earned. |
| Account safety | Do accounts get banned, and is the balance confiscated, especially at cash-out? | Bans are rare and follow a stated rule; a banned account keeps or is paid its balance. | The terms let the provider keep the balance of a banned account, but there is no repeated pattern of it. | A repeated pattern of accounts banned at or near cash-out with the balance kept. |
| Fit with how CashPilot runs it | Do the terms allow running it the way CashPilot does, in a container on a home server? | Containers or servers are allowed, or the official client is a container image. | The terms are silent on containers, or allow them with conditions such as one device per IP, or CashPilot does not run the provider at all (it is an app, extension or device you set up yourself), so the question does not apply. | The terms forbid containers, virtual machines or servers. |
| Traffic transparency | Does the provider say who buys the traffic or the work, and how buyers are vetted? | It names the kind of buyers, states what they may not do, and describes how it checks them. | It names the use in general terms, without saying how buyers are checked. | It does not say who uses your connection or machine. |
| Privacy | What leaves your machine, and can anyone check what the client does? | The client is open source, or the provider publishes exactly what it collects and it is little. | A privacy policy covers it, but the client is closed and the data collected is broad. | The data collected is excessive, or the provider has had a data incident it handled badly. |
| Identity checks | What do you hand over to get paid, such as a phone number, an ID document or tax details? | An email address and a payout address are enough. | A phone number, a payment processor's own checks, or a tax form for larger amounts. | A government ID or selfie is required before any payout. |
| Support | Are support tickets answered? | Tickets are answered, including ours, and reports of being ignored are rare. | Answers come, but slowly, or only through a community channel. | A repeated pattern of tickets left unanswered, often while a payout is held. |
| Earnings realism | How do advertised earnings compare with what one home IP actually makes? | The provider's claims match what we and other users measure. | Claims are optimistic, or earnings depend heavily on location and are small for most. | Advertised earnings are far above what users report, or rewards are in a token with no settled value. |
| Longevity | Is there a named company, how long has it run, and has it shut down or rebranded before? | A named legal entity, several years of operation and no history of shutdowns or rebrands. | A named entity but under three years running, or a past rebrand or relaunch. | No named entity, or a history of shutdowns, or a token or program that was wound down. |

Each verdict scores points: good 2, fair 1, poor 0, unknown 0. Unknown scores the same as poor, so a provider we could not check is graded as cautiously as one with bad evidence.

| Grade | Share of the maximum score |
|---|---|
| B | 75% or more |
| C | 55% or more |
| D | 35% or more |
| F | 0% or more |

Ceilings, applied whatever the score:

- **Capped at D.** The provider forbids running its software in a container, which is how CashPilot runs it.
- **Capped at C.** A poor payout record or poor account safety caps the grade at C.
- **Capped at C.** Four or more criteria could not be checked, so the grade is capped at C for thin evidence.

What a cited con or pro may rest on:

- `terms`: The provider's own terms, help centre or documentation.
- `provider_reply`: The provider's own reply to a user, for example on a review site.
- `our_experience`: What happened when we ran it or cashed out, written up in this repo.
- `user_reports`: A pattern in user reports, never a single complaint. At least three reviewers or posters describing the same specific problem, or two backed by an independent second source. An aggregate summary written by the review site counts as one source.
- `press`: A news article, a court record or a public filing.

## All providers

| Provider | Grade | Score | Unchecked | Reviewed | Worst con |
|---|:---:|:---:|:---:|---|---|
| <a href="#sia-hostd">Sia (hostd)</a> | C | 12 of 20 | 2 | 2026-11-04 | Renters store encrypted file fragments and nobody routes traffic through your IP, but we did not find where Sia says who the renters are or how they are checked. |
| <a href="#mysterium">MystNodes</a> | D | 10 of 20 | 4 | 2026-11-04 | About 21% of every settlement goes in fees, the 20% Hermes fee plus a transaction fee, and earnings are paid in the MYST token. |
| <a href="#packetstream">PacketStream</a> | D | 10 of 20 | 2 | 2026-11-04 | Trustpilot reviewers in 2025 and 2026 report payouts arriving late or not at all, and one long-time user says payouts slowed and then stopped; others in 2026 report being paid. |
| <a href="#proxybase">ProxyBase</a> | D | 9 of 20 | 4 | 2026-11-04 | Crypto only, as USDC on Polygon, POL or Litecoin, with no fiat method. The minimum is $0.20 and ProxyBase pays the network fee. |
| <a href="#storj">Storj</a> | D | 9 of 20 | 3 | 2026-11-04 | Customers store encrypted file fragments and nobody routes traffic through your IP, but we did not find where Storj says who the customers are or how they are checked. |
| <a href="#honeygain">Honeygain</a> | D | 8 of 20 | 3 | 2026-11-04 | The terms let Honeygain write off earnings that reached the $20 threshold and were not paid out within 24 months, and treat earnings as expired after six months without use. |
| <a href="#earnapp">EarnApp</a> | D | 7 of 20 | 5 | 2026-11-04 | EarnApp's help centre says installing it in Docker containers, virtual machines, hosting services or home servers is strictly prohibited, which is how CashPilot runs it. |
| <a href="#golem">Golem Network</a> | D | 7 of 20 | 5 | 2026-11-04 | CashPilot does not run Golem: you install the provider agent yourself, so CashPilot cannot deploy or update it for you. Golem documents running the provider in its own Docker image. |
| <a href="#urnetwork">URnetwork</a> | D | 7 of 20 | 4 | 2026-11-04 | Unclaimed epochs expire, and the old USDC payouts were cancelled for networks with no wallet linked within 30 days. |
| <a href="#anyone-protocol">Anyone Protocol</a> | F | 6 of 20 | 5 | 2026-11-04 | A relay earns nothing unless 100 ANYONE is locked for it for at least 180 days, and each reward claim is signed in your wallet. |
| <a href="#bytelixir">Bytelixir</a> | F | 6 of 20 | 6 | 2026-11-04 | Crypto only, and the minimum depends on the coin, from $5 for USDT to $250 for Bitcoin. |
| <a href="#noderr">Noderr Micronodes</a> | F | 6 of 20 | 4 | 2026-11-04 | Node rewards are unfunded testnet tokens with no market value, and none have been paid; the 5 to 10% APY on its site is a design target. |
| <a href="#proxybase-xyz">ProxyBase Markets</a> | F | 6 of 20 | 6 | 2026-11-04 | Payouts are USDC on Tempo Chain and need a Tempo wallet address. |
| <a href="#repocket">Repocket</a> | F | 6 of 20 | 2 | 2026-11-04 | Several Trustpilot reviewers report cancelled payouts and balances reset to zero; one says support cited irregular bandwidth earnings. The page rates Repocket 2.7 and notes it has not replied to negative reviews. |
| <a href="#bitping">Bitping</a> | F | 5 of 20 | 7 | 2026-11-04 | Withdrawals are paid in Solana (SOL), to an address you type into each request. |
| <a href="#earnfm">Earn.fm</a> | F | 5 of 20 | 6 | 2026-11-04 | A $15 minimum, a $1 to $3 fee on USDT, and a bank wire only from $1,000. |
| <a href="#ebesucher">Ebesucher</a> | F | 5 of 20 | 7 | 2026-11-04 | CashPilot does not run eBesucher: it is a browser extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. |
| <a href="#flux">Flux</a> | F | 5 of 20 | 6 | 2026-11-04 | The smallest node tier needs 1,000 FLUX locked as collateral. |
| <a href="#iproyal">IPRoyal Pawns</a> | F | 5 of 20 | 4 | 2026-11-04 | The terms say an account can be blocked without prior notice for abuse of withdrawal conditions or multiple accounts, and its earnings may then not be paid out. |
| <a href="#sentinel-dvpn">Sentinel dVPN</a> | F | 5 of 20 | 6 | 2026-11-04 | Payments are in the P2P token, and 20% of every bandwidth payment goes to stakers rather than the node host. |
| <a href="#traffmonetizer">Traffmonetizer</a> | F | 5 of 20 | 4 | 2026-11-04 | Trustpilot rates it 1.9; reviewers from 2023 to November 2026 report payouts pending for weeks, or marked completed with no matching transaction. |
| <a href="#helium">Helium</a> | F | 4 of 20 | 6 | 2026-11-04 | HIP 149 retired Proof-of-Coverage rewards on 6 July 2026; IoT hotspots now earn only for data they carry, and more than 114,000 of them carried none. |
| <a href="#proxylite">ProxyLite</a> | F | 4 of 20 | 7 | 2026-11-04 | The site's owner is hidden in its domain records, and we found no named company behind it. |
| <a href="#salad">Salad</a> | F | 4 of 20 | 7 | 2026-11-04 | Rewards are redeemed in Salad's own storefront for PayPal or gift cards, with no crypto. Trustpilot's summary says some payment methods are hard to use in some regions, and reviewers describe a Visa card that cannot be added to Apple Pay in Europe and no payout option for India. |
| <a href="#vast-ai">Vast.ai</a> | F | 4 of 20 | 7 | 2026-11-04 | CashPilot does not run Vast.ai: you install Vast's host software on your own GPU machine, so CashPilot cannot deploy or update it for you. Vast builds hosting around Docker on a Linux host. |
| <a href="#bytebenefit">Bytebenefit</a> | F | 3 of 20 | 7 | 2026-11-04 | The app's Google Play listing says your traffic serves web-intelligence requests by Infatica's clients, without saying who they are or how they are checked. |
| <a href="#grass">Grass</a> | F | 3 of 20 | 6 | 2026-11-04 | Rewards come only through airdrop seasons. Long-running node operators reported season 2 estimates in the single to low double-digit dollar range. |
| <a href="#ionet">io.net</a> | F | 3 of 20 | 6 | 2026-11-04 | Supplier rewards were paid from token emissions regardless of paid jobs, and GPU owners report sitting idle most of the time. |
| <a href="#nodepay">Nodepay</a> | F | 3 of 20 | 6 | 2026-11-04 | In its first season review Nodepay removed more than 300,000 accounts it judged to be bots and cancelled 17 billion points. |
| <a href="#nosana">Nosana</a> | F | 3 of 20 | 7 | 2026-11-04 | Each host must lock a NOS stake sized to its GPU's hourly price. |
| <a href="#passiveapp">PassiveApp</a> | F | 3 of 20 | 8 | 2026-11-04 | CashPilot does not run PassiveApp: you use the provider's own desktop app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. |
| <a href="#proxyrack">ProxyRack</a> | F | 3 of 20 | 8 | 2026-11-04 | ProxyRack's help centre says removing a device takes that device's earnings off your account, and they come back only if the same device is added again. |
| <a href="#gradient">Gradient Network</a> | F | 2 of 20 | 6 | 2026-11-04 | The Sentry Node points program ended on 28 August 2025, and Sentry nodes no longer earn rewards. |
| <a href="#nodle">Nodle</a> | F | 2 of 20 | 7 | 2026-11-04 | App Store reviewers report being unable to bridge or send NODL after the move to zkSync, and needing ETH to move tokens out. |
| <a href="#uprock">Uprock</a> | F | 2 of 20 | 7 | 2026-11-04 | Trustpilot reviewers reported a 255 UPT minimum and a 55 UPT fee to withdraw to a wallet; these reports are old and the current terms may differ. |
| <a href="#dawn">Dawn Internet</a> | F | 1 of 20 | 7 | 2026-11-04 | The extension earns points; no token distribution to node operators had been confirmed by October 2026. |
| <a href="#deeper-network">Deeper Network</a> | F | 1 of 20 | 8 | 2026-11-04 | Mining rewards are in DPR and depend on a credit score that grows slowly or by staking DPR. |
| <a href="#spide">Spide</a> | F | 1 of 20 | 9 | 2026-11-04 | CashPilot does not run Spide: you use the provider's own app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. |
| <a href="#teneo">Teneo Protocol</a> | F | 1 of 20 | 7 | 2026-11-04 | Teneo says points will be consolidated into $AGENTIC, a non-transferable reward token, not the $TENEO token. |
| <a href="#theta-edge">Theta Edge Node</a> | F | 1 of 20 | 9 | 2026-11-04 | CashPilot does not run Theta Edge: you use the provider's own desktop app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. |
| <a href="#titan">Titan Network</a> | F | 1 of 20 | 8 | 2026-11-04 | Titan's own help says a running node does not guarantee earnings: with no task assigned it earns nothing, and rewards are in the TNT token. |

## Provider details

<a id="sia-hostd"></a>

### Sia (hostd)

**Grade C**, 12 of 20 points, 2 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Sia (hostd)](guides/sia-hostd.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Payment is by on-chain contract; we have no host of our own to report. |
| Payout terms | Fair |  |
| Account safety | Fair |  |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Fair |  |
| Privacy | Good |  |
| Identity checks | Good |  |
| Support | Unknown | No pattern found. |
| Earnings realism | Fair |  |
| Longevity | Good |  |

**Cons**

- Renters store encrypted file fragments and nobody routes traffic through your IP, but we did not find where Sia says who the renters are or how they are checked. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/storage/sia-hostd.yml), checked 2026-11-04.
- Earnings are Siacoin in your own wallet: there is no payout to a bank, so you sell on an exchange yourself. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/storage/sia-hostd.yml), checked 2026-11-04.
- Collateral is locked per contract and burned if the host misses storage proofs by going offline or losing data. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/storage/sia-hostd.yml), checked 2026-11-04.
- Only about 30% of the storage offered on the network is in use, so a new host competes for little demand. [Source](https://sia.tech/provide-storage), checked 2026-11-04.

**Pros**

- hostd is developed in the open by the Sia Foundation, since 2022. [Source](https://github.com/SiaFoundation/hostd), checked 2026-11-04.
- hostd is open source under the MIT licence. [Source](https://github.com/SiaFoundation/hostd), checked 2026-11-04.
- The Sia Foundation publishes hostd as a container image. [Source](https://github.com/SiaFoundation/hostd), checked 2026-11-04.
- Permissionless: no signup or account. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/storage/sia-hostd.yml), checked 2026-11-04.

<a id="mysterium"></a>

### MystNodes

**Grade D**, 10 of 20 points, 4 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [MystNodes](guides/mysterium.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Settlements are on-chain and automatic; we have not published our own settlement history yet. |
| Payout terms | Fair |  |
| Account safety | Unknown | Settled earnings sit in a wallet you own, but we found no stated ban rule and no reports either way. |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Fair |  |
| Privacy | Good |  |
| Identity checks | Good |  |
| Support | Unknown | Trustpilot has 16 reviews and none in the last year; not enough to judge. |
| Earnings realism | Unknown | Not measured against a provider figure. |
| Longevity | Good |  |

**Cons**

- About 21% of every settlement goes in fees, the 20% Hermes fee plus a transaction fee, and earnings are paid in the MYST token. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/mysterium.yml), checked 2026-11-04.
- Your node is an exit for Mysterium's VPN, proxy and data-scraping customers, and you cannot choose which of them it carries. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/mysterium.yml), checked 2026-11-04.

**Pros**

- The node software is open source under the GPL-3.0. [Source](https://github.com/mysteriumnetwork/node), checked 2026-11-04.
- Mysterium publishes its own Docker image, mysteriumnetwork/myst. [Source](https://hub.docker.com/r/mysteriumnetwork/myst), checked 2026-11-04.
- Settlement goes to a wallet you own; no phone number or ID is needed. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/mysterium.yml), checked 2026-11-04.
- The node project has run since 2017. [Source](https://github.com/mysteriumnetwork/node), checked 2026-11-04.

<a id="packetstream"></a>

### PacketStream

**Grade D**, 10 of 20 points, 2 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [PacketStream](guides/packetstream.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Fair |  |
| Payout terms | Fair |  |
| Account safety | Fair |  |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Fair |  |
| Privacy | Unknown | The client is closed source; we did not review the privacy policy in depth. |
| Identity checks | Good |  |
| Support | Poor |  |
| Earnings realism | Unknown | Two Trustpilot reviewers report close to a year to reach the $5 minimum; two is below our user-reports threshold and we found no second source. |
| Longevity | Good |  |

**Cons**

- Trustpilot reviewers in 2025 and 2026 report payouts arriving late or not at all, and one long-time user says payouts slowed and then stopped; others in 2026 report being paid. [Source](https://www.trustpilot.com/review/packetstream.io), checked 2026-11-04.
- PayPal only, with a 3% cashout fee; users in countries PayPal does not serve have no other method. [Source](https://packetstream.io/terms-of-service/), checked 2026-11-04.
- The terms let PacketStream withhold, reverse or invalidate earnings it ties to fraud, manipulation or prohibited activity. [Source](https://packetstream.io/terms-of-service/), checked 2026-11-04.
- The terms say proxy customers and PacketStream itself route traffic through your connection; they describe no vetting of ordinary buyers. [Source](https://packetstream.io/terms-of-service/), checked 2026-11-04.
- Trustpilot notes PacketStream has not replied to negative reviews; reviewers report unanswered emails. [Source](https://www.trustpilot.com/review/packetstream.io), checked 2026-11-04.

**Pros**

- PacketStream publishes its own Docker image, packetstream/psclient, and its terms only require a device and connection you own or may use. [Source](https://packetstream.io/terms-of-service/), checked 2026-11-04.
- The terms describe no identity check; a payout needs a PayPal address. [Source](https://packetstream.io/terms-of-service/), checked 2026-11-04.
- The terms name PacketStream Inc. under California law. [Source](https://packetstream.io/terms-of-service/), checked 2026-11-04.
- PacketStream has run since 2018. [Source](https://proxyway.com/reviews/packetstream-proxies), checked 2026-11-04.

<a id="proxybase"></a>

### ProxyBase

**Grade D**, 9 of 20 points, 4 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [ProxyBase](guides/proxybase.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Good |  |
| Payout terms | Fair |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Unknown | We did not find who buys the traffic or how buyers are checked. |
| Privacy | Unknown | The peer client is closed source. |
| Identity checks | Good |  |
| Support | Unknown | No reports found. |
| Earnings realism | Fair |  |
| Longevity | Fair |  |

**Cons**

- Crypto only, as USDC on Polygon, POL or Litecoin, with no fiat method. The minimum is $0.20 and ProxyBase pays the network fee. [Source](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/proxybase.md), checked 2026-11-04.
- ProxyBase itself wrote in August 2025 that it is new and not yet the place to maximise earnings. [Source](https://github.com/engageub/InternetIncome/discussions/239), checked 2026-11-04.
- ProxyBase switched peer clients in 2026 and shut the old backend, so containers on the old image kept running and stopped earning. [Source](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/proxybase.md), checked 2026-11-04.

**Pros**

- Our $0.75 withdrawal went through in October 2026. [Source](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/proxybase.md), checked 2026-11-04.
- A withdrawal needs only an address typed into the request. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/proxybase.yml), checked 2026-11-04.
- ProxyBase publishes its own peer client image and supports datacentre IPs. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/proxybase.yml), checked 2026-11-04.

<a id="storj"></a>

### Storj

**Grade D**, 9 of 20 points, 3 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Storj](guides/storj.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Fair |  |
| Payout terms | Fair |  |
| Account safety | Unknown | Nodes are permissionless; disqualification for lost data is the stated rule, and we found no pattern of disputes. |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Fair |  |
| Privacy | Good |  |
| Identity checks | Good |  |
| Support | Unknown | No pattern found. |
| Earnings realism | Unknown | Not measured against a provider figure. |
| Longevity | Poor |  |

**Cons**

- Customers store encrypted file fragments and nobody routes traffic through your IP, but we did not find where Storj says who the customers are or how they are checked. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/storage/storj.yml), checked 2026-11-04.
- Storj Labs filed for Chapter 11 on 26 July 2026; node earnings from before the filing are frozen until the court rules. [Source](https://www.coindesk.com/business/2026/07/27/cloud-data-firm-storj-files-for-chapter-11-extending-a-week-of-crypto-failures-token-slides-16), checked 2026-11-04.
- Pre-filing payments to node operators went into the bankruptcy claims process. [Source](https://www.cryptotimes.io/2026/07/27/storj-files-for-chapter-11-pre-filing-node-operator-payments-in-limbo/), checked 2026-11-04.
- A new node has 75%, then 50%, then 25% of its earnings held in its first nine months; half comes back in month 16 and the rest only on a graceful exit. [Source](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/storj.md), checked 2026-11-04.

**Pros**

- The storage node software is open source under the AGPL-3.0. [Source](https://github.com/storj/storj), checked 2026-11-04.
- Storj publishes its own Docker image, storjlabs/storagenode. [Source](https://hub.docker.com/r/storjlabs/storagenode), checked 2026-11-04.
- No account: a wallet address and an email for operator notices. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/storage/storj.yml), checked 2026-11-04.
- Active nodes kept being paid after the filing. [Source](https://startupfortune.com/storj-labs-filed-for-chapter-11-bankruptcy-and-token-holders-are-last-in-line/), checked 2026-11-04.

<a id="honeygain"></a>

### Honeygain

**Grade D**, 8 of 20 points, 3 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Honeygain](guides/honeygain.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Trustpilot withholds Honeygain's rating for a breach of its guidelines and says it removed fake reviews, so its review pages cannot show a payout record either way. We have not yet published a completed Honeygain payout of our own. |
| Payout terms | Poor |  |
| Account safety | Fair |  |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Fair |  |
| Privacy | Unknown | The client is closed source. We did not find a published list of what the client collects beyond the privacy policy's general terms. |
| Identity checks | Fair |  |
| Support | Unknown | Two recent Trustpilot reviews say support did not answer; two is not a pattern, and we have no ticket of our own. |
| Earnings realism | Fair |  |
| Longevity | Good |  |

**Cons**

- The terms let Honeygain write off earnings that reached the $20 threshold and were not paid out within 24 months, and treat earnings as expired after six months without use. [Source](https://www.honeygain.com/terms-of-use/), checked 2026-11-04.
- The minimum is $20, and PayPal payouts go through Tipalti, which charges $2.02 per payment. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/honeygain.yml), checked 2026-11-04.
- The terms let Honeygain suspend an account and withhold or write off earnings it considers accumulated under false pretenses. [Source](https://www.honeygain.com/terms-of-use/), checked 2026-11-04.
- Before the first PayPal payout, Tipalti makes you confirm a mobile number by SMS and give your name, address and date of birth. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/honeygain.yml), checked 2026-11-04.
- The terms say business clients use the traffic to gather publicly available web data, but name no client, and you cannot know which client uses your connection. [Source](https://www.honeygain.com/terms-of-use/), checked 2026-11-04.
- Honeygain's own replies to low-earnings reviews say earnings depend on network demand and location; reviewers report taking a very long time to reach the $20 minimum. [Source](https://www.trustpilot.com/review/honeygain.com), checked 2026-11-04.

**Pros**

- Honeygain publishes its own Docker image, honeygain/honeygain. [Source](https://hub.docker.com/r/honeygain/honeygain), checked 2026-11-04.
- The terms name the operator, Honeygain UAB, registered in Vilnius, Lithuania. [Source](https://www.honeygain.com/terms-of-use/), checked 2026-11-04.
- Honeygain's press page says it was founded in 2019. [Source](https://www.honeygain.com/press-area/), checked 2026-11-04.

<a id="earnapp"></a>

### EarnApp

**Grade D**, 7 of 20 points, 5 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [EarnApp](guides/earnapp.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Good |  |
| Payout terms | Good |  |
| Account safety | Fair | We found no repeated pattern of accounts banned at cash-out with the balance kept. Trustpilot withholds EarnApp's rating for a breach of its guidelines and says it removed fake reviews, so we did not count its reviews either way. |
| Fit with how CashPilot runs it | Poor |  |
| Traffic transparency | Unknown | EarnApp is run by Bright Data; we did not find an EarnApp page that says how the buyers of the traffic are vetted. |
| Privacy | Unknown | The client is closed source; we did not review the privacy policy in depth. |
| Identity checks | Unknown | We found no EarnApp page that lists what a payout asks for, and our own notes do not record it. |
| Support | Unknown | One Trustpilot review says a ticket was closed without a reply; one is not a pattern, and we have no ticket of our own. |
| Earnings realism | Unknown | We have not measured EarnApp's earnings per IP against any figure the provider publishes. |
| Longevity | Good |  |

**Cons**

- EarnApp's help centre says installing it in Docker containers, virtual machines, hosting services or home servers is strictly prohibited, which is how CashPilot runs it. [Source](https://help.earnapp.com/hc/en-us/articles/10199416541969--Can-I-install-EarnApp-on-Hosting-Services-Virtual-Machines-or-Dockers), checked 2026-11-04.
- The same help article says an account found running that way is terminated without notice and its pending payments are cancelled. [Source](https://help.earnapp.com/hc/en-us/articles/10199416541969--Can-I-install-EarnApp-on-Hosting-Services-Virtual-Machines-or-Dockers), checked 2026-11-04.

**Pros**

- Our PayPal payout arrived in October 2026: a $37.54 balance came in as $36.81, about 2% less. [Source](https://github.com/GeiserX/CashPilot/blob/main/docs/guides/earnapp.md), checked 2026-11-04.
- A $10 minimum for PayPal and Wise, with auto-redeem that pays out by itself. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/earnapp.yml), checked 2026-11-04.
- EarnApp belongs to Bright Data, and its PayPal payments arrive from Bright Data Ltd., a named company. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/earnapp.yml), checked 2026-11-04.

<a id="golem"></a>

### Golem Network

**Grade D**, 7 of 20 points, 5 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Golem Network](guides/golem.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Payments are on-chain per task; we have no provider of our own to report. |
| Payout terms | Unknown | Payments are in GLM on Polygon; we did not find fees worth grading. |
| Account safety | Unknown | There is no account to ban. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Requestors run tasks on your machine; we did not find how they are checked. |
| Privacy | Good |  |
| Identity checks | Good |  |
| Support | Unknown | No pattern found. |
| Earnings realism | Poor |  |
| Longevity | Good |  |

**Cons**

- CashPilot does not run Golem: you install the provider agent yourself, so CashPilot cannot deploy or update it for you. Golem documents running the provider in its own Docker image. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/compute/golem.yml), checked 2026-11-04.
- A 2026 review finds Golem with no protocol revenue and low demand, so providers earn little and are paid in GLM. [Source](https://ownyourmind.ai/projects/golem/), checked 2026-11-04.

**Pros**

- The provider agent, yagna, is open source under the GPL-3.0. [Source](https://github.com/golemfactory/yagna), checked 2026-11-04.
- No account: you set a payout wallet in the provider setup. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/compute/golem.yml), checked 2026-11-04.
- The network has run for about ten years. [Source](https://ownyourmind.ai/tokenomics/akash-vs-golem/), checked 2026-11-04.

<a id="urnetwork"></a>

### URnetwork

**Grade D**, 7 of 20 points, 4 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [URnetwork](guides/urnetwork.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | The payout system changed in October 2026; we have no completed claim of our own to report. |
| Payout terms | Poor |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Unknown | We did not find how buyers of the traffic are checked. |
| Privacy | Good |  |
| Identity checks | Good |  |
| Support | Unknown | URnetwork's support answered our email about the new payout page; one ticket is not a record. |
| Earnings realism | Poor |  |
| Longevity | Fair |  |

**Cons**

- Unclaimed epochs expire, and the old USDC payouts were cancelled for networks with no wallet linked within 30 days. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/urnetwork.yml), checked 2026-11-04.
- Since October 2026 rewards are paid in SN25α, a Bittensor subnet token, and each claim costs gas in TAO. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/urnetwork.yml), checked 2026-11-04.
- URnetwork was formerly BringYour; its archived whitepaper carries the old name. [Source](https://docs.ur.io/archive/whitepaper), checked 2026-11-04.

**Pros**

- URnetwork publishes the source code of its provider client. [Source](https://github.com/urnetwork/connect), checked 2026-11-04.
- URnetwork publishes its own Docker image, bringyour/community-provider, and works on VPS and residential connections. [Source](https://hub.docker.com/r/bringyour/community-provider), checked 2026-11-04.
- A claim needs only a Bittensor wallet you control. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/urnetwork.yml), checked 2026-11-04.

<a id="anyone-protocol"></a>

### Anyone Protocol

**Grade F**, 6 of 20 points, 5 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Anyone Protocol](guides/anyone-protocol.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We have not published a reward claim of our own and found no pattern of reports. |
| Payout terms | Poor |  |
| Account safety | Unknown | There is no account to ban. |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Poor |  |
| Privacy | Good |  |
| Identity checks | Good |  |
| Support | Unknown | No pattern found. |
| Earnings realism | Unknown | Not measured. |
| Longevity | Unknown | Not checked on a primary source. |

**Cons**

- A relay earns nothing unless 100 ANYONE is locked for it for at least 180 days, and each reward claim is signed in your wallet. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/anyone-protocol.yml), checked 2026-11-04.
- It relays other people's traffic by design, with no vetting of who they are; exit relays attract abuse complaints. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/anyone-protocol.yml), checked 2026-11-04.
- The relay's identity, IP and uptime are published to the network directory, and any ContactInfo you set is public for good. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/anyone-protocol.yml), checked 2026-11-04.

**Pros**

- No account is needed at all. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/anyone-protocol.yml), checked 2026-11-04.
- The relay software is a published fork of Tor, under Tor's licence. [Source](https://github.com/anyone-protocol/ator-protocol), checked 2026-11-04.
- CashPilot builds its own image from Anyone's published relay software, which needs no account. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/anyone-protocol.yml), checked 2026-11-04.

<a id="bytelixir"></a>

### Bytelixir

**Grade F**, 6 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Bytelixir](guides/bytelixir.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Good |  |
| Payout terms | Fair |  |
| Account safety | Unknown | No reports of banned accounts found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | We could not load Bytelixir's terms. |
| Privacy | Unknown | The client is closed source; we could not load the privacy terms. |
| Identity checks | Good |  |
| Support | Unknown | Bytelixir replies to negative Trustpilot reviews, typically within a day, but that is not a ticket answer; we have no ticket of our own and found no reports about tickets either way. |
| Earnings realism | Unknown | Not measured. |
| Longevity | Unknown | We could not find the legal entity behind Bytelixir on a page that loaded. |

**Cons**

- Crypto only, and the minimum depends on the coin, from $5 for USDT to $250 for Bitcoin. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/bytelixir.yml), checked 2026-11-04.
- CashPilot does not run Bytelixir: you use the provider's own app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/bytelixir.yml), checked 2026-11-04.

**Pros**

- Trustpilot rates it 4.6 from 283 reviews, most of them praising crypto payouts; a few report payouts not arriving. [Source](https://www.trustpilot.com/review/bytelixir.com), checked 2026-11-04.
- A payout needs only a crypto address typed into the request. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/bytelixir.yml), checked 2026-11-04.

<a id="noderr"></a>

### Noderr Micronodes

**Grade F**, 6 of 20 points, 4 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Noderr Micronodes](guides/noderr.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Testnet beta: no rewards have been paid yet. |
| Payout terms | Unknown | Rewards are testnet tokens during the beta; mainnet terms are not published. |
| Account safety | Unknown | There is no account in the usual sense; the identity is a wallet. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Fair |  |
| Privacy | Fair |  |
| Identity checks | Good |  |
| Support | Unknown | No reports found. |
| Earnings realism | Poor |  |
| Longevity | Fair |  |

**Cons**

- Node rewards are unfunded testnet tokens with no market value, and none have been paid; the 5 to 10% APY on its site is a design target. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/noderr.yml), checked 2026-11-04.
- For the desktop and browser clients Noderr describes automation tasks and does not say whether they carry other people's traffic. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/noderr.yml), checked 2026-11-04.
- The provider says tasks are anonymised and sandboxed but publishes nothing more specific. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/noderr.yml), checked 2026-11-04.
- Still a testnet beta on Base Sepolia. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/noderr.yml), checked 2026-11-04.
- CashPilot does not run Noderr: you use the provider's own app or extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/noderr.yml), checked 2026-11-04.

**Pros**

- No account: the app generates a wallet on first launch. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/noderr.yml), checked 2026-11-04.

<a id="proxybase-xyz"></a>

### ProxyBase Markets

**Grade F**, 6 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [ProxyBase Markets](guides/proxybase-xyz.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no independent payout reports and have no payout of our own. |
| Payout terms | Fair |  |
| Account safety | Unknown | There is no account in the usual sense; the client mints its own wallet. |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Fair |  |
| Privacy | Unknown | Not reviewed beyond our own disclosure notes. |
| Identity checks | Good |  |
| Support | Unknown | No reports found. |
| Earnings realism | Unknown | Search summaries of its marketing pages quote $1.80 per GB and $54 to $90 a month for one device, far above our catalog estimate of $0 to $15, but the pages did not load for us to check. |
| Longevity | Unknown | We could not confirm the company behind ProxyBase Markets or how long it has run. |

**Cons**

- Payouts are USDC on Tempo Chain and need a Tempo wallet address. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/proxybase-xyz.yml), checked 2026-11-04.
- Your connection is sold as a SOCKS5 proxy to marketplace buyers; we found no description of how buyers are checked. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/proxybase-xyz.yml), checked 2026-11-04.

**Pros**

- Its own earn page is titled as needing no KYC, with a $1 payout. [Source](https://proxybase.xyz/earn/sell-internet), checked 2026-11-04.
- ProxyBase publishes its own client image and accepts datacentre connections. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/proxybase-xyz.yml), checked 2026-11-04.

<a id="repocket"></a>

### Repocket

**Grade F**, 6 of 20 points, 2 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Repocket](guides/repocket.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Poor |  |
| Payout terms | Poor |  |
| Account safety | Poor |  |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Fair |  |
| Privacy | Unknown | The client is closed source; we did not review the privacy policy in depth. |
| Identity checks | Fair |  |
| Support | Fair |  |
| Earnings realism | Unknown | Reviewers report very small amounts, but we have not measured Repocket's earnings against a provider figure. |
| Longevity | Fair |  |

**Cons**

- Several Trustpilot reviewers report cancelled payouts and balances reset to zero; one says support cited irregular bandwidth earnings. The page rates Repocket 2.7 and notes it has not replied to negative reviews. [Source](https://www.trustpilot.com/review/repocket.com), checked 2026-11-04.
- Reviewers report rejected withdrawals and having to chase payment. [Source](https://www.trustpilot.com/review/repocket.com), checked 2026-11-04.
- Repocket's payment policy lets it reverse, cancel or permanently forfeit earnings whenever it suspects they are invalid, and forfeit the unpaid earnings of a dormant account. [Source](https://repocket.com/payment-and-rewards-policy), checked 2026-11-04.
- The same policy lets Repocket add, remove or replace payout methods at any time without notice; PayPal was removed. [Source](https://repocket.com/payment-and-rewards-policy), checked 2026-11-04.
- The terms say Repocket may require identity or account verification at any time, and payout eligibility depends on it. [Source](https://repocket.com/terms-and-conditions), checked 2026-11-04.
- The terms say Repocket and its partners use the network capacity, but do not say who the partners are or how they are vetted. [Source](https://repocket.com/terms-and-conditions), checked 2026-11-04.
- Trustpilot notes Repocket has not replied to negative reviews, and reviewers say messages are ignored. [Source](https://www.trustpilot.com/review/repocket.com), checked 2026-11-04.
- The current terms name Repocket Pte. Ltd. in Singapore; older terms named no company. [Source](https://repocket.com/terms-and-conditions), checked 2026-11-04.

**Pros**

- Repocket publishes its own Docker image, repocket/repocket, and its terms allow containers you own. [Source](https://repocket.com/terms-and-conditions), checked 2026-11-04.
- The minimum is low: $4 before the first payout and $2 after it. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/repocket.yml), checked 2026-11-04.

<a id="bitping"></a>

### Bitping

**Grade F**, 5 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Bitping](guides/bitping.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no repeated user reports either way and have not published a payout of our own. |
| Payout terms | Fair |  |
| Account safety | Unknown | We found no Bitping terms page or reports of bans. |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Unknown | Bitping sells network monitoring from your connection; we found no page on who the customers are or how they are checked. |
| Privacy | Unknown | The node is closed source; we did not find a privacy page specific to node runners. |
| Identity checks | Good |  |
| Support | Unknown | No repeated reports found either way. |
| Earnings realism | Unknown | Not measured against a provider figure. |
| Longevity | Unknown | We did not find the legal entity behind Bitping. |

**Cons**

- Withdrawals are paid in Solana (SOL), to an address you type into each request. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/bitping.yml), checked 2026-11-04.
- Bitping's help says a withdrawal to a new, empty Solana wallet may fail until you fund that wallet with a little SOL yourself. [Source](https://bitping.com/help/nodes/troubleshooting-solana-payouts), checked 2026-11-04.

**Pros**

- Bitping's help says servers and Docker containers are supported. [Source](https://bitping.com/help/nodes/installing-the-node), checked 2026-11-04.
- A withdrawal needs only a Solana address typed into the request. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/bitping.yml), checked 2026-11-04.

<a id="earnfm"></a>

### Earn.fm

**Grade F**, 5 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Earn.fm](guides/earnfm.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Two Trustpilot reviewers report a late or missing payout and others report fast payouts; neither side reaches our user-reports threshold. |
| Payout terms | Fair |  |
| Account safety | Unknown | One Trustpilot reviewer alleges bans for criticism; one report is not a pattern. |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Unknown | Earn.fm's terms page leads to the business terms of InfiniteProxies; we found no page that says how buyers are vetted. |
| Privacy | Unknown | The client is closed source. One reviewer says a deleted account stayed in the database; one report is not a pattern. |
| Identity checks | Fair |  |
| Support | Fair |  |
| Earnings realism | Unknown | Not measured. |
| Longevity | Unknown | We could not find the legal entity behind Earn.fm on its own pages. |

**Cons**

- A $15 minimum, a $1 to $3 fee on USDT, and a bank wire only from $1,000. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/earnfm.yml), checked 2026-11-04.
- Before the first payout you fill in a billing profile with your legal name and address. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/earnfm.yml), checked 2026-11-04.
- Reviewers in 2025 report support on email and Discord not answering; Trustpilot notes Earn.fm has not replied to negative reviews. [Source](https://www.trustpilot.com/review/earn.fm), checked 2026-11-04.

**Pros**

- Earn.fm publishes its own Docker image, earnfm/earnfm-client. [Source](https://hub.docker.com/r/earnfm/earnfm-client), checked 2026-11-04.

<a id="ebesucher"></a>

### Ebesucher

**Grade F**, 5 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Ebesucher](guides/ebesucher.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | eBesucher says it has paid out over one million euros; we found no recent independent reports either way. |
| Payout terms | Good |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | The surfbar shows advertisers' pages; we did not find how advertisers are checked. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented on pages we read. |
| Support | Unknown | No reports found. |
| Earnings realism | Unknown | Not measured. |
| Longevity | Good |  |

**Cons**

- CashPilot does not run eBesucher: it is a browser extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/ebesucher.yml), checked 2026-11-04.

**Pros**

- Payouts from 2 euros by PayPal or SEPA, at least weekly, with no fee. [Source](https://www.ebesucher.com/earn-money/get-paid-to-surf), checked 2026-11-04.
- eBesucher has run since 2002. [Source](https://www.ebesucher.com/earn-money/beermoney), checked 2026-11-04.

<a id="flux"></a>

### Flux

**Grade F**, 5 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Flux](guides/flux.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Rewards are paid per block on-chain; we have no node of our own to report. |
| Payout terms | Fair |  |
| Account safety | Unknown | Nodes that fail Flux benchmarks stop earning; we found no pattern of disputes. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Good |  |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No pattern found. |
| Earnings realism | Fair |  |
| Longevity | Unknown | Not checked on a primary source. |

**Cons**

- The smallest node tier needs 1,000 FLUX locked as collateral. [Source](https://runonflux.com/fluxnodes/), checked 2026-11-04.
- The block reward drops 10% every year, and a 2026 guide found small-tier rewards weak in dollar terms. [Source](https://www.depinrun.com/guides/fluxnode-operator-guide), checked 2026-11-04.
- CashPilot does not run Flux: you use the provider's own node software, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/compute/flux.yml), checked 2026-11-04.

**Pros**

- The Flux daemon is open source under the MIT licence. [Source](https://github.com/RunOnFlux/fluxd), checked 2026-11-04.

<a id="iproyal"></a>

### IPRoyal Pawns

**Grade F**, 5 of 20 points, 4 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [IPRoyal Pawns](guides/iproyal.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Trustpilot withholds the rating of pawns.app for a breach of its guidelines and says it removed fake reviews, so its payout reviews cannot be taken at face value. We have not yet published a completed payout of our own. |
| Payout terms | Fair |  |
| Account safety | Fair | One Trustpilot reviewer says an account was blocked during a withdrawal after a phone number was mistyped; we could not confirm a wider pattern on the page. |
| Fit with how CashPilot runs it | Poor |  |
| Traffic transparency | Fair |  |
| Privacy | Unknown | The client is closed source; we did not review the privacy policy in depth. |
| Identity checks | Fair |  |
| Support | Unknown | No repeated support complaint found and no ticket of our own. |
| Earnings realism | Unknown | We have not measured Pawns earnings per IP against a provider figure. |
| Longevity | Fair |  |

**Cons**

- The terms say an account can be blocked without prior notice for abuse of withdrawal conditions or multiple accounts, and its earnings may then not be paid out. [Source](https://pawns.app/terms-of-use/), checked 2026-11-04.
- The terms say Pawns does not allow any servers, VPNs or proxy services for traffic sharing, and only one device per IP. [Source](https://pawns.app/terms-of-use/), checked 2026-11-04.
- PayPal costs 4% (at least $0.25) through Tremendous, and every payout is reviewed for up to 72 hours. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/iproyal.yml), checked 2026-11-04.
- The first payout needs an SMS check of your phone number, and every payout a code sent by email. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/iproyal.yml), checked 2026-11-04.
- The terms name no legal entity, only Pawns.app; the app is run by IPRoyal, a proxy company that started in late 2020. [Source](https://proxyway.com/reviews/iproyal-proxies), checked 2026-11-04.
- The terms say Pawns and its business clients route traffic through your device, and that you cannot identify which client uses it. [Source](https://pawns.app/terms-of-use/), checked 2026-11-04.

**Pros**

- A $5 minimum, with gift cards at no fee. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/iproyal.yml), checked 2026-11-04.

<a id="sentinel-dvpn"></a>

### Sentinel dVPN

**Grade F**, 5 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Sentinel dVPN](guides/sentinel-dvpn.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Payments are on-chain per session or per hour; we have no node of our own to report. |
| Payout terms | Fair |  |
| Account safety | Unknown | There is no account to ban; nodes are permissionless. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | VPN users route their traffic through your node; the protocol does not vet them. |
| Privacy | Good |  |
| Identity checks | Unknown | Not documented beyond a wallet. |
| Support | Unknown | No pattern found. |
| Earnings realism | Unknown | Hosts set their own prices; we found no published earnings figures to compare. |
| Longevity | Fair |  |

**Cons**

- Payments are in the P2P token, and 20% of every bandwidth payment goes to stakers rather than the node host. [Source](https://docs.sentinel.co/dvpn-nodes/earnings), checked 2026-11-04.
- The token was renamed from SENT to DVPN in 2021 and from DVPN to P2P in 2025. [Source](https://medium.com/sentinel/sentinel-is-changing-its-ticker-from-dvpn-to-p2p-with-its-ai-data-layer-launch-e5fde9443e6b), checked 2026-11-04.
- CashPilot does not run Sentinel: you use the provider's own node software, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/sentinel-dvpn.yml), checked 2026-11-04.

**Pros**

- Sentinel publishes its node source code under its own open source licence. [Source](https://github.com/sentinel-official/sentinel-dvpnx), checked 2026-11-04.

<a id="traffmonetizer"></a>

### Traffmonetizer

**Grade F**, 5 of 20 points, 4 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Traffmonetizer](guides/traffmonetizer.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Poor |  |
| Payout terms | Fair |  |
| Account safety | Unknown | We found no repeated reports of banned accounts and could not read the current terms on suspension. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | We could not find a page that says who buys the traffic or how buyers are checked. |
| Privacy | Unknown | The client is closed source; we did not review the privacy policy in depth. |
| Identity checks | Good |  |
| Support | Poor |  |
| Earnings realism | Fair |  |
| Longevity | Unknown | A third-party summary names Bytemarket OU in Estonia as the operator; we could not confirm it on Traffmonetizer's own pages. |

**Cons**

- Trustpilot rates it 1.9; reviewers from 2023 to November 2026 report payouts pending for weeks, or marked completed with no matching transaction. [Source](https://www.trustpilot.com/review/traffmonetizer.com), checked 2026-11-04.
- The same reviewers report live chat and email support not answering, sometimes for weeks. [Source](https://www.trustpilot.com/review/traffmonetizer.com), checked 2026-11-04.
- Crypto or a bank wire from $1,000 only; PayPal is gone, and a request pays whole dollars only. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/traffmonetizer.yml), checked 2026-11-04.
- Traffmonetizer's terms require a residential IP, so a server on a hosting connection is outside them. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/traffmonetizer.yml), checked 2026-11-04.
- Reviewers report about $0.10 per GB, and one cent a day across four devices. [Source](https://www.trustpilot.com/review/traffmonetizer.com), checked 2026-11-04.

**Pros**

- A payout needs only a saved crypto address confirmed by email; the dashboard may ask for a messenger contact. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/traffmonetizer.yml), checked 2026-11-04.
- Traffmonetizer publishes its own Docker image, traffmonetizer/cli_v2. [Source](https://hub.docker.com/r/traffmonetizer/cli_v2), checked 2026-11-04.

<a id="helium"></a>

### Helium

**Grade F**, 4 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Helium](guides/helium.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Rewards are paid on-chain; we found no pattern of missing rewards. |
| Payout terms | Unknown | Rewards are in HNT; we did not find fees or minimums worth grading. |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Good |  |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No pattern found. |
| Earnings realism | Poor |  |
| Longevity | Fair |  |

**Cons**

- HIP 149 retired Proof-of-Coverage rewards on 6 July 2026; IoT hotspots now earn only for data they carry, and more than 114,000 of them carried none. [Source](https://heliumgeek.com/faq/what-is-hip149.html), checked 2026-11-04.
- Helium's reward model has changed by vote several times, its CEO stepped down, and HNT fell about 96%. [Source](https://crypto.news/helium-ceo-amir-haleem-steps-down-as-hnt-token-extends-96-crash/), checked 2026-11-04.
- CashPilot does not run Helium: you use the provider's own hotspot hardware, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/helium.yml), checked 2026-11-04.

**Pros**

- The hotspot gateway software is open source under the Apache-2.0 licence. [Source](https://github.com/helium/gateway-rs), checked 2026-11-04.

<a id="proxylite"></a>

### ProxyLite

**Grade F**, 4 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [ProxyLite](guides/proxylite.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no user reports in a language we could check, and no payout of our own. |
| Payout terms | Good |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Unknown | The author of a widely used installer for it warns that some of the traffic is used to send spam; one source, so not graded, but read it before running ProxyLite: https://github.com/spiritLHLS/proxylite-one-click-command-installation |
| Privacy | Unknown | The client is closed source. |
| Identity checks | Unknown | Not documented on pages we read. |
| Support | Unknown | No reports found. |
| Earnings realism | Unknown | Not measured. |
| Longevity | Poor |  |

**Cons**

- The site's owner is hidden in its domain records, and we found no named company behind it. [Source](https://www.scamadviser.com/check-website/proxylite.ru), checked 2026-11-04.

**Pros**

- A $5 minimum, by crypto or PayPal. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/proxylite.yml), checked 2026-11-04.
- ProxyLite publishes a Docker image, proxylite/proxyservice, and accepts datacentre connections at a lower rate. [Source](https://hub.docker.com/r/proxylite/proxyservice), checked 2026-11-04.

<a id="salad"></a>

### Salad

**Grade F**, 4 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Salad](guides/salad.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Good |  |
| Payout terms | Fair |  |
| Account safety | Unknown | No pattern found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Salad rents your GPU to its cloud customers; we did not find how they are checked. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented on pages we read. |
| Support | Unknown | No pattern found. |
| Earnings realism | Unknown | Trustpilot's own summary says some reviewers find earnings low, and one October 2026 reviewer says an RTX 3090 barely covered its electricity. That is one site, below our user-reports threshold, and we found no second source. |
| Longevity | Unknown | Not checked on a primary source. |

**Cons**

- Rewards are redeemed in Salad's own storefront for PayPal or gift cards, with no crypto. Trustpilot's summary says some payment methods are hard to use in some regions, and reviewers describe a Visa card that cannot be added to Apple Pay in Europe and no payout option for India. [Source](https://www.trustpilot.com/review/salad.com), checked 2026-11-04.
- CashPilot does not run Salad: you use the provider's own desktop app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/compute/salad.yml), checked 2026-11-04.

**Pros**

- Several Trustpilot reviewers in October and November 2026 report PayPal cash-outs arriving quickly, some more than once; one reviewer in the same period says repeated cash-out attempts failed. [Source](https://www.trustpilot.com/review/salad.com), checked 2026-11-04.

<a id="vast-ai"></a>

### Vast.ai

**Grade F**, 4 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Vast.ai](guides/vast-ai.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no host complaint threads either way. |
| Payout terms | Good |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Renters run their own containers on your machine; we did not find how they are checked. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | A competitor's summary says hosts must complete identity, tax or business checks before choosing a payout method; we did not confirm it on Vast's own pages. |
| Support | Unknown | No pattern found. |
| Earnings realism | Fair |  |
| Longevity | Unknown | Not checked on a primary source. |

**Cons**

- CashPilot does not run Vast.ai: you install Vast's host software on your own GPU machine, so CashPilot cannot deploy or update it for you. Vast builds hosting around Docker on a Linux host. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/compute/vast-ai.yml), checked 2026-11-04.
- A host earns only while rented, and Vast's own figures for a consumer GPU depend on rental type and reliability score. [Source](https://vast.ai/article/how-much-money-can-you-earn-renting-out-your-gpu-on-vast-ai), checked 2026-11-04.

**Pros**

- Vast says the rate a host sets is the rate it receives, with no fee deducted. [Source](https://vast.ai/hosting), checked 2026-11-04.

<a id="bytebenefit"></a>

### Bytebenefit

**Grade F**, 3 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Bytebenefit](guides/bytebenefit.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | Trustpilot has four reviews. Two say the PayPal and Stripe payout pages return a 404 and the money never arrived, and one says it was paid. Two matching reports is under our threshold for a pattern, so we could not grade it either way. |
| Payout terms | Unknown | The catalog records a $5 minimum paid by PayPal, but two reviewers say the PayPal and Stripe payout pages return a 404, so we cannot say the route works. |
| Account safety | Unknown | No reports either way. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Fair |  |
| Privacy | Unknown | The client is closed source; we did not review the privacy policy. |
| Identity checks | Unknown | Not documented on pages we read. |
| Support | Unknown | One Trustpilot reviewer says ByteBenefit support did not reply and Infatica's support sent them back to it; one is not a pattern. |
| Earnings realism | Unknown | Not measured. |
| Longevity | Fair |  |

**Cons**

- The app's Google Play listing says your traffic serves web-intelligence requests by Infatica's clients, without saying who they are or how they are checked. [Source](https://play.google.com/store/apps/details?id=io.bytebenefit.app), checked 2026-11-04.
- The Android app left Google Play in April 2026 after 17 months. [Source](https://www.appbrain.com/app/bytebenefit/io.bytebenefit.app), checked 2026-11-04.
- CashPilot does not run ByteBenefit: you use the provider's own app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/bytebenefit.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="grass"></a>

### Grass

**Grade F**, 3 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Grass](guides/grass.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Good |  |
| Payout terms | Poor |  |
| Account safety | Unknown | We found no repeated reports of banned accounts. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Grass sells web data scraped through your connection; we did not find how its buyers are checked. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Claims go to a wallet; we did not find what else a claim asks for. |
| Support | Unknown | No pattern found. |
| Earnings realism | Poor |  |
| Longevity | Unknown | Grass is built by Wynd Network, a named and funded company; we did not confirm how long it has run. |

**Cons**

- Rewards come only through airdrop seasons. Long-running node operators reported season 2 estimates in the single to low double-digit dollar range. [Source](https://www.coingabbar.com/en/crypto-currency-news/grass-airdrop-season-2-claim-date-wallet-launch-price), checked 2026-11-04.
- Season 2 rewards not claimed by 22 January 2027 are lost for good. [Source](https://www.coingabbar.com/en/crypto-currency-news/grass-airdrop-season-2-claim-date-wallet-launch-price), checked 2026-11-04.
- The first airdrop drew a backlash over small rewards per point, diluted across more than two million users. [Source](https://beincrypto.com/grass-airdrop-sparks-outrage/), checked 2026-11-04.
- CashPilot does not run Grass: you use the provider's own app or extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/grass.yml), checked 2026-11-04.

**Pros**

- The first airdrop reached nearly 1.5 million claiming addresses. [Source](https://www.theblock.co/post/323805/grass-becomes-most-distributed-solana-airdrop-as-nearly-1-5-million-addresses-claim-tokens), checked 2026-11-04.

<a id="ionet"></a>

### io.net

**Grade F**, 3 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [io.net](guides/ionet.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no documented pattern of late or withheld supplier payouts. |
| Payout terms | Fair |  |
| Account safety | Unknown | io.net removed virtual GPU workers from rewards in 2024; we found no pattern affecting real hardware. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No pattern found. |
| Earnings realism | Poor |  |
| Longevity | Fair |  |

**Cons**

- Supplier rewards were paid from token emissions regardless of paid jobs, and GPU owners report sitting idle most of the time. [Source](https://ownyourmind.ai/projects/io-net/), checked 2026-11-04.
- Rewards are in the IO token and the payout model changed in 2026 to a dollar-pegged engine. [Source](https://ownyourmind.ai/projects/io-net/), checked 2026-11-04.
- In April 2024 about 1.8 million fake GPUs tried to join through a leaked authentication token, and the CEO later stepped down before the token launch. [Source](https://www.theblock.co/news/defi/2024-04-28-solana-based-depin-io-net-ceo-claims-network-was-attacked-in-detailed-postmortem-291315), checked 2026-11-04.
- CashPilot does not run io.net: you use the provider's own worker software, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/compute/ionet.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="nodepay"></a>

### Nodepay

**Grade F**, 3 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Nodepay](guides/nodepay.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | The NC token launched in January 2025; we found no pattern of reports about claims either way. |
| Payout terms | Unknown | Sources disagree on whether earning now requires staking NC; not confirmed on Nodepay's own pages. |
| Account safety | Fair |  |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Fair |  |
| Support | Unknown | No pattern found. |
| Earnings realism | Poor |  |
| Longevity | Unknown | We did not confirm the company behind Nodepay. |

**Cons**

- In its first season review Nodepay removed more than 300,000 accounts it judged to be bots and cancelled 17 billion points. [Source](https://coinmarketcap.com/academy/article/nodepay-airdrop-guide-everything-you-need-to-know), checked 2026-11-04.
- Eligibility needed a Solana wallet plus verified email, Discord and X accounts. [Source](https://coinmarketcap.com/academy/article/nodepay-airdrop-guide-everything-you-need-to-know), checked 2026-11-04.
- Rewards are points converted to the NC token, so their value rests on the token. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/nodepay.yml), checked 2026-11-04.
- CashPilot does not run Nodepay: you use the provider's own browser extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/nodepay.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="nosana"></a>

### Nosana

**Grade F**, 3 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Nosana](guides/nosana.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no host reports either way. |
| Payout terms | Fair |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Payouts go to a Solana wallet; we did not find other requirements. |
| Support | Unknown | No pattern found. |
| Earnings realism | Fair |  |
| Longevity | Unknown | Not checked on a primary source. |

**Cons**

- Each host must lock a NOS stake sized to its GPU's hourly price. [Source](https://github.com/nosana-ci/network-proposals/blob/main/nnp/NNP-0001-tokenomics.md), checked 2026-11-04.
- Hosts are paid in NOS, so dollar earnings move with the token and with demand for their card. [Source](https://solanacompass.com/projects/nosana), checked 2026-11-04.
- CashPilot does not run Nosana: you use the provider's own host software, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/compute/nosana.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="passiveapp"></a>

### PassiveApp

**Grade F**, 3 of 20 points, 8 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [PassiveApp](guides/passiveapp.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no independent payout reports; the testimonials on its site are its own. |
| Payout terms | Good |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No reports found. |
| Earnings realism | Unknown | Not measured. |
| Longevity | Unknown | We found no named company. Mobile and Linux apps announced in early 2025 have not shipped. |

**Cons**

- CashPilot does not run PassiveApp: you use the provider's own desktop app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/passiveapp.yml), checked 2026-11-04.

**Pros**

- PassiveApp's site lists PayPal, crypto and gift cards from a $3 minimum. [Source](https://www.passiveapp.com/), checked 2026-11-04.

<a id="proxyrack"></a>

### ProxyRack

**Grade F**, 3 of 20 points, 8 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [ProxyRack](guides/proxyrack.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | ProxyRack's Trustpilot reviews are mostly from proxy buyers; one peer reports payouts within three days and warns against deleting devices while a payout is pending. Not enough to judge. |
| Payout terms | Unknown | Third-party reviews disagree on the minimum ($5 or $20) and the help page did not load for us. |
| Account safety | Fair |  |
| Fit with how CashPilot runs it | Good |  |
| Traffic transparency | Unknown | We could not load the peer program's terms. |
| Privacy | Unknown | The client is closed source; we could not load the privacy terms. |
| Identity checks | Unknown | Not documented on pages we could load. |
| Support | Unknown | No peer-program pattern found. |
| Earnings realism | Unknown | Not measured. |
| Longevity | Unknown | We could not confirm the legal entity on a page that loaded. |

**Cons**

- ProxyRack's help centre says removing a device takes that device's earnings off your account, and they come back only if the same device is added again. [Source](https://help.proxyrack.com/en/articles/6532814-my-earnings-were-removed), checked 2026-11-04.

**Pros**

- ProxyRack publishes its own Docker image, proxyrack/pop, and accepts datacentre IPs at a lower rate. [Source](https://hub.docker.com/r/proxyrack/pop), checked 2026-11-04.

<a id="gradient"></a>

### Gradient Network

**Grade F**, 2 of 20 points, 6 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Gradient Network](guides/gradient.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | No token has launched, so nothing has been paid out to judge. |
| Payout terms | Poor |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | Chrome Web Store reviews report login and connection problems; we found no pattern about tickets. |
| Earnings realism | Poor |  |
| Longevity | Fair |  |

**Cons**

- The Sentry Node points program ended on 28 August 2025, and Sentry nodes no longer earn rewards. [Source](https://boxmining.com/gradient-network-token-airdrop-guide/), checked 2026-11-04.
- Gradient has announced no token, launch date or conversion rate for the points already earned. [Source](https://airdroplet.com/airdrop/gradient-network), checked 2026-11-04.
- Gradient's funding round was in June 2025; the project is young. [Source](https://boxmining.com/gradient-network-token-airdrop-guide/), checked 2026-11-04.
- CashPilot does not run Gradient: you use the provider's own app or extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/gradient.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="nodle"></a>

### Nodle

**Grade F**, 2 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Nodle](guides/nodle.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Fair |  |
| Payout terms | Unknown | Not documented on pages we read. |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | The app uses Bluetooth in the background; we did not review its privacy policy. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | Reviewers report unanswered messages; we could not confirm a pattern. |
| Earnings realism | Poor |  |
| Longevity | Unknown | Not checked on a primary source. |

**Cons**

- App Store reviewers report being unable to bridge or send NODL after the move to zkSync, and needing ETH to move tokens out. [Source](https://apps.apple.com/us/app/nodle-cash-wallet-earn-crypto/id1480763553), checked 2026-11-04.
- One reviewer reports about $3 earned over three to four years; others report daily earnings falling sharply. [Source](https://www.appbrain.com/app/nodle-cash-simple-earning-app/io.nodle.cash), checked 2026-11-04.
- CashPilot does not run Nodle: you use the provider's own phone app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/nodle.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="uprock"></a>

### Uprock

**Grade F**, 2 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Uprock](guides/uprock.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no recent pattern of reports either way. |
| Payout terms | Fair |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | One Google Play review reports an unanswered ticket; one is not a pattern. |
| Earnings realism | Poor |  |
| Longevity | Unknown | We did not confirm the company behind UpRock. |

**Cons**

- Trustpilot reviewers reported a 255 UPT minimum and a 55 UPT fee to withdraw to a wallet; these reports are old and the current terms may differ. [Source](https://www.trustpilot.com/review/uprock.com), checked 2026-11-04.
- Rewards are UPT tokens; reviewers and a third-party review say their value is very low. [Source](https://paidfromsurveys.com/uprock-ai-earnings-review), checked 2026-11-04.
- CashPilot does not run UpRock: you use the provider's own app or extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/uprock.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="dawn"></a>

### Dawn Internet

**Grade F**, 1 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Dawn Internet](guides/dawn.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | No token has been paid out yet. |
| Payout terms | Poor |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No pattern found. |
| Earnings realism | Poor |  |
| Longevity | Unknown | DAWN is built by Andrena, a named and funded US company; we did not confirm how long it has run. |

**Cons**

- The extension earns points; no token distribution to node operators had been confirmed by October 2026. [Source](https://www.airdropmeta.com/projects/dawn-internet), checked 2026-11-04.
- Points have no settled value until a token launches and its conversion is announced. [Source](https://airdropbuzz.com/airdrop/dawn-airdrop-guide), checked 2026-11-04.
- CashPilot does not run Dawn: you use the provider's own browser extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/dawn.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="deeper-network"></a>

### Deeper Network

**Grade F**, 1 of 20 points, 8 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Deeper Network](guides/deeper-network.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no recent pattern of reports either way. |
| Payout terms | Unknown | Not documented on pages we read. |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No pattern found. |
| Earnings realism | Poor |  |
| Longevity | Unknown | Not checked on a primary source. |

**Cons**

- Mining rewards are in DPR and depend on a credit score that grows slowly or by staking DPR. [Source](https://deeper-network-inc.gitbook.io/deeper-connect-knowledge-base/faq/mining), checked 2026-11-04.
- CashPilot does not run Deeper Network: you use the provider's own router hardware, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/deeper-network.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="spide"></a>

### Spide

**Grade F**, 1 of 20 points, 9 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Spide](guides/spide.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no user reports or payout proof. |
| Payout terms | Unknown | Our catalog lists crypto from $5; a third-party listing says Litecoin from $10. Not confirmed on Spide's own pages. |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Spide calls itself a proxy network; it does not say who the buyers are. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No reports found. |
| Earnings realism | Unknown | Spide's homepage calculator shows an example of about $45 a month. We found no user reports or measured figures to compare it with. |
| Longevity | Unknown | We did not find the company behind Spide. |

**Cons**

- CashPilot does not run Spide: you use the provider's own app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/spide.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="teneo"></a>

### Teneo Protocol

**Grade F**, 1 of 20 points, 7 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Teneo Protocol](guides/teneo.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | No transferable token has been paid out yet. |
| Payout terms | Poor |  |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No pattern found. |
| Earnings realism | Poor |  |
| Longevity | Unknown | We did not confirm the company behind Teneo. |

**Cons**

- Teneo says points will be consolidated into $AGENTIC, a non-transferable reward token, not the $TENEO token. [Source](https://teneo-protocol.ai/blog/the-first-step-towards-future-teneo-rewards), checked 2026-11-04.
- No $TENEO launch date, allocation or claim process had been confirmed by November 2026, after an earlier target of the second quarter of 2026 passed. [Source](https://blog.mexc.com/crypto-knowledge/teneo-airdrop-guide/), checked 2026-11-04.
- CashPilot does not run Teneo: you use the provider's own browser extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/teneo.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="theta-edge"></a>

### Theta Edge Node

**Grade F**, 1 of 20 points, 9 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Theta Edge Node](guides/theta-edge.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no pattern of reports either way. |
| Payout terms | Unknown | Elite edge nodes need at least 10,000 TFUEL staked; we did not find the full payout terms. |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No pattern found. |
| Earnings realism | Unknown | The only estimate we found is one forum post, below our user-reports threshold, and Theta's own pages give no per-node figure. |
| Longevity | Unknown | Not checked on a primary source. |

**Cons**

- CashPilot does not run Theta Edge: you use the provider's own desktop app, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/theta-edge.yml), checked 2026-11-04.

**Pros**

- None found.

<a id="titan"></a>

### Titan Network

**Grade F**, 1 of 20 points, 8 of 10 criteria unchecked, reviewed 2026-11-04. Setup guide: [Titan Network](guides/titan.md).

| Criterion | Verdict | Note |
|---|---|---|
| Payout record | Unknown | We found no pattern of user reports either way. |
| Payout terms | Unknown | Earlier reward rules locked 40% of daily rewards; those rules are marked replaced and we did not find the current ones. |
| Account safety | Unknown | No reports found. |
| Fit with how CashPilot runs it | Fair |  |
| Traffic transparency | Unknown | Not documented on pages we read. |
| Privacy | Unknown | Not reviewed. |
| Identity checks | Unknown | Not documented. |
| Support | Unknown | No pattern found. |
| Earnings realism | Poor |  |
| Longevity | Unknown | We did not confirm the company behind Titan. |

**Cons**

- Titan's own help says a running node does not guarantee earnings: with no task assigned it earns nothing, and rewards are in the TNT token. [Source](https://titannet.gitbook.io/titan-network-en/galileo-testnet/f.a.q./how-to-increase-node-rewards), checked 2026-11-04.
- CashPilot does not run Titan: you use the provider's own app or extension, so CashPilot cannot deploy or update it for you. Its terms were not checked for containers. [Source](https://github.com/GeiserX/CashPilot/blob/main/services/depin/titan.yml), checked 2026-11-04.

**Pros**

- None found.

<!-- END GENERATED: ratings -->
