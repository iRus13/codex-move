# Setup on two Macs

## 1. Install the skill

Download and extract the repository on each Mac. Review the source and run `Install Move.command` from the extracted directory. You can use:

```sh
/bin/sh 'Install Move.command'
```

The installer installs `~/.codex/skills/move`, verifies file hashes, and backs up a previous installation. Open a new Codex chat if the skill is not visible. It does not start a receiver or transfer data.

The commands below use `python3` as shorthand. Use an actual working Python 3.9+ interpreter. If your system Python asks for an Xcode license, do not accept it just for Move: ask Codex for its bundled Python with the `load_workspace_dependencies` tool instead. No Xcode compiler is required for the bundled native receiver.

## 2. Create a private Dropbox transfer folder

For example, `~/Library/CloudStorage/Dropbox/Codex Move/Transfers`. The physical path can differ between Macs, but it must refer to the **same synced folder**. Verify a harmless text file written on one Mac arrives on the other, then mark the folder available offline in Dropbox. Do not make it publicly shared.

## 3. Configure each Mac

On Mac A (example names `mac-mini` and `macbook`):

```sh
python3 "$HOME/.codex/skills/move/scripts/move.py" setup \
  --device mac-mini --peer macbook \
  --bus "$HOME/Library/CloudStorage/Dropbox/Codex Move/Transfers"
```

On Mac B, reverse the names:

```sh
python3 "$HOME/.codex/skills/move/scripts/move.py" setup \
  --device macbook --peer mac-mini \
  --bus "$HOME/Library/CloudStorage/Dropbox/Codex Move/Transfers"
```

Use simple unique names consisting of lowercase letters, numbers, or hyphens, starting with a letter (maximum 32 characters). Setup prints each Mac's public key. It refuses to replace an existing configuration.

## 4. Pair the public keys

On each Mac, the public key is `~/.codex/move/signing-key.pub`. Exchange **only the `.pub` file** using AirDrop or another trusted channel. Compare the received public key with the one displayed on the other Mac. Do not automatically trust a key just because it appeared in Dropbox.

On each Mac, pin the other Mac's public key (adjust the downloaded file path):

```sh
python3 "$HOME/.codex/skills/move/scripts/pair.py" \
  --key-file "$HOME/Downloads/other-mac.pub"
```

The helper rejects your own key and refuses to replace an existing different peer key. Never transfer `signing-key` without `.pub`.

## 5. Start the background receiver on both Macs

```sh
python3 "$HOME/.codex/skills/move/scripts/move.py" install-service
python3 "$HOME/.codex/skills/move/scripts/move.py" status
```

This creates `~/Applications/Codex Move Receiver.app`, records the interpreter you used, and installs a per-user login LaunchAgent. Allow the receiver access to your selected work folders through normal macOS prompts. `running: true` plus a recent heartbeat indicates an active receiver; it does not prove a transfer succeeded.

The default CLI detector recognizes the tested ChatGPT.app bundle layout and otherwise falls back to `codex` on PATH. If your installed desktop bundle has a different location, set the local config's `codex` value to the **absolute path of its matching executable** before testing. Ask Codex to inspect the installed app rather than guess that path.

## 6. Check a disposable round trip

1. Create a disposable Codex chat with its own small folder on Mac A. Ask it to create a text file containing a marker.
2. Send `move` or `$move` and let the response finish. Leave both Macs awake.
3. On Mac B, confirm the received chat is available, recalls the marker, and reads the copied file. Confirm whether it opened automatically.
4. Edit the file in the received chat and send `move` again.
5. On Mac A, confirm the edit and history arrived. Ask Codex to check the signed completion status.

Only then use it for important work. Original chats and files remain available. Transfer duration varies with workspace size, Dropbox, and app versions.

## Daily use

Type **move** in the chat you want to continue on the other Mac. Use **$move** if implicit skill selection does not trigger. Continue in the received copy; the old copy is a recovery copy, not a live mirror.

## Troubleshooting

Ask Codex to check Move status and the error message for the selected chat. To check manually:

```sh
python3 "$HOME/.codex/skills/move/scripts/move.py" status
python3 "$HOME/.codex/skills/move/scripts/move.py" status --thread YOUR_SOURCE_CHAT_ID
```

- **Not paired:** complete public-key exchange on both Macs.
- **Waiting for source:** let its current response finish. Persistent goals or ongoing writes can keep it busy.
- **Sent, no receipt:** check destination is awake, Dropbox is syncing, both receivers are running, and files are downloaded.
- **Permission denied:** inspect the receiver's folder permissions using normal macOS settings. Do not bypass system protections.
- **History verification failed:** preserve the data; check both desktop/CLI versions. Do not weaken the verifier or repeatedly create continuations.
- **Transferred but not visible:** `open_requested` confirms only that macOS accepted the request. Look for the received continuation in Codex. Report this separately from a content-transfer failure.
- **Linked Git worktree:** unsupported. Use Codex's native host handoff if available and suitable.

Local status/logs live under `~/.codex/move/`. Logs can contain private paths: redact before sharing.

## Stop or uninstall

Ask Codex to stop the Move receiver, or unload its exact per-user service:

```sh
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.local.codex-move.receiver.plist"
```

Then quit **Codex Move Receiver** with Activity Monitor and confirm its Python child has stopped. Preserve `~/.codex/move`, received workspaces, and original chats until you have verified your work. Removing the skill alone does not stop an already running receiver. Do not delete a shared transfer folder while a transfer is in flight.

To upgrade, stop the receiver first, install the new skill, and run `install-service` again. Repeat the disposable round trip. Keep the existing pairing/configuration; the installer does not erase it.
