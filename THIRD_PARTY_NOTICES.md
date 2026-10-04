# Third-Party Notices

This repository bundles one third-party binary: the pinned libXray/Xray-core
engine, recorded in `engines.lock.json` and verified byte-for-byte by
`tools/ci/verify-engine-checksums.sh`.

| Component | Use | Exact source revision | License |
| --- | --- | --- | --- |
| libXray | Apple XCFramework wrapper and structured API | `50b95979f5db551bd273165cf469e5daaf791341` (`v26.9.9`), `https://github.com/XTLS/libXray` | MIT — full text in `licenses/libXray-MIT.txt` |
| Xray-core | Production proxy engine, packaged by libXray | `52a412d9e2f5` (`v1.260327.1-0.20260908222543-52a412d9e2f5` in `go.mod` of the pinned libXray), `https://github.com/XTLS/Xray-core` | MPL-2.0 — full text in `licenses/Xray-core-MPL-2.0.txt` |
| sing-box / Libbox | Future alternate engine | Disabled; not bundled | GPL-3.0-or-later; separate App Store and naming review required |

Redistribution obligations and how Rovia meets them:

- **libXray (MIT).** The license text ships in this repository
  (`licenses/libXray-MIT.txt`) and must ship in any distributed build's
  notices.
- **Xray-core (MPL-2.0).** MPL-2.0 is a file-level copyleft license. The
  covered files are the unmodified upstream sources of the pinned commit;
  Rovia modifies none of them, so the Corresponding Source is the upstream
  repository itself at the exact revision above. The build recipe that turns
  those sources into the bundled binary is `tools/build-engine/xray/build-apple.sh`,
  and `tools/reproducibility/verify-xray.sh` proves the recipe produces the
  recorded bytes. The license text ships in `licenses/Xray-core-MPL-2.0.txt`
  and must ship in any distributed build's notices.
- The project does not infer a license permission from the existence of an
  official mobile client or from an engine's technical ability to compile for
  iOS. `docs/adr/0004-engine-licensing.md` records the decision.
