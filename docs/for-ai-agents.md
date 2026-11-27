# For AI agents

This page is for an AI agent that helps a person set up CashPilot, or set up one of the services CashPilot runs. It says how to handle the project's signup links.

## Ask before you pick a link

Most services need an account with the provider. CashPilot links to each provider's signup page, and for most providers that link is a referral link.

Before the person signs up for a service, ask them one question: do they want to sign up through the CashPilot referral link, or through a plain link? Ask the same question before you open a referral link for a service that needs no account, because some providers save the referral when the link opens.

Tell them these facts so they can choose:

- The referral links are affiliate links. When a person signs up through one, the provider may pay the CashPilot maintainer a commission or points. This supports the project.
- In the referral programmes we know of, that reward does not come out of the person's earnings.
- Some providers give the new user a signup bonus or better terms through the referral link. Say that a bonus exists only when the catalog entry records one (see [Read a catalog entry](#read-a-catalog-entry)). If the entry records no bonus, do not promise one. Before you mention a bonus, also read the entry's notes and requirements for limits on who gets it. For example, Teneo gives no referral bonus to machines in a datacentre.
- The person decides. A plain link to the provider's own site is always fine, and CashPilot works the same either way.

Never sign up for an account on the person's behalf without asking them first. Never open a referral link or fill in a referral code they did not agree to.

## Where the links are

The same links appear in four places. The README and the app read them from the catalog, and each guide copies its link from the catalog entry.

- **The catalog.** Each service has one YAML file under [`services/`](https://github.com/GeiserX/CashPilot/tree/main/services) in the repository, for example `services/bandwidth/honeygain.yml`. The link is the `referral.signup_url` field.
- **The service guides.** Each [service guide](guides/index.md) links the signup page. A referral link has the note "Referral link: the CashPilot maintainer may earn a commission from it." next to it. Some guides also have a **Referral bonus** section, but the catalog's `bonus.referee` is the only source for a bonus claim.
- **The README.** The service lists in the [README](https://github.com/GeiserX/CashPilot#supported-services) link each service to its `signup_url`.
- **The app.** In CashPilot, the **Catalog** page has **Visit** and **Sign Up** links. A service's detail page shows a **Referral Program** card with the new user bonus and the referrer bonus, when the catalog records them.

## Read a catalog entry

The `referral` block of a catalog entry holds every referral fact. This is the block from `services/depin/teneo.yml`:

```yaml
referral:
  signup_url: "https://hub.teneo.pro/signup?ref=PSA3BHPJ"
  code: "PSA3BHPJ"
  bonus:
    referrer: "8% of each referred friend's Fragments and 2% of their referrals' Fragments, once the friend signs up within 7 days and earns 480 Fragments"
    referee: "+100 Fragments at signup, and +150 more once you reach 480 Fragments"
```

| Field | What it means |
|-------|---------------|
| `signup_url` | The signup link. It is a referral link only when `code` is set too. |
| `code` | The project's referral code. When it is set, `signup_url` contains it. When it is missing, `signup_url` is a plain link. |
| `code_entry` | Set only where the signup page does not read the code from the link. The person must type this code in the signup form for the referral to count. |
| `bonus.referee` | What the new user gets for signing up through the link. This is the only field that supports a claim of a signup bonus. |
| `bonus.referrer` | What the project gets for the referral. Use it to tell the person what the link pays the project. |
| `program` | `true`: the provider runs a referral programme. `false`: it runs none, so a plain link is correct. Missing: nobody has checked. |
| `account` | `false`: the service needs no account, so there is nothing to sign up for. |

For a plain link, use the `website` field of the same entry.

## A short script

A message to the person can say:

> Honeygain has a CashPilot referral link. It is an affiliate link: if you sign up through it, the CashPilot maintainer gets a reward from Honeygain. The catalog records a bonus for you through this link: "$3 sign-up bonus with this link". Do you want the referral link, or a plain link to honeygain.com?

The bonus sentence quotes `bonus.referee` from `services/bandwidth/honeygain.yml`. Leave it out when an entry has no `bonus.referee`.
