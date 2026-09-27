# ADR-0004: Engine licensing and distribution boundaries

- Status: Accepted as a release gate
- Date: 2026-09-24
- Owners: Rovia maintainers and legal reviewers

## Context

The proposed engines have different licenses and distribution conditions. Xray-core is MPL-2.0. The libXray wrapper is MIT-licensed but links or packages components with their own obligations. sing-box is GPL-3.0-or-later and its upstream license includes a name/association restriction for derivative works.

An official client or a successful iOS build does not grant a downstream project additional permission.

## Decision

- Xray/libXray is the first production candidate.
- sing-box is not bundled in the foundation or in an App Store build until legal review and distribution design are complete.
- The project keeps new Swift/core code provisionally MIT-licensed, but does not imply that every binary is MIT.
- Every exact source revision, artifact hash, license text, modification, and Corresponding Source obligation is recorded before release.
- An adapter does not erase copyleft or attribution obligations.

## Required release evidence

- Exact upstream source revisions.
- Build commands and toolchain versions.
- Complete notices and license texts.
- Source-offer or source-distribution procedure where required.
- App Store distribution review for encryption and VPN functionality.
- Written legal approval for any GPL-covered App Store variant.

## Non-legal-advice notice

This ADR is an engineering release gate, not legal advice. The project must obtain qualified legal review before distributing a GPL-covered engine through a platform store.
