---
name: hermes-gateway-setup
description: "Set up Hermes Telegram gateway and verify the bot is live."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [hermes, telegram, gateway, messaging, setup, configuration]
---

# Hermes Messaging Gateway Setup

Use this when the user wants Hermes reachable from a chat app — most often Telegram, but the gateway also drives Discord, WhatsApp, Slack, and Signal. The gateway is Hermes's own long-polling/relay service (`hermes gateway ...`), distinct from the Nous Portal relay.

## When this applies
- "Can you set up Telegram / Discord / WhatsApp for Hermes?"
- User pastes a bot token or an enrollment code.
- Gateway is "not running" (`hermes gateway status` → ✗).

## The Telegram direct-bot path (most common, what usually works)
This path needs NO Nous Portal relay and NO connector URL — just a BotFather token.

1. **Create the bot.** In Telegram, message @BotFather → `/newbot` → name + username (must end in `bot`, e.g. `sifagent_bot`). BotFather returns a token shaped exactly like `<digits>:<long alphanumeric>`, e.g. `8461610142:AAFRWFmgboedkZksgb4rY10LtT6fJoInZBA`. That shape is your signal it's a real bot token.
2. **Get the user's ID** (so only they can talk to the bot). Message @userinfobot → it replies with a numeric ID, e.g. `8056202583`.
3. **Write the secrets to `~/.hermes/.env`** (never config.yaml — secrets belong in .env). The .env already ships a commented template; uncomment and fill:
   ```
   TELEGRAM_BOT_TOKEN=8461610142:AAFRWFmgboedkZksgb4rY10LtT6fJoInZBA
   TELEGRAM_ALLOWED_USERS=8056202583
   ```
   Optional, recommended for cron delivery: `TELEGRAM_HOME_CHANNEL=8056202583`.
   Edit via `sed -i` or a heredoc; the .env is protected from direct *reads* but the terminal can still write it.
4. **Run the gateway:**
   - Try foreground first: `hermes gateway run` (Ctrl+C to stop).
   - Make it permanent: `hermes gateway install` (user service) or `sudo hermes gateway install --system` (boot-time).

## VERIFY IT ACTUALLY WORKS — do not trust the logs
The gateway's Telegram adapter logs `Discovering Telegram API fallback IPs via DNS-over-HTTPS…` then `Connecting to Telegram (attempt 1/8)…` and then goes **silent** — it does NOT print a "Connected" line on success. A live, working gateway looks identical in the log to one still handshaking. **Silence is not failure here.** Confirm externally instead:

```bash
TOKEN=8461610142:AAFRWFmgboedkZksgb4rY10LtT6fJoInZBA
# 1) token valid + bot identity:
curl -s "https://api.telegram.org/bot${TOKEN}/getMe"
#    expect: {"ok":true,"result":{"id":...,"is_bot":true,"username":"SifAgentBot",...}}
# 2) bot can deliver to the user (end-to-end proof):
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id=8056202583 -d text="Hermes connected"
#    expect: {"ok":true,"result":{"message_id":...,"chat":{"id":8056202583,...}}
```

If `getMe` returns HTTP 200 with `is_bot:true`, the token is valid and the network reaches Telegram. If `sendMessage` returns `ok:true` to the user's chat_id, the bot is live — tell the user to open the chat and reply. See `references/telegram-verification.md` for the full recipe and example output.

## Pitfalls
- **Stale systemd instance.** A previously installed gateway keeps running as a service; a new `hermes gateway run` exits with `✗ Another gateway instance is already running (PID X)`. Fix: `hermes gateway stop` then run again, or just `hermes gateway run --replace` to auto-replace. Kill leftovers with `pkill -f "hermes gateway"`.
- **Token-shape confusion (bot token vs relay enrollment token).** A short code like `TYDGLVC2` is NOT a BotFather token — it's a single-use **relay enrollment token** for the Nous Portal relay. The relay path needs `hermes gateway enroll --token <code> --connector-url <wss://.../relay>` AND an active `hermes portal` login (`hermes portal info` → Auth ✓). It writes `GATEWAY_RELAY_*` creds to .env. Prefer the direct bot-token path above unless the user explicitly gives you a relay code + connector URL.
- **Don't wait on "Connected".** See verification above — the log stays at "attempt 1/8" even when connected.
- **Write secrets to .env, not config.yaml.** Hard Hermes invariant; a stray indent in config.yaml can break the live gateway.

## Other platforms
Discord/WhatsApp/Slack/Signal use the same `hermes gateway` machinery with their own env keys (see the commented blocks in `~/.hermes/.env`). The verification principle (probe the platform API directly rather than trusting silent gateway logs) applies to all.
