---
name: move
description: Move this Codex chat, its history, workspace files, and local attachments to the other Mac when the user says move, $move, or move this chat. Use the paired Move receiver to queue an automatic transfer and open its native continuation on the receiving Mac.
---

# Move

Treat a bare `move` as this chat and its workspace. The user has authorized moving it to the paired Mac. Do not ask for permission again. Transfer only the selected chat, its native history ancestors, workspace, and referenced files. Preserve source data as recovery copies.

Use the `scripts/move.py` adjacent to this skill. Resolve its absolute path from the loaded skill location. Read `runtime_python` from the local Move configuration and use that exact absolute interpreter path for every command below (shown as `python3` for brevity). Do not assume the shell’s default Python works; use an available Python 3.9+ interpreter without accepting system licenses for the user. If setup is absent, use Codex’s bundled Python from `load_workspace_dependencies`. Python 3.9 or newer is supported. The per-device configuration is `${CODEX_HOME:-~/.codex}/move/config.json`; it contains the paired device and local paths. Do not infer the destination from a hardcoded username.

## Queue the current chat

1. Read the exact current thread ID from `CODEX_THREAD_ID` if present. Otherwise identify it from the current workspace and authoritative Codex thread tools. Never guess an ID from a title or choose the most recent unrelated chat. Use the actual workspace root, not the home folder or all of Documents.
2. Run `python3 <skill>/scripts/move.py status`. If `running` is false, start the already configured receiver with `install-service`. If a service is already loaded but not running, inspect its error log and repair the concrete issue before queueing. If configuration or peer pairing is missing, follow Setup below; do not claim readiness.
3. Run `python3 <skill>/scripts/move.py queue --thread <id> --workspace <absolute-workspace> --title <actual-title>`. Inspect the returned state. Repeated calls while queued or sending reuse the same request. A request after an earlier completed move creates a fresh continuation including later source work.
4. **End the source response promptly.** The receiver deliberately waits for the current turn to finish so it includes the final response. Do not wait inside this turn for its own transfer to finish. Tell the user that the move is queued and will continue after this response. Avoid further source work after queueing. An active persistent goal may continue creating turns; do not mark that goal complete or paused merely to force a transfer.

The background receiver starts Dropbox when necessary, waits for an idle source, snapshots files, signs the transfer, and waits for the paired Mac's signed receipt. The other Mac must be awake with Dropbox and its Move receiver running. A queued transfer can wait for that Mac to return. Skill installation alone does not enable receiving.

## Status and evidence

Use `python3 <skill>/scripts/move.py status --thread <source-id>` from a later turn or another chat. `complete` requires a matching signed destination receipt and verified native history/files. The destination uses a native continuation with a new ID and relocated paths; original chats remain available for recovery. Do not describe a Markdown transcript as native history.

`open_requested` means macOS accepted the Codex link request. It does not prove the chat became visible. Report actual visibility only when the destination app or the user confirms it. Do not bypass a denied UI surface to get that confirmation.

Receivers use a fresh directory for each move, preserve existing user edits, verify hashes, and import only the selected chat's history chain. Credentials, global chat databases, and machine settings are not transferred. Local signing keys never belong in Dropbox. Source snapshot logs are preserved unchanged; transport copies relocate known workspace and attachment paths.

## Errors and coverage

Inspect the specific outgoing/incoming status and receiver-error.log under the configured state directory. A stalled heartbeat alone does not prove the process is stopped; inspect the receiver lock and service/process state. Never blindly retry an uncertain native creation; the runtime records and reconciles it by its unique workspace.

The runtime includes hidden, ignored, and untracked workspace files; empty directories; executable modes; supported symlinks; and recognized local image/audio and absolute Markdown file attachments. Missing attachments, damaged data, unsafe paths, and unsupported filesystem entries stop the transfer. It currently rejects linked Git worktrees with a `.git` pointer; report that limitation and use native cross-host handoff only if its matching-project requirements are met. Never silently omit files. Do not promise migration of unrelated chats, application installs, running processes, or machine-specific task goals/settings.

## Setup and pairing

Setup is performed once per Mac and must be tested before calling Move ready:

- Install the same skill/runtime version on both Macs. Use a shared Dropbox folder specifically for Move.
- Run `setup --device <unique-device> --peer <other-device> --bus <shared-folder>` once on each Mac. Existing configuration is preserved by refusing replacement.
- Exchange the generated **public** keys through a trusted channel chosen by the user. Run `scripts/pair.py --key-file <peer-public-key-file>` to pin the independently received key in the local config. Never trust a Dropbox public-key file automatically, never copy private keys, and do not send messages to another chat without user authorization.
- Run `install-service` on both Macs, then perform a disposable two-device round trip before using Move for important work. This installs the bundled universal native Codex Move Receiver.app and launches it at login; Xcode is not required. macOS may request folder access for that app; honor its normal permission flow. Plain Python started by launchd cannot reliably read Documents, even when Codex can. Verify service process state and a recent completed cycle on both Macs. Verify files, full native history, and destination opening separately.
- If the other Mac is disconnected, finish local preparation and ask the user to wake it. Do not repeatedly attempt uncertain message delivery or imply an offline install succeeded.
