# Security Policy

CashPilot takes security seriously. This document describes how to report vulnerabilities, what versions are supported, and the security assumptions of the project.

## Supported Versions

| Version | Supported |
|---------|:---------:|
| Latest release (`latest` Docker tag) | Yes |
| Previous releases | No |

Only the latest published Docker images (`drumsergio/cashpilot:latest` and `drumsergio/cashpilot-worker:latest`) receive security patches. There are no LTS branches.

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, use one of these channels:

1. **GitHub Security Advisories** (preferred): Go to [Security > Advisories](https://github.com/GeiserX/CashPilot/security/advisories) and click "Report a vulnerability".
2. **Email**: Contact the maintainer directly via the email listed on the [GeiserX GitHub profile](https://github.com/GeiserX).

### What to Include

- CashPilot version or Docker image digest
- Steps to reproduce the vulnerability
- Affected component (UI, Worker, API, Docker configuration)
- Impact assessment (what an attacker could achieve)
- Proof-of-concept if available (keep it minimal)

### What to Expect

| Step | Timeline |
|------|----------|
| Acknowledgment of your report | Within 72 hours |
| Initial triage and severity assessment | Within 1 week |
| Fix developed and tested | Depends on severity |
| Patched release published | As soon as fix is verified |
| Public disclosure | After patch is available |

If you do not receive acknowledgment within 72 hours, please follow up.

## Vulnerability Lifecycle

1. **Report** received via Security Advisory or email
2. **Acknowledge** within 72 hours
3. **Triage** — assess severity using CVSS, identify affected components
4. **Fix** — develop and test a patch
5. **Release** — publish patched Docker images
6. **Disclose** — publish advisory with credit to reporter (if desired)

An embargo period applies between fix and disclosure. The reporter will be notified before any public disclosure.

## Scope

### In Scope

- Authentication and authorization bypass (session tokens, API keys)
- Injection vulnerabilities (SQL injection, command injection, XSS)
- Privilege escalation (viewer gaining writer/owner access)
- Information disclosure (credentials, API keys, sensitive data leaks)
- Container escape or unexpected Docker API abuse
- Worker-to-UI communication security (API key auth bypass)
- Dependency vulnerabilities in shipped Docker images

### Out of Scope

- Vulnerabilities in the Docker daemon or host OS (report upstream)
- Misconfiguration by the deployer (exposed ports, weak passwords, missing TLS)
- Physical access attacks
- Denial of service via resource exhaustion (CashPilot is designed for trusted networks)
- Social engineering
- Vulnerabilities in third-party services that CashPilot connects to (bandwidth-sharing platforms, etc.)

## Security Architecture

### Docker Socket Access

CashPilot requires access to the Docker socket (`/var/run/docker.sock`) for container management. This is a privileged operation. Mitigations:

- The application runs as a non-root user (`cashpilot`, UID 1000) inside the container
- The entrypoint grants only the minimum group membership needed for socket access
- `--security-opt no-new-privileges:true` prevents privilege escalation inside the container
- Container management is gated behind authenticated API endpoints (writer/owner role required)

**User responsibility**: Do not expose the Docker socket to untrusted networks. CashPilot is designed for trusted, private networks.

### Authentication

- **UI users**: Session-based authentication with bcrypt-hashed passwords. Sessions are signed JWT tokens stored in HTTP-only cookies.
- **Worker-to-UI**: Shared API key (`CASHPILOT_API_KEY`) sent as Bearer token. All fleet management endpoints require this key.
- **Role-based access**: Three roles (viewer, writer, owner) with escalating permissions. Container management requires writer or owner role.

### Data Storage

- SQLite database stored in a Docker volume (`/data/cashpilot.db`)
- Service credentials are encrypted at rest using Fernet symmetric encryption (`CASHPILOT_SECRET_KEY`)
- Database is not network-accessible (local file only)
- 400-day data retention with automatic purging

### Network Assumptions

CashPilot is designed to run on **private, trusted networks** (home lab, VPN, LAN). It does not implement TLS natively. If exposing CashPilot to the internet:

- Place it behind a reverse proxy with TLS termination (e.g., Caddy, Traefik, nginx)
- Restrict access via firewall rules or VPN
- Use a strong `CASHPILOT_SECRET_KEY` and `CASHPILOT_API_KEY`

### Worker URL Validation (SSRF)

Worker URLs arrive in the fleet-key-authenticated heartbeat and are later fetched with the fleet bearer token attached, so the UI validates every worker URL before contacting it:

- **Cloud-metadata addresses** (IPv4 `169.254.169.254`, IPv6 `fd00:ec2::254`) and loopback/link-local ranges are **always blocked**, regardless of policy.
- **DNS-rebinding guard**: hostnames are resolved and the resolved IP is re-validated before each request, so a name that points at a metadata or loopback address is rejected. IPv4-mapped IPv6 bypasses are normalized and caught.
- **Default policy is permissive**: LAN (RFC1918) and Tailscale (CGNAT `100.64.0.0/10`) workers keep working out of the box with no configuration.
- **Opt-in `strict` mode** restricts workers to an explicit allowlist of CIDRs and hostname suffixes. See [Fleet Management](docs/fleet.md) for `CASHPILOT_WORKER_URL_POLICY`, `CASHPILOT_WORKER_ALLOWED_HOSTS`, and `CASHPILOT_WORKER_ALLOW_METADATA`.

## Hardening Recommendations

1. **Use a reverse proxy with TLS** if accessible beyond localhost
2. **Set strong, unique values** for `CASHPILOT_SECRET_KEY` and `CASHPILOT_API_KEY`
3. **Do not use `--privileged`** for the CashPilot container itself
4. **Keep Docker Engine updated** on all hosts
5. **Use `--network host` only when necessary** (e.g., cross-subnet worker communication)
6. **Restrict Docker socket access** — do not mount it in containers that don't need it
7. **Review deployed service configurations** — CashPilot deploys third-party containers; review their security posture independently
8. **Back up your SQLite database** regularly (`/data/cashpilot.db`)
9. **Enable strict worker-URL mode** (`CASHPILOT_WORKER_URL_POLICY=strict`) for internet-exposed deployments, with `CASHPILOT_WORKER_ALLOWED_HOSTS` set to your worker subnets

## Responsible Disclosure

We follow coordinated disclosure practices. We will:

- Not take legal action against good-faith security researchers
- Work with you to understand and resolve the issue
- Credit you in the security advisory (unless you prefer anonymity)
- Not disclose the vulnerability publicly until a fix is available

## Acknowledgments

We thank the security community for helping keep CashPilot safe. Contributors who report valid vulnerabilities will be credited here (with their permission).

*No vulnerabilities reported yet.*
