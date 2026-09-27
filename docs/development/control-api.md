# Internal control API

The host app and Packet Tunnel extension use provider messages for the MVP. The payload is a versioned JSON envelope, in both directions: `schemas/control-api.schema.json` describes the request and `schemas/control-response.schema.json` describes the response. The host-to-extension transport is `NETunnelProviderSession.sendProviderMessage`.

What exists today is the provider side: `PacketTunnelProvider.handleAppMessage` validates the envelope, rejects anything above 64 KiB, answers `status.get`, and returns `not-implemented` for the other declared methods. The host side is not wired in this slice, so no request currently travels from the app to the extension.

## Request

```json
{
  "apiVersion": 1,
  "requestID": "request-uuid",
  "method": "status.get",
  "payload": {}
}
```

Messages larger than 64 KiB are rejected. Unsupported API versions, methods,
malformed JSON, and missing payload objects receive an error response.

Three rules make the envelope closed, and the extension enforces all three,
because a schema cannot run inside a Packet Tunnel extension:

- the field set must be exactly `apiVersion`, `requestID`, `method`, `payload`,
  so a fifth field is refused rather than ignored;
- `requestID` is 1 to 128 characters, the same bound
  `schemas/control-response.schema.json` puts on the echoed identifier, so a host
  can always match a refusal to its own request; and
- every method's payload must be an object, and `status.get`'s must be empty.

The numbers live in one `ControlContract` enum in
`client/app/ios/RoviaTunnel/PacketTunnelProvider.swift`.
`tools/ci/test_validate_schemas.py` reads that file and both schemas and requires
them to agree, so a bound changed in one place and not the other fails the suite
rather than the tunnel.

`status.get` takes no parameters: its payload must be an empty object, which `schemas/control-api.schema.json` enforces with `additionalProperties: false` and `maxProperties: 0`. The request cannot become a channel for host state that the extension did not already report. `routing.explain` and `group.select` have method-specific payload definitions; the remaining declared methods accept an object payload until their domain services exist.

One limit is stated rather than implied: the schema defines a payload shape for
`routing.explain` and for `group.select`, and the provider does not check either.
Neither method is implemented — it answers `not-implemented` before it reads the
payload — and a method that starts answering has to validate its payload against
the declared shape in the same commit that makes it answer. The other three
declared methods take an object payload with no shape of its own yet.

`fixtures/control/` holds one positive fixture per implemented request shape:
`status-request.json`, `routing-diagnostic.json`, and
`group-selection-decision.json`, plus two negative request fixtures,
`oversized-request-id.json` and `request-with-extra-field.json`. `tools/ci/validate-schemas.py` validates them, requires negative probes with extra fields, cross-role reason codes, a non-empty `status.get` payload, and a second `apiVersion` to be refused, and a decoded diagnostic must not grow a field the schema does not declare.

## Response

```json
{
  "apiVersion": 1,
  "requestID": "request-uuid",
  "ok": true,
  "result": {
    "state": "disconnected"
  }
}
```

A refusal:

```json
{
  "apiVersion": 1,
  "requestID": "unknown",
  "ok": false,
  "error": "invalid-request"
}
```

`schemas/control-response.schema.json` states the envelope, and it is closed at
every level. The rules it makes machine-checkable are:

- `apiVersion` is the constant 1 and `requestID` is a non-empty string, echoed
  from the request. A request too malformed to read an identifier from is
  answered with the literal `"unknown"`.
- `ok: true` requires `result` and forbids `error`; `ok: false` requires `error`
  and forbids `result`. There is no third shape, so a caller never has to guess
  whether a field means success or failure.
- `error` is a closed set, `invalid-request` and `not-implemented`. A refusal
  carries a stable code and never a message, so nothing from the request or the
  device can echo back into the response.
- `result` is a closed object. Today the only one that can be produced is the
  status envelope, with a non-empty bounded `state`; the only value this build
  emits is `disconnected`, because no engine is enabled. A method that returns
  data adds its own closed shape and a probe rather than widening this one.

`fixtures/control/` holds three positive response fixtures
(`status-response.json`, `not-implemented-response.json`,
`invalid-request-response.json`) and six negative ones, and
`tools/ci/validate-schemas.py` adds eight generated probes. The negative set
covers an `ok` response that also carries an error, a refusal that also carries a
result, a missing `ok`, a missing `result`, a missing `error`, an extra envelope
field, an extra field inside `result`, an unknown error code, an empty
`requestID`, an empty `state`, and a second `apiVersion`.
`tools/ci/test_validate_schemas.py` also deletes the two conditional branches
and requires the checker to fail, so the ok/refusal split cannot quietly stop
being enforced.

No LAN HTTP listener is opened. A loopback adapter may be added for debug builds only, with authentication and an explicit opt-in.
