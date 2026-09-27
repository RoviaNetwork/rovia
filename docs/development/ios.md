# iOS development

## Requirements

- Xcode with an iOS SDK
- An Apple Developer organization for a distributable Packet Tunnel build
- A real team identifier in `Config/BundleIdentifiers.xcconfig` for signed builds
- Registered app and extension App IDs
- NetworkExtension packet-tunnel capability
- An App Group shared by the host and extension
- A physical iPhone for tunnel acceptance

The simulator is useful for SwiftUI and pure-domain tests. It is not evidence that a production VPN configuration, entitlement, extension lifecycle, or packet path works. The current `ROVIA_TEAM_ID` value is intentionally empty; a signed archive must fail until an organization configures it.

## The app depends on the domain packages

`client/app/ios/RoviaApp.xcodeproj` links the local Swift packages
`core/config` and `core/routing` through `XCLocalSwiftPackageReference`
entries, and the `RoviaApp` and `RoviaAppTests` targets both declare the
`RoviaRouting` and `RoviaConfig` product dependencies. The app has no copy of
the routing rules: `CanonicalRouteBridge` converts the app's display models into
the canonical `RouteSet` and `RouteInput`, calls `RouteEvaluator.explain`, and
renders the returned `RoutingDiagnostic`.

`tools/ci/test_app_dependencies.py` is the gate, and it is a mutation suite. It
parses the project into objects and requires `RoviaApp` *and* `RoviaAppTests` to
declare and link both products, with resolvable package paths and every product
dependency pointing at a real local package. On the Swift side it extracts every
declaration in the app sources and applies rules rather than names: a range type,
a host normalizer in either spelling, a containment predicate, a matcher
predicate that returns a verdict, a decision function that returns a value of its
own, and — in the sources the app target compiles — a string compared by suffix
or prefix. A `Codable` conformance added to `RoutingDecisionTrace` or
`RuleEvaluation`, by a declaration, an extension, a wrapper, a stored property, a
collection, or a function that encodes one, is refused, and so is a body that
accepts a raw trace and reaches for a store, a serialiser, or one of the log and
message channels: `print`, `os_log`, `OSLog`, `Logger`, `logger`, `debugPrint`,
`dump`, `NSLog`, and `sendProviderMessage`.

Each rule is proven by a mutation: the test copies the repository, breaks that one
property, and requires the check to fail. **47 mutations plus 7 legitimate
shapes**, of which 9 are package-dependency mutations, 16 write a second route
evaluator, 20 give a raw trace somewhere to live, and 2 are contract deletions.
The 7 shapes must *not* be flagged, and they are not part of the 47: they are the
cases the check has to leave alone, because a gate that cries wolf is a gate
people turn off. The suite copies the tree 69 times, which is most of its
25–90 seconds across the runs recorded in this repository's verification record, which is a measurement on one x86_64 Mac and not a bound. That figure is measured by counting `Workspace` instantiations, one per copy,
not by counting `shutil.copytree` calls, which recurse; the test enforces only the
bracket the mutation and test counts imply.

What it does not claim is written in the gate's own docstring, and repeated here
because a limit that lives in one file is a limit nobody reads. It reads
declarations and bodies, not Swift: an operator overload is not a declaration it
finds, a body that avoids every signal — normalises nothing, names nothing about
ranges or hosts or matchers, and calls nothing that looks like a match — is not
visible to it, and a code-generated body is outside it entirely. A stored
`RuleEvaluation` is deliberately allowed, because the canonical evaluator builds a
local one while it works and a local is indistinguishable from a property without
scope analysis; `RuleEvaluation` holds a rule identifier and a matched matcher
rather than the input, so its `Codable` conformance is the whole risk. And it
reads the repository, not the build: a link it does not model would be reported as
not linked, which fails closed.

Two build settings matter for that dependency:

