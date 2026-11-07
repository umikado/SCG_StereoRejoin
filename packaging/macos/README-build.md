# macOS test build

Target: Apple Silicon (arm64), macOS 14 or later. Tested on macOS 26.7.2.

Version 1.0.2 builds on main merge 8965429d899cdc980d05452729577cc9223579c5 (tree equivalent to b5cf31ea01c744def3c61b5bf66f91eb33e30219). This local revision adds streaming support for stereo sources with exactly one non-silent channel, mixed mono/stereo pairing, safe full-payload source hashing, selected-channel iXML metadata, regression tests and updated GUI/docs. Two-active-channel sources are refused rather than mixed or discarded. The 1.0.2 GUI adds English, Simplified Chinese and Japanese labels, reports, dialogs and hover help; audio-engine modules are unchanged from the tested 1.0.1 build. The repository changes are local and have not been published.

Use the official python.org Python 3.14.3 installation with its Tcl/Tk 8.6.17 frameworks. Run `packaging/macos/build.sh` from an Apple Silicon Mac in a normal graphical login session. It creates an isolated .venv, installs the pinned PyPI dependencies, runs pytest, and builds an ad-hoc-signed bundle. It does not publish, notarize, install system-wide, or alter any input audio.

Tkinterdnd2 0.7.0 includes TkDND 2.10.3. The Apple Silicon binary requires macOS 14, so the bundle minimum is 14.0. A local hook deliberately collects the correct arm64 / Tcl 8 native binary plus all its scripts; drag-and-drop is retained.

Build output: dist/SCG StereoRejoin.app

Safe bundled self-test, using synthetic WAVs in a fresh temporary directory:

`dist/SCG StereoRejoin.app/Contents/MacOS/SCG StereoRejoin --self-test /absolute/path/to/a-new-result.json`

Quote the executable path when running from a shell. The result filename must not already exist. The bundled test loads real Tk and TkDND, builds the GUI, uses its join worker on mono, normal/reversed single-sided stereo, mixed mono/stereo and all-silent pairs, verifies bit-exact stereo and unchanged inputs, refuses existing outputs and two-active-channel sources, and verifies Dry run. It also switches all three languages through the selector event, checks translated labels and dialogs, tests all nine hover targets appearing above their controls and disappearing on leave, rerenders existing logs, and joins a synthetic stereo pair in each language. It does not simulate an actual physical Finder drag.

The bundle has no Developer ID signature or Apple notarization. Code signing is ad hoc only. Do not weaken Gatekeeper globally. Native bundle binaries were checked for architecture, system-only external linkage and valid in-bundle links. Use ditto to archive the .app so symlinks and executable permissions are preserved.
