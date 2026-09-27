## What this changes

<!-- One or two sentences. If it changes a boundary, say which one. -->

## Why

<!-- The problem, or link the issue. -->

Closes #

## Checklist

- [ ] `./tools/ci/run-tool-tests.sh` passes locally.
- [ ] Every Swift package in `tools/ci/local-packages.txt` passes, or the reason it
      cannot is stated below.
- [ ] `xcodebuild … test` passes if this touches the app or the extension.
- [ ] New behaviour has a test that **fails without this change**. If you cannot name
      the failure, say so in the PR rather than shipping the test anyway.
- [ ] No real credential, host, subscription URL, or Apple team ID appears anywhere in
      the diff. Synthetic values only — `synthetic.example` and friends.
- [ ] Documentation that describes this behaviour is updated in the same commit.
- [ ] If this touches parsers, secrets, routing, tunnels, signing, or CI, the security
      and privacy impact is described below.

## Security and privacy impact

<!--
Required for: core/config, core/subscription, core/routing, platform/apple,
client/app/ios, engines, tools/ci, tools/release, .github/workflows, schemas.

Answer these, or say why the change cannot affect any of them:
  - Can this change what the product does with a credential?
  - Can it change what leaves the device, or what a diagnostic contains?
  - Can it weaken a release gate, or make one pass when it should refuse?
-->

## Notes for the reviewer

<!--
What you would want challenged. Which decision you are least sure of, and why you
made it anyway. A reviewer reading this first is a better use of everyone's time.
-->
