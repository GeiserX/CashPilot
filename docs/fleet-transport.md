# Fleet transport: pinned keys, then iroh

Status: design spec, 2026-11-27. It covers steps 2 and 3 of the fleet security plan. Step 1 shipped first, in [#870](https://github.com/GeiserX/CashPilot/pull/870): no box sends its key over plain `http://` to a public host ([the rule](fleet.md#plain-http-only-on-your-own-network)).

This page is the single source for the three stacks: the Docker worker and the web UI (Python), CashPilot Desktop (Go) and the Android app (Kotlin). Where it says "must", every stack does exactly that. Where a stack differs, the stack is named.

## 1. What changes

Today the fleet key travels over plain HTTP on the LAN. Anyone who can read the LAN can read a box's key, and that key deploys containers on the box.

After step 2:

- Each box and the UI hold an Ed25519 key. A box's identity is its public key.
- Pairing a box pins keys in both directions: the UI records the box's key, and the box records the UI's key.
- Every fleet connection is TLS 1.3. Each side checks the other's certificate against the pinned key. No certificate authority takes part.
- The bearer key stays. A request needs the right bearer and the right pinned key.

After step 3, the same key is also the box's iroh endpoint id. The UI, Docker workers, Desktop and phones can then reach each other through NAT with no port forward and no VPN. iroh is a setting, off by default.

## 2. The links

| Link | TLS client | TLS server | Server port, step 2 | iroh in step 3 |
|---|---|---|---|---|
| Heartbeat and earnings import | Box (worker, Desktop, phone) | UI | UI fleet port `8443` | Yes |
| Commands to a Docker worker | UI | Worker | `8081` | Yes |
| Commands to a joined Desktop | UI | Desktop | `8086` | Yes |
| Desktop as hub ("Accept workers") | Worker or phone | Desktop | `8085` | No |
| The browser to the dashboard | Browser | UI | `8080` | No |

The browser link does not change. A browser cannot pin a key. The dashboard stays on `8080` behind the login, and a user who wants it remote keeps a reverse proxy or a VPN. For that reason the boxes get their own port on the UI, `8443`. A browser never sees the self-signed certificate.

The box-facing routes on the UI are `POST /api/workers/heartbeat` and `POST /api/workers/earnings-import`. The fleet port serves only these two routes and answers `404` to every other path. After step 2 the dashboard port answers both routes with `426` and the re-pair message in section 8.1.

A Desktop in hub mode plays the UI's part for the boxes that report to it. Everything this page says about the UI as a server also applies to the hub.

## 3. Identities

### 3.1 The key

- Every box and every UI makes one Ed25519 key at first run. The key comes from the operating system's random source.
- The key is the 32-byte seed of RFC 8032. Its public key is 32 bytes.
- A stack never makes a new key while the key file exists. A new key is a new identity, and a new identity needs pairing again.

### 3.2 The endpoint id

The endpoint id is the 32-byte public key, written as 64 lowercase hex characters, for example `5a2fe1db…b223`. This is exactly iroh's `EndpointId` text form (`str(id)` in the iroh Python package), so step 3 needs no second identity.

The fingerprint is the endpoint id itself. Nothing is hashed. 64 hex characters fit on a line, and one value means nothing can drift.

Parsing rules for every stack:

- Lowercase the input and trim spaces.
- Accept only exactly 64 characters from `0-9a-f`.
- Refuse anything else with a message that names the setting.
- Compare the 32 bytes, never the text.

A short form for lists is the first 10 hex characters (iroh's `fmt_short`). It is only for reading. A stack never accepts or compares the short form.

### 3.3 Where the keys live

| Stack | Identity key | TLS leaf key and chain | Pins it holds |
|---|---|---|---|
| Docker worker | `/data/.identity_key` | `/data/.tls_key`, `/data/.tls_chain.pem` | The UI's endpoint id from `CASHPILOT_UI_KEY`, and the UI's identity certificate in `/data/.ui_identity.pem` |
| UI | `/data/.identity_key` | `/data/.tls_key`, `/data/.tls_chain.pem` | Each box's endpoint id and identity certificate, in the `workers` table |
| Desktop | The OS keychain through the existing `config` keyring helper, item `identity-key`, with the same 0600 file fallback the fleet key uses: `<AppDir>/identity_key.pem` | `<AppDir>/tls_key.pem`, `<AppDir>/tls_chain.pem` | The UI's id and identity certificate in `config.json` when joined. As hub: each box's, as the UI keeps them |
| Android | The seed, encrypted with AES-256-GCM under an AndroidKeyStore key (alias `cashpilot_identity_wrap`), in `filesDir/identity.bin` | An AndroidKeyStore EC P-256 key (alias `cashpilot_tls`, `PURPOSE_SIGN`, `DIGEST_SHA256`, not exportable). The chain is in `filesDir/tls_chain.pem` | The UI's id and identity certificate, in the settings DataStore |

File rules:

- Formats:
  - Key files hold PKCS#8 PEM (`-----BEGIN PRIVATE KEY-----`). An Ed25519 PKCS#8 file holds the 32-byte seed (RFC 8410), so the same file feeds TLS and iroh.
  - Chain files hold PEM certificates in the order of section 4.3.
- Permissions:
  - Key files are mode `0600` and belong to the user the app runs as (`cashpilot` in the images).
  - Chain files and certificate files are `0644`.
- Location:
  - On Docker, the files live in the container's own `/data`, never in the shared `/fleet` volume. The UI and a worker beside it already have separate `/data` folders.
  - Android excludes `identity.bin` and `tls_chain.pem` from backup and device transfer in `data_extraction_rules.xml`, as it does for the settings file.
- Writing:
  - Write to a temporary file in the same folder, `fsync` it, then rename it into place.
  - Create the temporary file with `O_EXCL`, so two starts cannot both write one.
- A broken key file:
  - A key file that exists but does not parse stops the fleet link.
  - The log names the file and says to restore it or delete it. Deleting it means pairing again.
  - The stack never replaces the file by itself.
- The leaf key:
  - The TLS leaf key and its chain are made again, both together, whenever either file is missing or the pair does not match. The pair does not match when the chain's identity certificate lacks the current identity key, or its leaf certificate lacks the leaf key. So a new identity key always gets a new leaf, and a start that stopped between the two writes repairs itself.
  - The leaf is signed by the identity key, so a new leaf needs no new pairing.
- Encryption at rest:
  - The UI and worker files are not encrypted at rest.
  - The UI's Fernet key sits in the same `/data`, so encrypting them would add nothing.
- Backups:
  - The UI's backup and restore include `/data/.identity_key`.
  - A UI restored from backup keeps its id, so no box needs pairing again.

Each box shows its own endpoint id: the worker in a log line at start and on its status page, Desktop in Settings, and Android in Settings. A stack never logs the seed.

## 4. Certificates

Each side holds two certificates: an identity certificate and a TLS leaf.

The identity certificate is self-signed with the Ed25519 key. It is what the other side pins.

The leaf holds an ECDSA P-256 key, and the identity key signs the leaf. The TLS handshake signature uses the P-256 key. P-256 works in every TLS stack we ship. Android's platform TLS (BoringSSL through Conscrypt) does not offer Ed25519 for the handshake signature, so the design does not depend on it. The Ed25519 signatures appear only inside the certificates, where each stack checks them in its own code or through OpenSSL.

### 4.1 The identity certificate

| Field | Value |
|---|---|
| Version | v3 |
| Serial | The first 16 bytes of the public key as a big-endian unsigned integer, shifted right by one bit. If that is 0, use 1 |
| Subject and issuer | `CN=<endpoint id>`: the 64 hex characters, which is exactly the CN length limit |
| Validity | `notBefore` 2026-01-01T00:00:00Z, `notAfter` 9999-12-31T23:59:59Z |
| Public key | Ed25519 (OID 1.3.101.112) |
| Signature | Ed25519, made with the same key |
| `basicConstraints` | critical, `CA:TRUE`, `pathLenConstraint` 0 |
| `keyUsage` | critical, `keyCertSign` only |
| `subjectKeyIdentifier` | SHA-1 of the subjectPublicKey bit string (RFC 5280 method 1) |
| `subjectAltName` | URI `cashpilot://<endpoint id>` |

Every field is fixed and Ed25519 signatures are deterministic, so one stack makes the same bytes from the same key every time. Nothing relies on that. A verifier always compares the key, never the bytes.

### 4.2 The TLS leaf

| Field | Value |
|---|---|
| Version | v3 |
| Serial | 16 random bytes, positive |
| Subject and issuer | `CN=<endpoint id>`, the same as the identity certificate |
| Validity | The same as the identity certificate |
| Public key | ECDSA P-256 |
| Signature | Ed25519, made with the identity key |
| `basicConstraints` | critical, `CA:FALSE` |
| `keyUsage` | critical, `digitalSignature` only |
| `extendedKeyUsage` | `serverAuth`, `clientAuth` |
| `authorityKeyIdentifier` | `keyIdentifier` equal to the identity certificate's `subjectKeyIdentifier` |
| `subjectKeyIdentifier` | SHA-1 of the leaf's subjectPublicKey bit string |
| `subjectAltName` | URI `cashpilot://<endpoint id>` |

The far `notAfter` is deliberate. A pinned certificate that expires is an outage with no warning on an unattended box. Trust ends when the owner removes the pin.

This profile passes OpenSSL's strict chain checks (`VERIFY_X509_STRICT`, on by default in Python 3.13 and newer). We tested that, in section 11.

### 4.3 What each side sends

In both roles, client and server, a side sends the chain `[leaf, identity certificate]` in that order and signs the handshake with the leaf key.

## 5. The channel

### 5.1 TLS settings

- TLS 1.3 only, with each stack's default TLS 1.3 cipher suites.
- ALPN `http/1.1` on clients. Nothing negotiates HTTP/2.
- No SNI is needed. A server ignores the name a client sends.
- Servers issue no session tickets: Python `ctx.num_tickets = 0`, Go `SessionTicketsDisabled: true`. A resumed session skips the certificate exchange, so a box removed after its last full handshake could otherwise come back on its ticket.
- No stack ever loads the system CA store or checks a host name on a fleet link. The pin is the whole check.

### 5.2 Verifying by pin

A side accepts the other's chain only if all of these hold. This applies to servers checking clients and to clients checking servers.

1. The chain has exactly two certificates.
2. The second certificate has an Ed25519 public key, and those 32 bytes are a pinned endpoint id.
3. The second certificate's self-signature verifies with that key.
4. The first certificate's signature verifies with that key.
5. The first certificate's public key is ECDSA P-256.
6. The handshake completes. This proves the peer holds the leaf key.

Names, dates and the system CA store play no part in the check.

The Go check, as tested in section 11:

```go
func verifyPinned(raw [][]byte, pinned func(ed25519.PublicKey) bool) error {
	if len(raw) != 2 {
		return fmt.Errorf("want 2 certificates, got %d", len(raw))
	}
	leaf, err := x509.ParseCertificate(raw[0])
	if err != nil {
		return err
	}
	id, err := x509.ParseCertificate(raw[1])
	if err != nil {
		return err
	}
	pub, ok := id.PublicKey.(ed25519.PublicKey)
	if !ok || !pinned(pub) {
		return errors.New("identity is not pinned")
	}
	if err := id.CheckSignature(x509.PureEd25519, id.RawTBSCertificate, id.Signature); err != nil {
		return err
	}
	if err := leaf.CheckSignatureFrom(id); err != nil {
		return err
	}
	if k, ok := leaf.PublicKey.(*ecdsa.PublicKey); !ok || k.Curve != elliptic.P256() {
		return errors.New("leaf key is not P-256")
	}
	return nil
}
```

How each stack runs the check:

- **Go (Desktop).**
  - As a client: `InsecureSkipVerify: true` together with `VerifyPeerCertificate: verifyPinned`. With `InsecureSkipVerify` alone, nothing would be checked.
  - As a server: `ClientAuth: tls.RequestClientCert` and a `VerifyPeerCertificate` that accepts an empty chain (enrolment, section 7) and otherwise calls `verifyPinned`.
  - The pinned set is read on every handshake, so adding or removing a box needs no restart.
- **Python (UI and worker), with the standard library `ssl` module only.**
  - The trust store holds only the pinned identity certificates, loaded with `load_verify_locations(cadata=...)`. The context never calls `load_default_certs()`.
  - Settings: `check_hostname = False`, `VERIFY_X509_STRICT` on, minimum version TLS 1.3. A client uses `CERT_REQUIRED`. A server uses `CERT_OPTIONAL`, so a box that is enrolling can connect with no certificate.
  - OpenSSL then runs checks 2, 4 and 6: it matches the leaf's issuer to a pinned identity certificate and checks the leaf's signature with that key. The stack runs checks 3 and 5 itself on the verified chain (`get_verified_chain()`, Python 3.13 and newer). It runs check 1 on the chain the peer sent (`get_unverified_chain()`). OpenSSL can complete a verified chain from its trust store, so a peer that sends only its leaf still gets a verified chain of two.
  - When the pinned set changes, the UI builds a new server context. An `sni_callback` on the listening context sets `sslobj.context` to the current one for each new handshake, so adding or removing a box takes effect without a restart. We tested both directions in section 11 with blocking sockets. The Python lane must test it once more under uvicorn's asyncio transport, which hands the callback an `SSLObject`.
  - The servers run on uvicorn with `ssl_context_factory` (uvicorn 0.54).
- **Kotlin (Android).**
  - An `X509ExtendedTrustManager` runs all six steps in `checkServerTrusted`. It checks the Ed25519 signatures with BouncyCastle's `Ed25519Signer` over `getTBSCertificate()`.
  - An `X509ExtendedKeyManager` returns the AndroidKeyStore P-256 key and the chain from section 4.3.
  - OkHttp gets these through `sslSocketFactory(context.socketFactory, trustManager)`, a `hostnameVerifier` that returns true (the pin replaces the name), and `ConnectionSpec.RESTRICTED_TLS` limited to `TlsVersion.TLS_1_3`.
  - OkHttp's `CertificatePinner` is not used. It pins inside a CA-validated chain, and these chains have no CA.
  - The platform TLS stack has TLS 1.3 only from Android 10, and the app supports Android 8. So the app installs Conscrypt as the first security provider, and API 26 to 28 get TLS 1.3 too.

A handshake that presents a certificate that is not pinned fails at TLS. A handshake with no client certificate succeeds only so the box can enrol. The app then refuses every other request on that connection (section 5.3).

### 5.3 The peer's identity reaches the app

The request handler needs the peer's endpoint id from the transport, never from a header the peer could set.

- Go reads `r.TLS.PeerCertificates[1]`, after `verifyPinned` passed.
- Python:
  - uvicorn 0.54 does not fill in the ASGI TLS extension. A small protocol subclass (`http=` in the uvicorn config) reads the peer chain from the transport's `ssl_object` in `connection_made`. It puts the chain into `scope["extensions"]["tls"]["client_cert_chain"]` as the ASGI spec names it, and the endpoint id into `scope["extensions"]["cashpilot.peer"]["endpoint_id"]`.
  - The endpoint id comes from the verified chain (`get_verified_chain()`): it is the key of the identity certificate that issued the leaf and matched a pin. The identity certificate the peer sent must equal that verified one, or the connection is closed. Otherwise a peer could send its own leaf with another box's public identity certificate, and OpenSSL would still complete the chain with the right one.
  - Middleware reads only `cashpilot.peer`.
  - Section 9.4 fills the same key for iroh, so one auth path serves both transports.
- Android is only ever a client, so it needs no peer id in a handler.

### 5.4 The bearer stays as a second check

Every request still carries a bearer key, exactly as today.

- On the UI and a hub: a request is accepted only if the bearer is box B's own key and the TLS peer's endpoint id is B's pin.
- On a worker and on Desktop's command port: a request is accepted only if the bearer is that box's own key. The TLS peer must also be the pinned UI.
- Either check failing gives `401`. The log says which check failed and never prints the key.

A stolen bearer is useless without the box's private key. A stolen private key is useless without the bearer.

### 5.5 What reaches a port without a client certificate

| Port | Without a client certificate | With a pinned one |
|---|---|---|
| UI fleet port `8443` | Only the enrolment heartbeat (section 7.2) | `POST /api/workers/heartbeat`, `POST /api/workers/earnings-import` |
| Worker `8081` | `GET /api/health` (the container healthcheck, which connects over TLS without verifying) and the status page `/`, which keeps its bearer check. A browser shows a certificate warning there. That is expected | Every route |
| Desktop hub `8085` | The same rule as the UI fleet port: only the enrolment heartbeat | The UI fleet port's routes |
| Desktop commands `8086` | Health only | Every route |

### 5.6 URLs

- A URL to a pinned peer is `https://host:port`. When a stack holds a pin for that peer, it verifies by the pin and never by a CA. A URL without a pin is refused on a fleet link.
- TLS must run end to end between CashPilot processes. A reverse proxy that terminates TLS in between breaks the pin, by design. Use TCP passthrough for the fleet port, or no proxy.
- The step 1 rule (no key over plain `http://` to a public host) still guards the legacy paths until they are removed.

## 6. Settings

| Setting | Where | Meaning |
|---|---|---|
| `CASHPILOT_FLEET_PORT` | UI | The port boxes connect to, default `8443`. The compose files publish it next to `8080` |
| `CASHPILOT_UI_URL` | Docker worker | Now `https://<ui host>:8443` |
| `CASHPILOT_UI_KEY` | Docker worker | The UI's endpoint id, 64 hex characters. Required: without it the worker sends nothing and logs why |
| `CASHPILOT_WORKER_URL` | Docker worker | Now `https://<worker host>:8081` |
| `CASHPILOT_IROH` | UI and worker, and the same setting in Desktop and Android | `on` or `off`, default `off`. Section 9 |
| `CASHPILOT_IROH_RELAY` | UI and worker, and the same setting in Desktop and Android | One relay URL. Empty means n0's public relays. Section 9.6 |

Desktop and Android hold the same values in their own settings, filled from the paste block.

## 7. Enrolment

### 7.1 The paste block

The UI's Fleet page, under Add a box, copies this block. Desktop's hub snippets use the same block with the Desktop's own id.

```text
CASHPILOT_UI_URL=https://192.168.1.10:8443
CASHPILOT_UI_KEY=5a2fe1db0c4e7304ea22ec6fa22b1b4b9ed2c1f0a3b4c5d6e7f8091a2b3cb223
CASHPILOT_API_KEY=<the shared enrolment key>
CASHPILOT_WORKER_NAME=server-name
```

- `CASHPILOT_UI_URL` uses the host the browser is on, with the fleet port.
- When the UI has iroh on, the block has one more line: `CASHPILOT_IROH=on`. When the UI uses its own relay, it also has `CASHPILOT_IROH_RELAY=<url>`.
- Line parsing is the one Desktop already uses (`internal/upstream/join.go`, `parseBlock`):
  - One `KEY=VALUE` per line, with an optional `export ` or `- ` prefix.
  - `KEY: VALUE` is accepted too.
  - Quotes around the value are removed, and CR LF works.
  - An unknown line is skipped.
- `CASHPILOT_UI_KEY` follows the parsing rules in section 3.2.
- A block with a URL and no `CASHPILOT_UI_KEY` comes from an older UI. Refuse it with: "This block is from an older CashPilot. Update it, then copy the block again."

### 7.2 First contact

1. The box loads its identity and leaf, or makes them (section 3).
2. The box connects to `CASHPILOT_UI_URL` over TLS **with no client certificate** and checks the UI's chain against `CASHPILOT_UI_KEY`. It sends nothing until that check passes.
   - Python has no verify callback, and it holds no UI certificate yet. So the first connection uses `CERT_NONE` and reads `get_unverified_chain()`. It runs the six checks of section 5.2 in code with `cryptography`, writes the UI's identity certificate to `/data/.ui_identity.pem` and closes. Every later connection loads that file as `cadata`.
   - At each start, the box checks that the key in `/data/.ui_identity.pem` equals `CASHPILOT_UI_KEY`. If it does not, the box deletes the file and repeats this first connection against the new pin. So a changed `CASHPILOT_UI_KEY` (section 8.3) takes effect at the next start.
   - With `CASHPILOT_IROH=on`, steps 2 and 3 can run over iroh instead, so a UI with no reachable fleet port can still pair boxes. The box dials `CASHPILOT_UI_KEY`, and iroh's handshake proves that the UI holds that key. The box writes the `ui_identity_cert` of the reply (step 4) to `/data/.ui_identity.pem` after it checks that certificate's key. It tries TLS first only when `CASHPILOT_UI_URL` is set.
3. The box sends `POST /api/workers/heartbeat` with `Authorization: Bearer <shared key>`. The body holds the usual fields plus `identity_cert`, the PEM of the box's identity certificate.
4. The UI accepts the enrolment only when all of these hold:
   - The shared key is right.
   - One of these admits the `client_id`:
     - It is new.
     - Its pin is unconfirmed and equals the presented key, and the box proves it holds that key. This is a retry, described below.
     - The owner opened a re-pair window for it and for this exact endpoint id (section 8), and that pin is not confirmed yet.
   - `identity_cert` passes checks 2 and 3 of section 5.2 against its own key.
   - Its CN is the hex of that key.
   
   The UI then stores the pin, issues the box's own key as it does today (`worker_key` in the reply), and adds `ui_identity_cert` to the reply. If that certificate's key is not `CASHPILOT_UI_KEY`, the box drops the reply and refuses to continue.
5. The UI rebuilds its fleet listener's trust (section 5.2).
6. The box's next heartbeat presents its certificate and its own key. The UI checks that the peer id equals the pin for that `client_id`, then marks the pin confirmed. This is the existing `key_confirmed` step, extended to the pin.
7. From then on, the UI sends commands to the box's `https://` URL. It presents its own certificate and checks the box against the pin. The box checks the UI against its pin.

A lost reply does not strand the box. If the reply of step 4 never arrives, the box retries with the same identity. While the pin is unconfirmed and equals the presented key, the UI runs step 4 again and returns a new reply. The new `worker_key` replaces the one the lost reply carried.

- The retry must prove that the box holds the identity key, because `identity_cert` is public. Over TLS, the box presents its client certificate: after step 5 the UI's listener already trusts the unconfirmed pin, so the handshake checks it. Over iroh, the connection's remote id is the proof.
- A retry without that proof gets `409`. So a holder of the shared key who copies the public certificate cannot replace the box's `worker_key`.
- A different identity, or any identity once the pin is confirmed, gets the `409` below.
- Inside a re-pair window the same rules hold: a retry with the approved id and its proof completes, and any other id is refused.

The UI refuses these, each with a message the box logs and shows:

- The shared key with `identity_cert` for a `client_id` that is already pinned, when no rule of step 4 admits it: `409`, "This box is already paired. On the Fleet page, press Pair again on it."
- The shared key with no `identity_cert`: `426`, "This box runs a CashPilot that cannot pair. Update it."
- A heartbeat with no client certificate for a confirmed box: `401`.

## 8. Pairing again

There is no silent migration. Every box is paired again once, when step 2 ships, and that release is a major version.

### 8.1 The upgrade

What the user sees on the UI:

- Every box row keeps its history and earnings, which are keyed on `client_id`. It shows a **Pair again** flag, and the box reads as offline until it is paired again. Its containers keep running and earning.
- The owner pastes the new block (Fleet page, Add a box) on the updated box. The box's first attempt gets `409`. The UI records the endpoint id it presented, and the row shows "This box presented a key: `<short id>`" next to **Pair again**.
- The owner compares the short id with the one the box shows (section 3.3), then presses **Pair again**. That opens a window for that `client_id` **and that endpoint id only**. It closes when that pin is confirmed (section 7.2, step 6), or after 30 minutes. The box's next attempt enrols and keeps its row, because `/data/.worker_id` keeps its `client_id`. Its old bearer key is discarded and a new one is issued.
- Inside the window, the UI refuses any other endpoint id for that `client_id` with `409` and records it, so the row shows the conflict.
- A new box needs no window. A new `client_id` enrols with the shared key, as it does today.

What the user sees on the box:

- An old worker gets `426` from the dashboard port. Its log says: "Your CashPilot UI needs this box paired again. Update this worker, then paste the new block from the Fleet page."
- An updated worker with no `CASHPILOT_UI_KEY` sends nothing. It logs why once at start, and shows it on its status page and in `/api/health`:
  "CASHPILOT_UI_KEY is not set, so this worker does not know which UI to trust and sends it nothing. Copy the block from the Fleet page, Add a box."
- Desktop and Android show the same message on their status screen.

The window guards the moment a row has no pin. Without it, anyone holding the shared key could claim an existing row before its real box re-enrols. The window names one endpoint id, so the holder of the shared key cannot use it either. Any other id is refused, and the approved id is useless to them without its private key.

### 8.2 A box that lost its key

A box that lost its `/data` or its key file makes a new identity.

- If it also lost `/data/.worker_id`, it enrols as a new box. The owner removes the old row.
- If it kept its `client_id`, the UI refuses it with `409`. The UI records the endpoint id it presented, and the row shows "This box presented a new key: `<short id>`" next to **Pair again**.
- The owner compares the short id with the one the box shows (section 3.3), then presses **Pair again**. That opens the window of section 8.1 for that endpoint id only. The box's next attempt enrols.
- The box logs: "The UI refused this box's key, because it was paired with another one. On the Fleet page, press Pair again on `<name>`."

### 8.3 A UI that lost its key

A UI restored from its backup keeps its key, and nothing changes.

A UI rebuilt with no backup has a new id. Every box refuses it at the handshake, and each box logs: "The UI's key changed from `<old short id>` to `<new short id>`. If you rebuilt your UI, set `CASHPILOT_UI_KEY` to the new id on this box." The owner pairs every box again with the new block.

### 8.4 Removing a box

Removing a row deletes its pin. The UI rebuilds its trust at once, so the box's next handshake fails.

There is no key rotation apart from pairing again.

## 9. Step 3: iroh

### 9.1 One identity

- The iroh secret key is the 32-byte seed from the identity key file.
- The iroh endpoint id is the identity's public key, which is the pin.
- In the Python package: `EndpointOptions(secret_key=seed)` and `ep.id().to_bytes()`.
- We checked that the id is the Ed25519 public key that `cryptography` derives from the same seed, and that signatures verify across the two (section 11).

### 9.2 ALPN

`cashpilot/fleet/1`, as bytes. A change to the wire format needs a new ALPN, `cashpilot/fleet/2`. A peer that offers another ALPN is refused at the handshake (tested).

### 9.3 Which links use iroh

- The UI and a Docker worker: heartbeats and commands.
- The UI and a joined Desktop: heartbeats and commands.
- An Android phone to the UI: heartbeats. A phone on mobile data must reach the UI, and iroh lets it do that without a VPN.

The hub links and the browser stay on pinned TLS and the dashboard port.

### 9.4 What travels over iroh

- iroh's own QUIC handshake already authenticates both ends by endpoint id. So no X.509 TLS runs inside it.
- Each request is one bidirectional stream:
  - The dialer writes one HTTP/1.1 request with `Connection: close` and finishes its send side.
  - The acceptor reads the request and serves it through the same app, with `cashpilot.peer.endpoint_id` set to `conn.remote_id()`.
  - The acceptor writes the response and finishes.
- One QUIC connection per peer stays open and carries many streams.
- The routes, the bearer check and the pin check of section 5.4 are the same as on TLS.

The accept rule is checked at `accept`, before any stream is read:

- The UI accepts any pinned box. It also accepts an unpinned id for exactly one request: the enrolment heartbeat of section 7.2, step 3. There, the key in `identity_cert` must equal the connection's remote id.
- A worker and a Desktop accept only the pinned UI.
- Anything else is closed with application error code 1.

### 9.5 Addressing

- A box dials the UI by `CASHPILOT_UI_KEY`, and the UI dials a box by its pin. Neither needs an IP address.
- With n0's relays, the dialer passes `EndpointAddr(id, None, [])` and lets n0's discovery find the peer. With the user's own relay, it passes `EndpointAddr(id, relay_url, [])`. Both forms are tested.
- When iroh is on and a box also has a pinned-TLS URL, a request whose iroh dial fails goes over TLS, and the failure counts (section 9.7). A request that failed after it was sent is not sent again over TLS. With iroh off, nothing changes from step 2.

### 9.6 Relays

- By default iroh uses n0's public relays, `preset_n0()`. We run no relay for users.
- For the user's own relay, set `CASHPILOT_IROH_RELAY=<https url>`. The endpoint then binds with `RelayMode.custom_from_urls([url])`, and dials pass that relay URL in the `EndpointAddr`. The UI, its boxes and its phones must all use the same relay.
- iroh is off for users by default. Our own fleet and test beds turn it on, so it gets used for real. The default stays off until it has held for weeks.

### 9.7 Recovery: N = 5

An endpoint that is up but stalled is the failure we hit ourselves: hours with the process alive and nothing getting through. So every long-lived endpoint supervises itself.

- A failure is either of these:
  - A failed dial: a `connect` that raises, or that does not finish within 30 seconds.
  - A failed request on an open connection. Opening the stream, writing the request or reading the response raises. Or the response does not end within the timeout that the TLS path uses for that request, which is 15 seconds for a heartbeat.
  - After a failed request, the dialer closes that connection, so the next request dials again.
- A failed request is never replayed. Its caller sees a failure, as it does today when an HTTP request times out. A command whose result is unknown stays unknown, and the existing deploy deadline settles it.
- A box or a Desktop counts failures in a row. Only a completed request resets the count. An inbound connection from the UI does not, because it does not show that the box can reach the UI.
- The UI counts failures in a row for each box. A completed request to that box, or a heartbeat from it, resets that box's count. Traffic with other boxes does not.
- At 5 failures in a row, the supervisor closes the endpoint (`ep.close()`, at most 10 seconds) and binds a new one with the same key. On the UI, a box whose count reaches 5 recycles the endpoint, but the same box can cause at most one recycle every 30 minutes. So a dead box costs the others one short reconnect each half hour. Another box that stalls has its own allowance, and it gets a fresh endpoint within its own 5 failures.
- If that close does not return, the process exits with status 75. Docker's restart policy restarts the container, and on Desktop the app restarts its sidecar.
- The same recycle happens when `ep.addr().relay_url()` stays `None` for 5 minutes. An unreachable relay raises no error, so this field is the only sign.

Why 5:

- A box sends a heartbeat once a minute, and each failed one fails within 30 seconds at most. So 5 failures take about 5 minutes, whether the dial or the request stalls.
- A UI update or restart takes one or two heartbeats. 5 is above that, so a routine restart does not recycle every box's endpoint.
- The worker reports itself unhealthy after 12 missed heartbeats. 5 is below that, so the endpoint is recycled before the container is flagged.
- The stalls we saw lasted hours. 5 minutes is the most any one of them can now last.

Android is different:

- Each WorkManager run binds a fresh endpoint and closes it at the end, so the count does not carry across runs.
- Within a run, one failed dial sends that heartbeat over TLS when the phone has a TLS URL. Otherwise it waits for the next run.

No iroh release fixes the stall issues that are open today (n0-computer/iroh #4476, #4707, #4603, #4656). This recycle is the guard until one does.

### 9.8 Python: in-process, on Debian

The official wheel works on Debian, so the worker and UI images move from Alpine to Debian and use iroh in-process. The evidence is in section 11.

- Base image: `python:3.15-slim-trixie`, pinned by digest, as the Dockerfiles pin today.
- Install: `iroh==1.2.0` from PyPI, locked in `uv.lock`. PyPI has wheels only (`py3-none-manylinux_2_28_x86_64` and `_aarch64`), with no sdist and no musl wheel. That is why Alpine is out.
- Size:
  - The Debian base is about 44.5 MB compressed, against 20.0 MB for `python:3.15-alpine`.
  - The iroh wheel is about 7 MB compressed and 19 to 20 MB installed.
  - Measure both images against the 100 MB rule before the switch merges.
- Debian has no `su-exec`, so the entrypoint drops root with `setpriv` (util-linux, in the slim image) instead.

### 9.9 Desktop: a sidecar

Go has no official iroh binding, so Desktop ships a small Rust sidecar, `cashpilot-iroh`. It is built on the iroh crate at the iroh core version that iroh-ffi 1.2.0 builds against, read from that release's `Cargo.lock`.

- There are two listeners. The sidecar listens on the dial socket, for outbound requests. Desktop listens on the inbound socket, for streams the sidecar accepts.
- Start:
  - Desktop opens its inbound socket first, then starts the sidecar and writes the 32-byte seed to its stdin.
  - Arguments: `--alpn cashpilot/fleet/1`, `--relay <url>` (absent means n0), `--dial-socket <path>` and `--inbound-socket <path>`.
  - On macOS and Linux, both are Unix sockets of mode 0600 in AppDir. Only the user can connect, so no token is needed.
  - On Windows, both are TCP on 127.0.0.1, so each direction needs a token:
    - Desktop binds its inbound port and passes `--inbound-socket 127.0.0.1:<port>`. After the seed, it writes its own 32-byte hex token as one line on stdin.
    - The sidecar binds `--dial-socket 127.0.0.1:0`, then prints the port it bound and its own 32-byte hex token on stdout.
    - Each side sends `TOKEN <the other side's hex>\n` first on every connection it opens, and closes any connection whose first line is not its own token.
- Inbound:
  - For each stream the sidecar accepts, it connects to Desktop's inbound socket and writes `PEER <64 hex>\n`. Then it pipes bytes both ways.
  - Desktop reads that line as the peer's endpoint id and serves HTTP on the rest of the stream.
  - Desktop applies the accept rule of section 9.4 and closes a stream from a peer it does not accept.
- Outbound:
  - Desktop connects to the sidecar's dial socket and writes `DIAL <64 hex>\n`.
  - The sidecar answers `OK\n` and then pipes, or answers `ERR <reason>\n` and closes.
- Recovery: the sidecar runs the rule of section 9.7 and exits with status 75. Desktop restarts it whenever it exits.

### 9.10 Android

Android uses the `computer.iroh:iroh-android:1.2.0` AAR from Maven Central. It is 22.9 MB before ABI splits, so ship per-ABI APKs or an App Bundle.

## 10. Libraries per stack

| Stack | TLS | Certificates and Ed25519 | iroh |
|---|---|---|---|
| Python (UI, worker) | Standard library `ssl` on the image's OpenSSL 3. Servers on uvicorn 0.54 with `ssl_context_factory`. Clients on httpx with an `ssl.SSLContext` | `cryptography` 50.0.2 (already locked): `Ed25519PrivateKey`, `ec.SECP256R1`, `x509.CertificateBuilder` | `iroh` 1.2.0 (PyPI, iroh-ffi) |
| Go (Desktop) | `crypto/tls` with `VerifyPeerCertificate` (Go 1.26) | `crypto/ed25519`, `crypto/ecdsa`, `crypto/x509` (`CreateCertificate` with an Ed25519 parent). The identity goes in the keychain through `zalando/go-keyring`, already used for the fleet key | The `cashpilot-iroh` Rust sidecar (section 9.9) |
| Kotlin (Android) | OkHttp 5.5.1 (through ktor-client-okhttp 3.6.1) with a custom `X509ExtendedTrustManager` and `X509ExtendedKeyManager`. `org.conscrypt:conscrypt-android` 2.10.0 as the first provider, for TLS 1.3 on API 26 to 28 | `org.bouncycastle:bcprov-jdk18on` and `bcpkix-jdk18on` 1.87: `Ed25519Signer`, `X509v3CertificateBuilder`. AndroidKeyStore for the P-256 key and the wrapping key | `computer.iroh:iroh-android` 1.2.0 |

## 11. Evidence

### 11.1 The iroh wheel on Debian

Tested on 2026-11-27 with Docker on an arm64 Mac mini. linux/arm64 ran natively and linux/amd64 under emulation.

- The package:
  - `iroh` 1.2.0 (2026-10-22) is the newest release on PyPI and on iroh-ffi's GitHub releases.
  - Its wheels are `iroh-1.2.0-py3-none-manylinux_2_28_x86_64.whl` (7,198,245 bytes) and `…_aarch64.whl` (6,950,433 bytes), built by maturin 1.15.0.
  - They are tagged `py3-none`, so one wheel serves every CPython 3. They need glibc 2.28 or newer.
- The base image is `python:3.15-slim-trixie` (Python 3.15.2, glibc 2.41), index digest `sha256:63bb298d2b7b88f176f51b5189f54ce6535c997682ea70885d2132f5d473a8a5`.
- The install command is `pip install --no-cache-dir --only-binary=:all: iroh==1.2.0`. pip printed `Downloading iroh-1.2.0-py3-none-manylinux_2_28_aarch64.whl (7.0 MB)` on arm64 and the `x86_64` wheel (7.2 MB) on amd64, then `Successfully installed iroh-1.2.0`.
- On `python:3.15-alpine`, pip printed `ERROR: Could not find a version that satisfies the requirement iroh==1.2.0 (from versions: none)`. It fails the same way without `--only-binary`, because there is no sdist.
- The echo test:
  - A server container and a client container on one Docker network ran the test. The client sent `hello` over ALPN `cashpilot/fleet/1` and read it back.
  - Three dial forms passed on both architectures: a full ticket, relay URL only, and id only through n0 discovery.
  - A second arm64 run passed 15 times out of 15.
  - A custom relay map (`preset_minimal()` with `RelayMode.custom_from_urls`) also passed.
  - A client offering another ALPN was refused with `peer doesn't support any known protocol`.

```text
arm64  ticket      echo=b'hello' OK connect=4.0ms    rtt=1.7ms
arm64  relay-only  echo=b'hello' OK connect=221.7ms  rtt=89.4ms
arm64  id-only     echo=b'hello' OK connect=221.1ms  rtt=89.0ms
amd64  ticket      echo=b'hello' OK connect=86.7ms   rtt=15.5ms
amd64  relay-only  echo=b'hello' OK connect=300.7ms  rtt=104.2ms
amd64  id-only     echo=b'hello' OK connect=320.6ms  rtt=95.2ms
```

The core of the two processes:

```python
# server
ep = await iroh.Endpoint.bind(
    iroh.EndpointOptions(preset=iroh.preset_n0(), secret_key=seed32, alpns=[b"cashpilot/fleet/1"])
)
await ep.online()
while (inc := await ep.accept_next()) is not None:
    conn = await (await inc.accept()).connect()
    bi = await conn.accept_bi()
    data = await bi.recv().read_to_end(1024)
    await bi.send().write_all(data)
    await bi.send().finish()
    await conn.closed()

# client
ep = await iroh.Endpoint.bind(iroh.EndpointOptions(preset=iroh.preset_n0()))
conn = await ep.connect(iroh.EndpointAddr(server_id, None, []), b"cashpilot/fleet/1")
bi = await conn.open_bi()
await bi.send().write_all(b"hello")
await bi.send().finish()
assert await bi.recv().read_to_end(1024) == b"hello"
```

Known limits of this evidence:

- One early failure: in the very first run, one relay-only dial failed and the server, which had no error handling yet, stopped. All 21 relay-only and id-only dials after that passed. We cannot tell if it was a passing relay fault.
- One network: both containers sat on one Docker network, so traffic moved to the direct path after the relay handshake. Behaviour across real NATs is not shown here.

### 11.2 Pinned TLS across Python and Go

Tested on 2026-11-27 with Python 3.13 on OpenSSL 3.5.5, `cryptography` from the lockfile, and Go 1.27. The certificates follow section 4 exactly.

- Python against Python:
  - A pinned box connected with and without SNI.
  - A box with no client certificate reached the server, as enrolment needs.
  - A box with a certificate that was not pinned was refused at TLS.
  - A client pinning the wrong UI refused the server.
  - After the `sni_callback` swapped in a context without the box, the box was refused. A box added in the same swap was accepted.
- Go server, Python clients:
  - A pinned box was accepted with 2 peer certificates.
  - A box with no client certificate was accepted with 0.
  - A box that was not pinned was refused: `identity … is not pinned`.
- Python server, Go clients:
  - A box pinning the right UI read `hi`.
  - A box pinning another key refused the server: `identity … is not pinned`.

The Android lane must repeat the Go-server and Python-server cases from a device on API 26 and API 36 before its PR merges.

## 12. Tests every stack carries

Each case must fail when its check is removed. Prove that once by breaking the check and watching the test go red.

- Verifying by pin: accept a valid pinned chain. Refuse each of these:
  - an unpinned identity
  - a leaf signed by another key
  - a leaf with an Ed25519 or RSA key
  - a chain of one or three certificates, as the peer sent it
  - an identity certificate whose self-signature is broken
  - an endpoint id of 63 or 65 characters, or one that is not hex
- Enrolment:
  - Refuse a second enrolment of a pinned `client_id` outside the window, and accept it inside the window.
  - Inside the window, refuse every endpoint id but the approved one.
  - Complete a retry with the same unconfirmed identity and its proof: the client certificate over TLS, or the matching remote id over iroh. Refuse it without the proof, and once the pin is confirmed.
  - Close the re-pair window when its pin is confirmed.
  - On the box, drop a cached `/data/.ui_identity.pem` whose key is not `CASHPILOT_UI_KEY`.
  - Refuse an `identity_cert` whose CN is not its key.
  - On a Desktop hub, accept the enrolment heartbeat without a client certificate on `8085`, and refuse it on `8086`.
  - Refuse a reply whose `ui_identity_cert` is not `CASHPILOT_UI_KEY`.
- The bearer: refuse box A's bearer on box B's certificate, and box A's certificate with box B's bearer. Refuse box A's leaf sent with box B's identity certificate.
- Keys: a new identity key on a box that kept its TLS files gets a new leaf signed by it. A new leaf key stored without its chain gets both files made again.
- Removal: a removed box's next handshake fails without a restart.
- Tickets: a server issues no session ticket.
- iroh:
  - Refuse an unpinned id at accept, except for the one enrolment request.
  - After 5 failures in a row, recycle the endpoint. Count a request that stalls on an open connection as a failure. Fewer failures, or one completed request in between, keep it.
  - Never replay a request that failed after it was sent.
