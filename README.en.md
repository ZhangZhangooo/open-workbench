# OpenWorkbench

**Let the AI come to you, instead of you always asking it.**

Before you've looked at your phone in the morning, it's already picked out the emails that
actually matter today — and drafted the replies that need sending, waiting for you to confirm.
You say "print this attachment" in WeChat, and paper comes out. You take a photo on your phone,
and it's already on your computer.

It connects the things **already on your machine** — Ollama, OpenClaw, files, a real terminal,
email, printers — into one interface. **Zero third-party dependencies** (Python standard library
only, nothing to `pip install`), and your data never leaves your machine.

```bash
git clone https://github.com/ZhangZhangooo/open-workbench
cd open-workbench
python server.py 8777        # → http://127.0.0.1:8777
```

**On Windows, just double-click `start.bat`** (starts the service, opens the browser, restarts
on crash). The one-click Ollama / OpenClaw installer is there too, but you can skip it for now —
get the UI running first, worry about models later.

<details>
<summary><b>Don't want to install Ollama / OpenClaw yourself?</b></summary>

| System | Command |
| --- | --- |
| Windows | `powershell -ExecutionPolicy Bypass -File install.ps1` |
| macOS / Linux | `sudo ./install.sh` |

The script installs/starts Ollama, pulls the chat model `gpt-oss:120b-cloud` and the vision model
`gemma4:31b-cloud`, installs OpenClaw, then generates a `config.json` pointing at your local Ollama.
Every step is printed and waits for you to press Enter; add `-Yes` / `--yes` to run unattended.

**It never overwrites an existing `config.json`** — it backs up to `config.json.bak.<timestamp>`
first, and only writes when yours is missing or still at factory defaults.

> Both models are Ollama **cloud** models — a few hundred bytes of proxy, no weights downloaded,
> so they pull in seconds. For fully offline, pull your own (`ollama pull qwen2.5:7b`).

**macOS / Linux: run it from the project directory and keep the `./`** — `.` isn't in `$PATH`,
so bare `install.sh` fails with `command not found`.

**Why the whole script runs as root**: on mac, installing Ollama / Node / OpenClaw needs privileges
almost everywhere. But `brew` and `ollama` are deliberately dropped back to *your* user — brew
refuses to run as root, and `ollama pull` as root would download models into `/root/.ollama`
that your everyday `ollama` can't see or write to.

**OpenClaw is a special case**: Homebrew's openclaw is a **cask** (GUI app only, no CLI), but the
workbench needs the CLI to reach the gateway. So after the client the script also installs the CLI —
official script first (`curl -fsSL https://openclaw.ai/install.sh | bash`), falling back to
`npm install -g openclaw@latest --allow-scripts=openclaw`.

**Windows "file is not digitally signed"**: downloaded `.ps1` files carry a "from Internet" mark
and get blocked. Either use the `-ExecutionPolicy Bypass` command above, run
`Unblock-File install.ps1` first, or save the file to a local drive (D:\…) where that mark is absent.

</details>

## Screenshots

| Dashboard | Projects |
| --- | --- |
| ![Dashboard](docs/screenshots/home.png) | ![Projects](docs/screenshots/projects.png) |

| Module overview | Tools |
| --- | --- |
| ![Features](docs/screenshots/features.png) | ![Tools](docs/screenshots/tools.png) |

> Screenshots are from a clean local instance with no personal data.

---

## What it actually does for you

| You say | It does |
| --- | --- |
| It's morning, you haven't checked email | A scheduled job surfaces today's important mail and drafts the replies that need sending, for you to confirm |
| "Print this attachment" in WeChat | Finds the printer, prints. Paper comes out. |
| You upload a photo from your phone | It lands on your computer **byte-for-byte, no re-encoding** (EXIF intact) |
| "What haven't I finished this week?" | Reads your todos, tells you the next step on each |
| "Save this" | Writes to your knowledge base / inbox / projects — via an approval queue, nothing lands until you confirm |

---

## Features

**Light to run**

- **Zero third-party dependencies**: Python standard library only. **No requirements.txt.**
- **One process**: `server.py` serves the frontend *and* the `/api/*` backend.
- **A real terminal**: built on ConPTY (Windows) — not a fake shell in a `<div>`.
- **Your data stays yours**: `data/app.db`, exportable backup.

**It works for you, not just answers you**

- **Scheduled automations**: morning email digest, daily review, weekly review — scheduled with
  OpenClaw's own cron.
- **A real MCP server**: `wb_mcp.py` registers read-email / add-todo / save-note / status as
  **standard MCP tools**. One `openclaw mcp add` and OpenClaw *calls tools* — instead of guessing
  URLs from a prompt.
- **Two-way WeChat**: a WeCom self-built app plus the "WeChat plugin" lets you command the
  workbench from your **regular WeChat** — say something, it works, the result comes back to the
  same thread. Fully official; no reverse-engineered protocols.
- **Connector framework**: PushPlus / ServerChan / WeCom / Webhook / SMTP — push results anywhere.

**It hooks into the stuff you own**

- **25 configurable modules**: Today / Tasks / Files / OpenClaw / Skills / Calendar / Meetings /
  Mail / Projects / Notes / Knowledge base / System / Settings / Life / Room / Pomodoro / Habits /
  Clipboard / Reminders / Log / Tools / System tools / Feature list / **File transfer** /
  **Printers**. Each can be toggled, renamed, and reordered.
