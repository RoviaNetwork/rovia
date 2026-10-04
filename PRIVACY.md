# Privacy

This document describes what Rovia handles, where it lives, who can read it, and
what Rovia deliberately does not do. It is written against the code in this
repository, not against an intention.

Two statements frame everything below.

1. Rovia contains no telemetry, analytics, advertising, attribution, or
   crash-reporting SDK. There is no code in this repository that sends data to
   a Rovia-operated service, because there is no Rovia-operated service.
2. Rovia does not promise that a proxy hides your traffic from the network you
   are on, from the server operator you connect to, or from a compromised
   device. See `docs/security/threat-model.md` for the boundaries.

Where this document says a capability is not implemented, that is a statement
about this pre-alpha slice, not a design promise. New collection requires a
change to this document, an App Store privacy label update, and a reviewed
decision recorded in `docs/architecture/decision-log.md`.

## Data inventory

| Data | Where it lives | Who can read it | Retention | Deleted when |
| --- | --- | --- | --- | --- |
| Subscription URL | The App Group container, in the subscription store (`subscriptions/`), with the credential part in the Keychain — never in the file | The app and the tunnel extension, both via the shared App Group | Until the subscription is removed | Deleting the subscription, or deleting the app |
| Subscription or share-link response body | Memory only | The parsing code | One import | Immediately after parsing |
| Server credentials (UUIDs, passwords, keys) | The Keychain, written by the subscription import with `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` in the shared access group the extension also reads. The canonical configuration carries only a `SecretReference` key | The app and the tunnel extension, on this device only | Until the subscription is removed | Deleting the subscription, or deleting the app |
| Non-secret canonical configuration | The App Group container: the subscription store, plus the tunnel hand-off (`tunnel/canonical-config.json`, `tunnel/settings.json`) written before a tunnel start and read by the extension | The app and the tunnel extension | Until overwritten by the next write | Deleting the app, or the next write |
| Routing policy and selected server | The App Group hand-off (in the canonical configuration) and the app model | The app and the tunnel extension | Until changed | The next write, or deleting the app |
| Connection state and timestamps | Memory only | The app model | Until the next status refresh | Replaced by newer status |
| Latency and health samples | Memory | Selection logic | Until the next sample | Replaced by newer samples |
| Routing diagnostic (what the user asked about) | Memory, and the on-screen debugger | The user, on the device | Until the user leaves the screen | Leaving the screen or deleting the app |
| Bundled engine provenance (the engine lock, `engines.lock.json`) | Not in the shipped app: it is a build input, read by CI and by the SBOM generator | The release engineer, and any reviewer of the release artifacts | For the lifetime of the build | Never; it is a build input, not user data. The shipped app records the provenance derived from it in its SBOM, not the lock itself. |
| Signing material | A temporary CI keychain, never on a user's device | The release job in the protected `ios-production` environment | One job | The keychain is deleted in an `always()` step |

Credentials are never written to the canonical configuration, a diagnostic, an
error message, or a log. The assertions are the schema rules that
reject secret-bearing transport keys, the `SecretReference` key rule in
`RoviaConfig` and `schemas/config.schema.json`, and canary-secret tests in
`core/config`, `core/subscription`, and `client/app/ios/RoviaAppTests`. The
Keychain and the App Group are both written to today: credentials go to the
Keychain, and the hand-off files carry no credential values — a test reads the
written configuration and fails if a credential value appears in it.

## Data flows

### Subscription import

```text
user-supplied URL or pasted link
        |
        v
bounded read (1 MiB, UTF-8)  ->  parser  ->  transient secret reference
        |                          |
        |                          +-> canonical server record naming a secret
        v
raw body discarded after parsing; the App Group holds the redacted record and
the Keychain holds the credential. A redacted display value such as
"vless://synthetic.example:443/••••••••" is all the UI ever shows
```

A URL source is stored as a URL plus a secret reference; the token, path, and
query of a subscription URL are treated as secrets. A pasted or imported link
is never stored raw: the parser produces a canonical server and a redacted
display value, and a parser error contains a stable code, never the input.

### Tunnel start

```text
user taps Connect
        |
        v
selected server resolved to a canonical configuration
(App Group hand-off: endpoints and routing, never credentials)
        |
        v
NetworkExtension public API: NEPacketTunnelProvider starts
        |
        v
engine validates and starts (XrayAdapter over the pinned artifact)
        |
        v
NEPacketTunnelNetworkSettings applied — after the engine is running
        |
        v
packets move: NEPacketTunnelFlow <-> pump <-> xray.tun.fd
```

