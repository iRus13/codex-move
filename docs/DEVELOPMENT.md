# Architecture and verification

The runtime is Python standard-library code plus a small Swift/AppKit wrapper. It uses the installed Codex app-server stdio API and native rollout files. History imports depend on experimental, version-sensitive behavior.

- `engine.py`: snapshots, content-addressed blobs, hash checks, ancestry import, path relocation, strict projected history comparison.
- `rpc.py`: bounded stdio client; mutation timeouts are reported as uncertain outcomes.
- `signing.py`: Ed25519 signatures using macOS `ssh-keygen`; private keys stay local.
- `move.py`: queue, receiving loop, signed completion/error receipts, status.
- `native_service.py` and `receiver.swift`: a normal macOS app with folder permissions, child restart, and login launch.
- `pair.py`: pins an independently verified public key and refuses accidental re-pairing.

## Recorded pre-publication verification

38 automated checks passed for the original runtime and installer: 15 engine, 10 service, 4 signature, 9 installer. Coverage includes 75-turn pagination, real app-server imports, round trips, attached image relocation after removal of the source path, historical tool argument preservation, hidden files, modes, links, signature tampering, corruption, recovery, source-idle waiting, repeated moves, and signed error receipts.

Physical production tests passed Mac mini → MacBook → Mac mini → MacBook, including edits made on the destination. The final continuation contained six verified turns. The final small transfer took about 36 seconds from send to signed receipt. Actual on-screen opening remained unconfirmed. These are observations from one two-Mac setup, not a guarantee for every app version or filesystem.

Tested native CLI versions: 0.160.0 and 0.159.0-alpha.12.1. Earlier testing exposed a history projection mismatch with CLI 0.155.1. Prefer the matching desktop-bundled CLI rather than an unrelated global install.

## Run tests

From this repository root on macOS, put a compatible `codex` executable on PATH, then run:

```sh
python3 tools/build_installer.py
python3 -m unittest discover -s tests -p 'test_move_*.py' -v
```

Tests use temporary synthetic profiles. They do not need to send model prompts. Native history/service tests require the compatible installed app-server; pure file and signature tests do not establish desktop compatibility.

## Native wrapper

The bundled `receiver-universal.b64` contains an arm64 + x86_64 executable targeting macOS 12. Its SHA-256 is checked before installation:

`cd03da0b2b07d1797ac67e5c77a1fb99d0f34d39786477067bfe71a2bcd42a72`

The Swift source is included. To rebuild, use Xcode's Swift compiler for `arm64-apple-macos12.0` and `x86_64-apple-macos12.0`, combine with `lipo`, base64-encode the result, and deliberately update the expected hash in `native_service.py`. Rebuild the installer afterward. Compiler versions can change binary output; source builds are not claimed bit-for-bit reproducible.
