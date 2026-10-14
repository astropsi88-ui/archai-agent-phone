# ARCH_AI Agent Phone

> **EXPERIMENTAL DEVELOPMENT KIT — NOT A FINISHED PRODUCT.**
> End-to-end acceptance of the real application, including agent work dispatch and results, is incomplete. The code is currently for developer evaluation and further development. Published source and passing local tests do not establish production readiness.

Connect a phone PWA to your existing agent, sharing its server-side conversation and memory.

This is an open developer kit accompanying ARCH_AI's practical demonstration of talking to an agent through a separate phone app. It is an additional web entrypoint; network availability depends on your domain, hosting and providers.

## Features

- Phone browser interface and installable PWA.
- Existing agent integration through an HTTP or callable adapter.
- Text and optional speech-to-text → existing agent → text-to-speech.
- Server-pinned owner, agent and conversation bindings.
- Cancellation, ambiguous request recovery, expiry and backup examples.

## Requirements

Python 3.10+, an existing agent entrypoint with canonical history and durable request deduplication, and your own domain/HTTPS for phone use. Server access and provider accounts are not included. Speech APIs are disabled by default.

## Local checks

```sh
python3 -m unittest discover -s tests -p test_connector.py -v
```

Tests use a synthetic existing runtime and mock speech. No paid API calls. The supplied guides are currently in Russian: [start here](00_START_HERE.md). The real backend adapter, provider speech, iPhone/Android actions and production deployment require acceptance in your environment; see [CHECKS.md](CHECKS.md).

## ARCH_AI

[Website](https://iarch.ai/) · [Telegram](https://t.me/IARCH_AI) · [YouTube](https://www.youtube.com/@iarch_ai)

Issues and contributions are welcome. Please include reproducible steps and avoid posting credentials or personal conversations.

MIT License · © 2026 ARCH_AI · [License](LICENSE)

## Update 2026-10-14

File-only, text+file and completed voice+file input, bounded 1 MiB chunk transport, quiet receipt details, persistent sound/voice toggles and versioned PWA assets are available with the existing runtime attachment contract. The reviewed PDF-reading routing reference is included for your composer. [Update and tested limits](UPDATES_2026-10-14.md). This remains EXPERIMENTAL; the public kit is not a copy of a private owner agent.