- The Debug configuration sets `ONLY_ACTIVE_ARCH = YES`, which is Xcode's own
  default for a new project and which this hand-written project was missing.
  Without it the app target compiled both simulator slices while the SwiftPM
  package targets compiled only the active one, and the app's other slice failed
  with `Unable to find module dependency: 'RoviaRouting'`.
- Derived data must stay outside the checkout, for the reason described in
  `docs/development/ci.md`.

## Local package tests

Every entry in `tools/ci/local-packages.txt`, which is the same list the lockfile
verifier, the SBOM generator, and the release workflow all read:

```text
swift test --package-path core/config
swift test --package-path core/routing
swift test --package-path core/subscription
swift test --package-path engines/api
swift test --package-path engines/xray
swift test --package-path engines/singbox
swift test --package-path platform/apple
```

The last three were missing from this list, which is how a reader could conclude
the engine adapters and the Apple platform layer were untested. They are not: the
engine adapters carry the adapter-boundary tests, and `platform/apple` carries the
Keychain and App Group store tests. `tools/ci/test_ci_checks.py` requires this list
to match the file, so a package added to `local-packages.txt` cannot be left out of
the documented commands.

## App model tests

The host app keeps its observable model, `AppModel`, and its immutable `AppSnapshot`, in `client/app/ios/RoviaApp/`. They are covered by the `RoviaAppTests` unit-test target:

```text
xcodebuild \
  -project client/app/ios/RoviaApp.xcodeproj \
  -scheme RoviaApp \
  -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  test
```

Any installed iPhone simulator works. To let `xcodebuild` pick one, resolve the device first:

```text
SIMULATOR_ID="$(xcrun simctl list devices available --json | python3 -c '
import json, sys
devices = json.load(sys.stdin)["devices"]
for runtime in sorted(devices, reverse=True):
    for device in devices[runtime]:
        if device.get("isAvailable") and device["name"].startswith("iPhone"):
            print(device["udid"])
            raise SystemExit
raise SystemExit("no available iPhone simulator")
')"
xcodebuild -project client/app/ios/RoviaApp.xcodeproj -scheme RoviaApp -configuration Debug \
  -destination "platform=iOS Simulator,id=$SIMULATOR_ID" test
```

`RoviaAppTests` is a host-less logic test bundle. It compiles `AppModel.swift`, `AppSnapshot.swift`, and `CanonicalRouteBridge.swift`, the same sources the app target compiles — the bridge included, because the tests assert that the debugger's display model agrees with the canonical evaluator, which means the bridge itself has to be under test; and links `XCTest` implicitly through the unit-test product type. It needs no test host, so the model is exercised without launching the app. It does not cover the SwiftUI views; presentation is checked by building, installing, and launching the app.

The app target itself is built without signing, which is what CI runs:

```text
xcodebuild \
  -project client/app/ios/RoviaApp.xcodeproj \
  -scheme RoviaApp \
  -configuration Debug \
  -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  build
```

Install and launch on a simulator, pointing at the built product rather than the project:

```text
xcrun simctl install booted <build-products-dir>/Rovia.app
xcrun simctl launch booted io.rovia.client
```

The app bundle identifier is `io.rovia.client`, and the test bundle is `io.rovia.client.tests`; both come from `Config/BundleIdentifiers.xcconfig`, which every target, including the test target, uses as its base configuration.

The model reports engine availability from `UnavailableTunnelController`, so the app cannot report a connected tunnel in this build. Passing tests and a successful launch are not evidence of a working VPN.

## Project layout

The initial Apple source lives under `client/app/ios/`. The Packet Tunnel extension has its own `Info.plist` and entitlement. The host app and extension must be embedded as separate targets in an Xcode project created with the organization's identifiers and signing settings.

## Manual packet-flow gate

Before adding Xray, verify that the extension can:

1. Apply minimal network settings.
2. Read packets from `packetFlow`.
3. Write packets back through `packetFlow`.
4. Stop and restart without a leaked reader task.
5. Pass IPv4 and IPv6 cases on a physical device.

The foundation intentionally stops before claiming proxy connectivity.