The engine lock approves and enables a pinned xray build, and the extension is
wired to it: `PacketTunnelProvider` validates the canonical configuration the
app wrote to the App Group hand-off, starts the engine through the live
adapter, and moves packets between `packetFlow` and the engine's utun file
descriptor via the pump. Packets are framed and forwarded; **payloads are never
read, logged, or persisted** — the pump's only counters are drop counts, and
`RoviaConfig.RoutingDecisionTrace` stays in memory, not `Codable`, with nothing
persisting it.

Rovia never installs a default route before the engine is running: the
extension prepares and starts the engine first and applies network settings
after, so the route never exists without something consuming it. The engine
binary is the pinned artifact built by the gated pipeline; nothing executable
is downloaded after installation.

### Routing and health

Routing is evaluated locally against the policy the user configured, by the one
implementation in `RoviaRouting`. The app's debugger hands its display models
to `RouteEvaluator.explain` and renders the returned `RoutingDiagnostic`; it does
not compare hosts, ports, or CIDR ranges itself, and
`tools/ci/test_app_dependencies.py` fails if a second evaluator reappears in the
app or if the Xcode project stops linking the package.

`RoviaConfig.RoutingDecisionTrace` is the raw form: it holds the hostname,
address, and port that were evaluated. It is not `Codable`, it is not written
anywhere, and the only thing that outlives an evaluation is the redacted
`RoutingDiagnostic`.

Health selection is a pure function of an injected snapshot: it does not call the
engine, `URLSession`, the wall clock, or a random source. In this slice the
latency values are fixture data; no active latency probe is implemented yet,
and no implementation of one is authorized without updating this document.

### Diagnostics

Routing diagnostics exist to explain a decision the user made. The on-screen
debugger evaluates one of the content's built-in synthetic sample inputs with
`RoviaRouting.RouteEvaluator.explain`, and renders the `RoutingDiagnostic` it
returns. That type's fields are fixed by `schemas/control-api.schema.json`:

- `inputSummary`: four booleans, `hasHost`, `hasIP`, `hasPort`, `hasNetwork`;
- `rules`: per rule, a rule identifier, `enabled`, `matched`, `selected`, a
  stable reason code, and the rule's matchers;
- `matchers`: per matcher, a rule identifier, matcher index, matcher type,
  `matched`, `selected`, `applied`, `ruleEnabled`, and a reason code;
- `finalDecision`: `direct`, `block`, or a group identifier;
- `selectedGroup`, `selectedServer`: opaque identifiers or `null`;
- `reasonCode`: `firstMatchingRule`, `defaultAction`, or `invalidInput`.

The diagnostic deliberately has no field for a hostname, an IP address, a port
value, a URL, a credential, a packet, or the raw request. The schema sets
`additionalProperties: false` at every level, and the decoder rejects unknown
keys, so a future field cannot be added to a diagnostic without failing the
schema and the tests. The on-screen debugger shows the same structure: whether a
host, an address, a port, or a network is present is reported as a boolean, and
the debugger never holds the value that was evaluated.

The extension does not produce a diagnostic yet. `routing.explain` answers
`not-implemented`; the shape above is what a working implementation must return,
and `schemas/control-response.schema.json` describes the envelope that answer
arrives in.

## Retention and deletion

- The Keychain holds server credentials; the App Group container holds the
  subscription store and the tunnel hand-off (`tunnel/canonical-config.json`,
  `tunnel/settings.json`). That is everything that outlives the process.
- Removing a subscription deletes its Keychain items and its store record; the
  next tunnel start overwrites the hand-off. Deleting the app removes the
  Keychain items, the container, and the profile.
- There is no analytics store, no crash store, and no log file that Rovia
  writes. Rovia does not call `Logger` or `os_log` with user data, and the
  control API is a provider message rather than a log sink.
- There is no server-side retention question, because there is no server.

## Export

Export is explicit and user-initiated, or it does not exist.

- Today the app shows redacted, on-device views of subscription entries and
  routing diagnostics, and keeps them in memory. There is no share sheet, no
  file exporter, and no background upload.
- Any future export must be a user action, must show the exact payload before
  it leaves the app, must run the redaction rules in this document over the
  payload, and must say where the payload is going.
- The routing debugger has no text field, and no destination is typed into it.
  The only input it accepts is a choice from the content's own built-in samples,
  and it never writes that choice to disk, a log, or a diagnostic. If a typed
  destination is ever added, this document has to change with it: that is the
  point at which a value the user supplies would enter the app.

## Redaction, and where it can fail

Redaction is a control, not a guarantee. These are the known limits, stated so a
user does not rely on a stronger promise than the code makes.

- The debugger today has nothing to redact, because the user supplies nothing:
  the input is a built-in synthetic sample compiled into the app, so no hostname,
  address, or port a user cares about ever reaches the debugger. The limit to
  watch is the one that arrives with a typed destination, which this slice does
  not have. A future version that accepts one has to say here what it keeps, for
  how long, and how the redaction rules apply to it.
