# Embedded FreeImage / LibRaw licensing audit

Date: 2026-09-07. Scope: read-only inspection of the local macOS ARM64 `cadquery-ocp==7.8.1.1.post1` wheel and primary upstream licensing sources. No application code, installed binaries, or existing license archives were changed. This note does not certify the remaining native dependency inventory.

**Conclusion:** There is an upstream license route for commercial use of both libraries. The inspected local development/runtime installation is not prohibited merely because its use is commercial. An external commercial binary release containing this wheel is **not yet cleared by the available package evidence**: FreeImage/LibRaw license notices and the corresponding source/build provenance have not been assembled. The OCP wrapper's Apache-2.0 license does not relicense its embedded libraries.

## Local evidence

Inspected wheel: `.engineering-wheelhouse/cadquery_ocp-7.8.1.1.post1-cp312-cp312-macosx_11_0_arm64.whl` beneath `outputs/cabinet-flow`.

Inspected installed directory: `.venv-engineering/lib/python3.12/site-packages/OCP/.dylibs` beneath that same project.

| Binary | Native API result | Size | SHA-256 |
| --- | --- | ---: | --- |
| `libfreeimage.3.18.0.dylib` | `FreeImage_GetVersion()` = `3.18.0` | 812,960 bytes | `9cc96d1a508e2781803e6f27f4d612af13d1e746853768e5c14a96f430235c5c` |
| `libraw.23.dylib` | `libraw_version()` = `0.21.3-Release` | 1,124,176 bytes | `f1e1e9271ba7e37f3165fe9aaeac2378a4dbfb29f0a4678cb1e86cec741e3b64` |

`otool -L` confirms that FreeImage dynamically loads `@loader_path/libraw.23.dylib`. Both libraries load other separately bundled native dependencies. `libraw_capabilities()` returns 192, corresponding to ZLIB (64) and JPEG (128) in the official [0.21.3 capability enum](https://raw.githubusercontent.com/LibRaw/LibRaw/0.21.3/libraw/libraw_const.h). The upstream [capabilities implementation](https://raw.githubusercontent.com/LibRaw/LibRaw/0.21.3/src/utils/utils_libraw.cpp) does not expose a GPL-demosaic-pack flag, so this value cannot certify that optional GPL code is absent.

The wheel's only filename matching license/copying/copyright/notice is `cadquery_ocp/LICENSE`. Installed `OCP/` and the package's `.dist-info/` have no such files. At inspection time, `licenses/engineering/` had no FreeImage or LibRaw file; neither `upstream-license-sources.json` nor `installed-dependencies.json` mentioned either library. Therefore an audit limited to Python distribution metadata misses these native components.

## FreeImage 3.18.0

The [official licensing page](https://freeimage.sourceforge.io/license.html) offers **FIPL 1.0 or GPLv2/GPLv3**, explicitly identifies FIPL as a commercial-use route, and requires the chosen license text plus acknowledgement in an About box or manual. FreeImage itself is not presented there as LGPL.

Under [FIPL 1.0](https://freeimage.sourceforge.io/freeimage-license.txt), section 3.6 requires an executable notice that the covered source is available under FIPL and explains source availability. Section 3.2 specifically requires modifications made or contributed by the distributor to be available to executable recipients; electronic availability lasts at least 12 months initially, or six months after a later version of the particular modification. Sections 3.3 and 3.5 preserve attribution and describe changes. Section 3.7 permits a larger product with independently licensed code. Thus FIPL does not inherently require publication of the whole proprietary application, but an acknowledgement alone does not exhaust its requirements. For this wheel, retain an identifiable corresponding FreeImage source version and all applicable build patches; do not assume it is an untouched upstream binary.

Official source location: the [FreeImage download page](https://freeimage.sourceforge.io/download.html), source distribution for **3.18.0**. That page identifies its bundled LibRaw as **0.19**, whereas this installed wheel uses **0.21.3** and newer native dependencies. Consequently, the stock FreeImage 3.18.0 archive by itself is not verified as the complete build provenance for this wheel. No archive was downloaded during this audit.

## LibRaw 0.21.3

The release-specific [COPYRIGHT](https://raw.githubusercontent.com/LibRaw/LibRaw/0.21.3/COPYRIGHT) offers **LGPL 2.1 or CDDL 1.0** at the user's choice. It identifies additional BSD-style and MIT components. Those component acknowledgements must be preserved as applicable. Official source: [LibRaw 0.21.3 tag](https://github.com/LibRaw/LibRaw/tree/0.21.3).

**LGPL route:** The [release LICENSE.LGPL](https://raw.githubusercontent.com/LibRaw/LibRaw/0.21.3/LICENSE.LGPL) permits running a linked program (section 0) and permits an independently licensed application when section 6 is met. For distributed library binaries, section 4 requires corresponding source, including build/install scripts, with equivalent download access from the same place being one method. Section 6 requires library-use notice and license, permits user modification and reverse engineering for debugging those modifications, and supplies alternatives such as a suitable replaceable shared-library mechanism or relinkable materials. A `.dylib` filename alone does not establish that a signed/package-restricted application satisfies replacement requirements. Library modifications remain subject to the LGPL.

**CDDL route:** The [release LICENSE.CDDL](https://raw.githubusercontent.com/LibRaw/LibRaw/0.21.3/LICENSE.CDDL) permits commercial and larger-work distribution. Section 3.1 requires executable recipients to have reasonable access to the covered source under CDDL, with the license included in distributed source. Sections 3.2–3.3 cover modifications and preservation of notices; sections 3.5–3.6 allow other terms for the executable/larger application while preserving source rights. CDDL therefore provides an alternative to the LGPL linking conditions, not an exemption from source availability and notices.

The official [LibRaw explanation of optional demosaic packs](https://www.libraw.org/node/1288) distinguishes the main library from separate GPL2+ and GPL3+ additions. Such additions cannot simply be relabeled CDDL or FIPL. No evidence establishing their inclusion was found in this bounded audit; absence is also not certified without the actual build recipe and source inventory. The normal upstream 0.21.3 library has the dual-license route described above.

## Release status and concrete remaining work

1. Record explicit license choices for this distribution, for example FIPL for FreeImage and either LGPL 2.1 or CDDL 1.0 for standard LibRaw.
2. Archive the chosen full licenses, applicable upstream copyright/third-party notices, and a user-visible FreeImage acknowledgement and source-access notice.
3. Obtain the precise FreeImage and LibRaw source/build recipes/patches corresponding to these binaries. Preserve hashes and identify optional code; do not mark the upstream tag alone as a verified corresponding-source bundle.
4. Provide recipients the source and notices required by the chosen route. If using LGPL, verify replacement/relinking and ensure product terms preserve its required modification/debugging rights.
5. Audit all remaining bundled native libraries separately before claiming that the whole commercial binary package is cleared.

Suggested disclosure: **Real local CAD execution is installed and usable. Its OCP wrapper is Apache-2.0; embedded OCCT, FreeImage, LibRaw, and other libraries retain separate licenses. FreeImage and standard LibRaw have commercial-use paths. External redistribution remains pending completion of native notices, corresponding-source/build evidence, and the obligations of the chosen licenses.**
