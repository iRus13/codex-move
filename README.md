# Move

**Switch Macs. Keep your Codex conversation and work files.**

Move is an experimental, community-built Codex skill for two Macs. After one-time setup, type **`move`** (or **`$move`**) in a chat. Move transfers that chat's history, its workspace, and recognized local attachments through your Dropbox, then creates a native continuation on the other Mac and requests that Codex open it.

Built to solve a personal workflow: starting work on a Mac mini and continuing on a MacBook without manually rebuilding context.

> **Early release:** actual transfers were verified in both directions on two Macs, with 38 automated tests passing before publication. Automatic opening requests were accepted, but on-screen opening is not yet independently confirmed. Linked Git worktrees are unsupported. This is not an official OpenAI product.

## What happens when you type `move`?

```text
Mac mini                 Your Dropbox                 MacBook
current chat + files  ->  signed transfer bundle  ->  native continuation
                                                    + verified local files
                                                     ↓
                                              type move to return
```

1. Move queues the selected chat and waits for the current response to finish.
2. A background receiver snapshots the history and workspace, hashes the files, and signs the transfer.
3. Your other Mac downloads the bundle through Dropbox and verifies the signature and content.
4. It imports the history, creates a continuation with a new chat ID, and requests opening in Codex.
5. A signed receipt confirms completion. The original remains available as a recovery copy.

The last small production round trip's final leg took about 36 seconds from sending to signed confirmation. This excludes the model response and is not a speed guarantee. Large workspaces and Dropbox hydration take longer.

## Install on both Macs

Requirements:

- Two Macs running a compatible Codex desktop app, signed in locally.
- Dropbox desktop on both, using the same private transfer folder. Keep the transfer folder available offline.
- Python 3.9 or newer. Codex's bundled Python works; a separate Python installation is also fine.
- Standard `~/.codex` profile for the native login receiver.
- Both Macs awake and logged in for immediate transfers.

**Start here: [Installation and pairing](docs/SETUP.md).** Installation alone does not pair the computers or start receiving.

If you use Codex to install skills, you can ask:

> Install the move skill from https://github.com/iRus13/codex-move, at skills/move. Read docs/SETUP.md and help me pair my two Macs using my private Dropbox folder. Do not transfer a real chat until the disposable round-trip check passes.

Alternatively, download this repository with **Code → Download ZIP**, extract it, and run the included **Install Move.command** on each Mac. Then follow the pairing guide.

## What travels?

| Content | Behavior |
| --- | --- |
| Selected chat and its history ancestors | Imported into a new native Codex continuation |
| Workspace files | Includes hidden, ignored, and untracked files; preserves structure |
| Empty directories and executable modes | Preserved |
| Supported symbolic links | Relocated; external targets are included where supported |
| Recognized local image/audio and absolute Markdown file links | Copied and their known history paths relocated |
| Web links or merely mentioned filenames | Not automatically downloaded or collected |
| Other chats, installed apps, running processes, goals and machine settings | Not migrated |

The receiving workspace is `~/Documents/Codex/Moved/<transfer-id>/workspace`. External attachments are in the neighboring `assets` directory. Original history snapshots are retained in `source-history`.

Continue in the **received copy**. The copies do not live-sync or merge. A later `move` transfers the latest work into another fresh destination folder.

## Limits and privacy

- **Linked Git worktrees** (`.git` is a pointer file) are rejected. Ordinary repositories with a `.git` directory can be copied.
- Codex history formats and experimental app-server APIs can change. Version mismatches may stop a transfer. Use compatible versions and repeat the disposable test after upgrades.
- This transfers the **whole selected workspace**, including `.env` files or other secrets if present there. Choose the workspace carefully. Workspace file contents are preserved, so absolute paths inside project configuration may still need adjustment.
- Signing provides authenticity and integrity, **not end-to-end encryption**. Dropbox receives the chat history and file contents under its normal account/storage protections. Use a private folder, not a publicly shared link.
- Local Move private signing keys and global Codex authentication databases are not part of the transfer. Never publish your configuration, transfer bus, receipts, or chat logs.
- Not every attachment representation is recognized. Missing detected assets and verification errors prevent success; a plain text mention does not make a file an attachment.
- The included native wrapper supports Apple silicon and Intel, targets macOS 12+, and is ad-hoc signed during installation. It is not Developer ID notarized. Codex itself may require a newer macOS. Respect normal macOS security and folder-permission prompts.

## Troubleshooting and development

- [Setup, status, stopping the receiver, and troubleshooting](docs/SETUP.md)
- [Architecture and test evidence](docs/DEVELOPMENT.md)
- [Report a bug](https://github.com/iRus13/codex-move/issues/new?template=bug_report.md)
- [Contribute](CONTRIBUTING.md)

Please report the macOS and Codex versions, transfer stage, and a **redacted** error. Do not attach full chats, private keys, or your Dropbox transfer folder.

MIT licensed. Contributions and reports from other two-Mac setups are welcome.