- A redacted display value keeps the scheme, host, and port. The host is the
  server the user chose, so a shared screenshot or an exported diagnostic can
  still identify the provider. Redaction removes the secret, not the identity
  of the server.
- That form is one form, produced the same way wherever a display value is
  written. The config model and the subscription parser had disagreed about the
  port — one kept it and one dropped it — so the persisted value depended on
  which code path had produced it. Both now keep the port, and a test compares
  them directly. One case is deliberately stricter than the other: a value
  carrying userinfo (`https://user:password@host/…`) is refused by the config
  path and replaced with the literal `redacted`, so neither the host nor
  anything from the credentials survives. The subscription path keeps the host
  for such a value; the two differ deliberately and the difference is recorded in
  `docs/architecture/next-spikes.md`.
- Redaction depends on parsing the value as a URL or a share link. A value that
  is not a URL falls back to the literal string `redacted`; a value with
  unusual encoding, an IDN or punycode label, an IPv6 literal, or a very long
  authority can be rejected and replaced, which hides more than intended.
- Secrets are not redacted at rest — they are *protected* at rest: a credential
  in the Keychain is protected by the device's Keychain protections and by the
  access group, not by a string transformation. A Keychain item is the one
  place a real credential exists, and the hand-off files never carry one — the
  canary test in `client/app/ios/RoviaAppTests` reads the written configuration
  and fails if a credential value appears in it.
- A future feature that introduces a new redacted shape must add a canary test.
  The existing canaries live in `core/subscription/Tests` and
  `client/app/ios/RoviaAppTests`; a canary that stops failing is a regression,
  not a passing test.
- Error text from the operating system, from `URLSession`, or from an engine is
  shown to the user only after mapping to a stable code. If a future change
  surfaces a raw error string, that change is a privacy regression and must be
  reviewed as one.

## Network egress and third parties

- Rovia opens no listener. There is no local HTTP server, no LAN listener, and
  no unauthenticated debug endpoint. Host-to-extension communication is defined
  as a versioned JSON provider message rather than a network service, and the
  extension implements the provider side of that contract:
  `PacketTunnelProvider.handleAppMessage` accepts an envelope of at most 64 KiB,
  answers `status.get` with the engine's lifecycle state, and answers every
  other declared method with `not-implemented`. No provider-message data is
  stored or logged either way.
- The only outbound connections are the ones the user's own configuration
  selects: the configured server, and the subscription URL the user supplied.
  The provider of that subscription sees the request, as any HTTP client does.
- The server operator selected for a connection sees the traffic it carries and
  the metadata that traffic implies. Selecting a proxy does not hide the
  connection from the operator.
- No third-party SDK, analytics backend, or attribution service is linked. The
  local Swift packages are listed in `tools/ci/local-packages.txt` and have no
  external dependencies, which `tools/ci/verify-lockfiles.sh` enforces.

## App Store privacy questions

The answers below are the project's position. The release owner must re-verify
them against the current App Store privacy label and App Review Guidelines
before submission, and must update this section if the answer changes.

| Question | Answer for this slice |
| --- | --- |
| Does the app collect data? | It handles data the user supplies, on the device, at the user's direction. No data is transmitted to the developer. |
| Is the data linked to the user's identity? | No. There is no account, no identifier, and no developer-side store. |
| Is the data used for tracking? | No. No tracking, no advertising identifier, no cross-app or cross-site sharing, no third-party SDK. |
| What is the data used for? | App functionality only: to configure the tunnel the user asked for and to explain routing decisions. |
| What categories could apply? | If a label is required, the closest description is user-provided content processed on device, not collected. This must be confirmed before submission. |
| What is the retention? | Keychain for credentials, App Group for the subscription store and the tunnel hand-off; everything else lives for the life of the app process. There is no server-side retention. |
| Can the user request deletion? | Removing a subscription deletes its Keychain items and its store record; deleting the app removes the Keychain items, the container, and the profile. There is no server to ask. |
| Does the app use data for advertising? | No. |
| Does the app download executable code? | No. The engine binary is the pinned artifact built by the gated pipeline and linked at build time; nothing executable is downloaded after installation. `docs/legal/app-store-distribution.md` records the App Review position. |
| Does the app open a local listener? | No. |
| Are there region-specific requirements? | The engine linked into the app carries licence obligations (libXray MIT, Xray-core MPL-2.0) that travel with the binary — see `licenses/` and `docs/legal/licensing.md`. Region-specific *engine* rules beyond that need legal review before shipping; see `docs/legal/app-store-distribution.md`. |

## Reporting a privacy problem

Treat a suspected leak as a security issue: follow `SECURITY.md`. Do not post
credentials, subscription URLs, or real diagnostic payloads in a public issue.
If a redaction failure is found, the report should include the shape of the
value that leaked, not the value itself.
