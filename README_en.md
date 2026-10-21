# OpenLookout

**An assistive partner.** It watches the screen you are on right now and speaks up when you are stuck. Otherwise it stays quiet. You stay in charge: it may look and it may talk, and it asks before it changes the machine. Temp files, caches, and the recycle bin are the exception — those go into a quarantine it can restore, and it tells you afterwards.

It is not a whole-machine steward and it does not explore freely. Full-disk history, system maintenance, and writing reports for you are out of scope for a first run. This repository does not contain a screenshot.

Chinese: [README.md](README.md).

## Install (Windows)

Python 3.11 or newer, and a desktop that can take a screenshot. From the repository root:

```bat
install.bat
```

or:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The script checks the Python version, installs `pillow`, `psutil`, `jsonschema`, `certifi`, and `requirements-proactive.txt`, then tries optional `pystray`. A failed `pystray` install does not stop the script. It then runs the first-run wizard. If the wizard does not finish the config, it does not start the sprite.

The wizard asks for protocol, base URL, model name, and API key. It writes:

- `src/openlookout/sprite/proactive/provider.json` (no key)
- `SPRITE_API_KEY` in the repository-root `.env`

Without a terminal it prints one sentence and exits 2. It does not start Claude Code.

The same steps by hand, from the repository root:

```powershell
cd src\openlookout
python -m pip install pillow psutil jsonschema certifi -r requirements-proactive.txt
python -m sprite.proactive.first_run
python -m sprite.proactive.live
```

The sprite sits at the bottom-right of the desktop. Click it to talk.

## Models

The default is direct HTTP to `provider.json`. You do not set `OPENLOOKOUT_BACKEND=direct`, and you do not need Docker or Claude Code.

The loader reads `protocol`, `base_url`, and `model`. Any other key is ignored. The `examples` array in `provider.example.json` is documentation only; the loader does not pick an entry from it.

| Protocol | Request | Examples |
|---|---|---|
| `anthropic` | `{base}/v1/messages` | Any Anthropic Messages-compatible URL. A base that already ends in `/v1` is not doubled. |
| `openai` | `{base}/v1/chat/completions` | OpenAI `https://api.openai.com/v1`, DeepSeek `https://api.deepseek.com/v1` (use that provider's public model id, for example `deepseek-chat`), local Ollama `http://localhost:11434/v1` |

Ollama often ignores the Authorization header. `SPRITE_API_KEY` must still be non-empty. `ollama` is a fine placeholder. A missing key shows the first-run sentence, not a separate empty-key error.

Whether a local model accepts images or tools depends on that model. The client waits for one JSON body and does not send `stream`. A server that only speaks server-sent events will fail. Live Ollama, OpenAI, and DeepSeek were not called here; both protocols are covered by mocked HTTP tests.

Claude Code is opt-in: `OPENLOOKOUT_BACKEND=claude` (`host` is an alias). If Claude fails to start, the process raises and does not fall back to direct HTTP. A missing provider file does not fall back to Claude.

## Pause, quit, undo

Right-click or middle-click the sprite: Pause, Undo, Quit. While paused, the brain and the rules process skip the turn. Quit writes a `QUIT` file. The supervisor stops and does not start children again.

A system-tray menu is created only when `pystray` imports. If it does not, the window still opens and the right-click menu still works. The tray was not verified on a Windows desktop.

## Rules

The supervisor starts a rules process next to the brain, the window, and the operation recorder. It runs the tested resource scenario (memory pressure, suspend, quarantine of restorable cache) and does not call a model. Actions the engine already treats as safe and reversible run, then a bubble reports them with undo. High-risk or irreversible actions are skipped. Offers that wait for "OK" still come from the model path.

When free memory is under 10%, a background browser that has been idle for about 30 seconds, is not the foreground, has no window, and is not playing audio is suspended. The bubble includes undo. A mere warning still uses the long-idle renderer rule. Foreground, audio, and protected processes stay untouched. The Linux probe does not mark the foreground window, so that guard applies when the Windows probe can see it.

## Cost

An unchanged idle screen does not call the model. A heartbeat, or the mere presence of history files, is not a trigger. Feedback, a maintenance signal, a continuation, a goal, or a pending reply still opens a turn. An outbound image whose long edge is over 768 pixels is downscaled to JPEG first. Later requests in the same turn omit the full screenshot when the screen did not change. Crops returned by tools stay. A turn makes at most 4 HTTP calls by default (`OPENLOOKOUT_MAX_CALLS`, clamped to 1..8).

## Config

| Name | Meaning |
|---|---|
| `OPENLOOKOUT_BACKEND` | Empty or `direct`: HTTP. `claude` / `host`: local Claude Code. `mimo` is no longer an alias; unknown values, including that one, stay on direct. |
| `OPENLOOKOUT_MODEL` | Overrides `model` in `provider.json`. Blank uses the file. |
| `OPENLOOKOUT_LANG` | `zh` or `en`. Blank follows the Windows display language: Chinese for `zh*`, English otherwise. |
| `OPENLOOKOUT_MAX_CALLS` | HTTP calls per turn. Default 4, clamped to 1..8. |
| `SPRITE_API_KEY` | Required and non-empty. `ollama` is a valid placeholder for local Ollama. |
| `provider.json` | `protocol`, `base_url`, `model`. Other keys are ignored. |

User-facing strings are translated when they are shown. Supervisor logs stay in Chinese.

## Privacy

Screenshots and the text sent with them go only to the endpoint in `provider.json`. `sprite_home`, `.env`, and `provider.json` stay on this machine and are gitignored. This repository does not contain a screenshot.

## Uninstall

Quit from the menu, or stop `python -m sprite.proactive.live`. Then delete the runtime data, `.env`, and `provider.json`:

- the `SPRITE_HOME` directory, if you set it
- otherwise `%LOCALAPPDATA%\OpenLookout\sprite_home` on Windows
- otherwise `~/.openlookout/sprite_home`
- the repository-root `.env`
- `src/openlookout/sprite/proactive/provider.json`

## What else is in the repo

`src/openlookout/lookout/` and the root `record_win.py` are earlier research prototypes. Start with the sprite above. Contributors: [AGENTS.md](AGENTS.md).

Changes go through a branch and a pull request. Do not push `main` directly. `third_party/` is not in this repository and is not a runtime dependency. See [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

License: MIT for this tree. The bundled VISTA code carries its own MIT notice at `src/openlookout/vista/LICENSE.txt`.
