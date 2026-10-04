# Licensing

## What the MIT grant in `LICENSE` covers

Rovia's own work: the Swift packages under `core/`, `engines/`, `platform/`, and
`client/`, the JSON schemas, the fixtures, and the tooling.

`LICENSE` is kept as the unmodified MIT text and nothing else, deliberately. A licence
file that a machine can read is worth more than one with a paragraph appended: GitHub
uses the file to label the repository, and a note inside it turns the detection into
"unrecognised". This document is where the qualification lives, and the README links
to it.

## What it does not cover

It is **not** a statement about the licences of anything a build might bundle.

No third-party binary is committed to this repository. The engine lock pins
xray v26.9.9 — exact source commit, verified source archive digest, and the
artifact digest every gated build reproduces — and the build pipeline produces
`LibXray.xcframework.zip` from that pin. When the app links the artifact, the
applicable terms are:

| Component | Licence | Consequence for a distributed build |
| --- | --- | --- |
| Xray-core | MPL-2.0 | File-level copyleft. Covered files and any modifications must stay available, and the notices must travel with the binary. Rovia modifies no covered file: the Corresponding Source is the upstream repository at the pinned commit `52a412d9e2f5`, and the build recipe is `tools/build-engine/xray/build-apple.sh`. |
| libXray | MIT (wrapper) | The wrapper's licence does **not** override the obligations of the Xray-core code it packages. |
| sing-box / Libbox | GPL-3.0-or-later | **Not enabled.** A GPL-covered engine in an App Store build requires a compliant distribution model, source availability, and legal review before it is shipped. |

The complete license texts are in `licenses/` (`libXray-MIT.txt`,
`Xray-core-MPL-2.0.txt`), and `THIRD_PARTY_NOTICES.md` records the exact
revisions and the redistribution obligations. `docs/adr/0004-engine-licensing.md`
records the decision and its reasoning. The project does not infer a licence
permission from the existence of an official client, or from an engine's
technical ability to compile for iOS.

Nothing here is legal advice.
