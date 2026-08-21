# Telegram Gateway Verification Recipe

The gateway Telegram adapter logs `Connecting to Telegram (attempt 1/8)…` and then goes SILENT on success — it never prints "Connected". A live gateway looks identical to a still-handshaking one. **Verify externally, do not trust the logs.**

## 1. Confirm token validity + bot identity (getMe)
```bash
TOKEN=8461610142:AAFRWFmgboedkZksgb4rY10LtT6fJoInZBA
curl -s -w "\nHTTP %{http_code}\n" "https://api.telegram.org/bot${TOKEN}/getMe"
```
Expected (real, observed):
```
HTTP 200
{"ok":true,"result":{"id":8461610142,"is_bot":true,"first_name":"Sifagent_bot","username":"SifAgentBot",...}}
```
HTTP 200 + `is_bot:true` ⇒ token valid, network reaches api.telegram.org.

## 2. End-to-end proof the bot can deliver to the user (sendMessage)
```bash
curl -s -w "\nHTTP %{http_code}\n" -X POST \
  "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id=8056202583 \
  -d text="✅ Hermes conectado. Responde para activar el chat."
```
Expected (real, observed):
```
HTTP
{"ok":true,"result":{"message_id":1206,"from":{"id":8461610142,"is_bot":true,"username":"SifAgentBot"},"chat":{"id":8056202583,"first_name":"Holmart","type":"private"},...}}
```
`ok:true` to the user's chat_id ⇒ bot is live. Tell the user to open the chat and reply.

## 3. Connectivity sanity check (optional)
```bash
timeout 10 bash -c 'cat < /dev/null > /dev/tcp/api.telegram.org/443' && echo TCP OK || echo BLOCKED
```
Observed: TCP OK on a standard AWS host — Telegram is reachable even when the gateway log looks stuck.

## Reading the gateway log correctly
- Silent after `attempt 1/8` with NO error ⇒ probably connected; verify with steps 1–2.
- `✗ Another gateway instance is already running (PID X)` ⇒ stale systemd service. `hermes gateway run --replace` or `hermes gateway stop` first.
- `Broken pipe`/`ReadError` ⇒ transient network/API blip, retry; not a token problem.
