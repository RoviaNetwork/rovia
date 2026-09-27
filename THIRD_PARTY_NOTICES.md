# Third-Party Notices

No third-party binary is bundled in the current foundation.

The following components are candidates for future integration and must be recorded with their exact source revision, build procedure, license text, notices, and redistribution obligations before being linked into a distributed app.

| Component | Intended use | Current status | License review |
| --- | --- | --- | --- |
| Xray-core | First production proxy engine | Not bundled | MPL-2.0; review covered files and Corresponding Source obligations |
| libXray | Apple XCFramework wrapper and structured API | Not bundled | MIT wrapper plus the licenses of wrapped Xray-core and dependencies |
| sing-box / Libbox | Future alternate engine | Disabled | GPL-3.0-or-later; separate App Store and naming review required |

The project does not infer a license permission from the existence of an official mobile client or from an engine's technical ability to compile for iOS.

Before a release, update this file with exact revisions and copy the complete applicable license texts into `licenses/`.