- **Ask anything**: multi-model chat over any Ollama-compatible endpoint, with side-by-side model
  comparison and automatic stripping of reasoning traces.
- **Printing**: ordinary printers auto-discovered (Windows spooler + IPP/IPPS direct).
  3D printers: **OctoPrint / Klipper-Moonraker / PrusaLink**, LAN auto-discovery, live progress and
  temperatures, pause/cancel.
- **File index**: instant search across hundreds of thousands of local files, including message
  bodies (works offline on cached mail).

**It actually works on your phone**

- **Device-to-device file transfer**: photos go phone → computer as **raw bytes, never re-encoded**
  (EXIF fully preserved — strictly better than screenshot or clipboard). Quotas and expiry included.
- **Mobile shell**: sidebar becomes a drawer with a bottom tab bar and swipe-to-close on narrow screens.
- **Installable PWA**: add to home screen for a fullscreen, address-bar-free app
  (`manifest` + Service Worker, network-first so changes take effect immediately).
- **Usable terminal on mobile**: a 21-key touch row (44px targets), a quick-command bar, and
  adjustable font size (mobile and desktop sizes are stored separately).
- **LAN reachable**: phone or tablet on the same network, with an optional passphrase or open access.

**Bilingual UI**

- Interface language **follows your system by default**; one click switches it (`Ctrl+L` also works).
- Untranslated strings stay in Chinese rather than going blank; the language files ship with the repo.

## In WeChat (two-way channel)

Regular WeChat has no official message API; reverse-engineering it gets accounts banned. This goes
through the official route: a WeCom self-built app plus **My Company → WeChat plugin**.

**Why WeCom**: WeCom has a "WeChat plugin" that routes messages into your *own* WeChat.
Same phone number, no second account, no business licence.

One-time setup (~5 minutes, in the WeCom admin console):

1. Register WeCom with your phone number, open the admin console;
2. **My Company → Company Info** → copy the **Corp ID**;
3. **App Management → Internal → Create App** → get **AgentId** and **Secret**;
4. **My Company → WeChat plugin** → generate a QR code, scan it with your own WeChat;
5. Uncheck "receive messages only in WeCom", otherwise WeChat won't deliver.

Then in **Settings → WeCom** inside the workbench: paste the details, generate a Token + AESKey,
"Open tunnel" for an `https://xxx.trycloudflare.com/wecom/callback` URL, and paste that plus the
Token/AESKey into the console. Finally, "Connectivity self-check" sends you a real message.

| You say | It does |
| --- | --- |
| `help` | Command list |
| `today` | What's still left today |
| `note buy milk` | Drops into the inbox |
| `todo pay the electric bill` | Goes straight into today |
| `log 12 lunch` / `log income 50 freelance` | Records a transaction |
| `find reimbursement form` | Searches hundreds of thousands of local files |
| Anything else | Handed to the local OpenClaw; the result comes back to the same thread |

Two gotchas worth knowing:

- **The callback URL is temporary** — a quick tunnel gets a new address on restart.
- **Home broadband has a dynamic IP** — when your public IP changes, WeCom reports `60020`. Add the
  IP to the console's "trusted IPs"; the workbench warns you in the log when it detects a change.

## Platform support

| | Windows | macOS / Linux |
| --- | --- | --- |
| Core features (chat, OpenClaw, files, projects, calendar, email…) | ✅ | ✅ |
| Built-in terminal (ConPTY, needs Win10 1809+) | ✅ | ❌ |
| WPS document read/write | ✅ | ❌ |
| **Printer module** (needs the Windows spooler) | ✅ | ❌ |

> The 3D-printer protocols and LAN discovery are cross-platform in `printers.py`; only the
> ordinary-printer channel (Windows spooler) is Windows-only.

## Remote access (self-hosted)

To reach **your own machine** from a phone or the outside world:

1. In `config.json`:
   ```json
   "remote": { "bind": "0.0.0.0", "gate": true, "allow_lan": true, "token": "a long random string" }
   ```
   - `gate: false` — open: same-LAN devices (phone, tablet) connect with **no passphrase**, and the
     terminal endpoints open up too.
   - `gate: true` — locked: anything not from localhost needs the passphrase (`?k=` exchanges a
     cookie), and **terminal endpoints stay localhost-only** regardless.
2. Start: `python server.py 8777` (`bind` comes from config, not a CLI flag)
3. Tunnel (free, no account): `cloudflared tunnel --url http://127.0.0.1:8777`
4. Open the tunnel URL on your phone.

> ⚠️ Security: **don't bind `0.0.0.0` with `gate: false` and leave it there** — that exposes your
> file index and a shell to everyone on the network. Use `gate: true` with a strong `token`.
> Terminal endpoints (`/api/term`, `/api/bridge`) are localhost-only in either mode; on a phone
> with the gate on, you get a plain-language explanation instead of a bare error.

> Also note: deployed as a **pure static site** (no local backend), the features that depend on
> your machine — chat, OpenClaw, files, terminal, system — are unavailable. The UI says so
> explicitly rather than showing a blank page.

## Open loop

This is an open product: everyone runs their own instance, connects their own OpenClaw/Ollama,
does their own tunneling. **Contributions, configs, and deployment notes are welcome** — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Security

`config.json` holds real credentials (mail password, API key) and is excluded by `.gitignore` —
it never enters the repository. Create your own from `config.example.json`. The source itself
contains no personal information.

## License

[MIT](LICENSE)
