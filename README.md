# slotlane

Prototype: Slotlane: check sponsored ad copy for AI agents and MCP apps

**Use it free, no account:** https://app-slotlane.manykiln.com/  
**Try the demo (made-up data):** https://try-slotlane.manykiln.com/  
**Product page:** https://slotlane.manykiln.com/

> Built and maintained by AI agents at [Manykiln](https://manykiln.com), a studio whose products are written, tested and operated by AI agents. This is a working prototype, not a finished product. No payment is taken anywhere: any checkout, waitlist or payment code in this project runs against fakes only, and the hosted demo uses made-up data.

- Status: prototype; run the 16 automated tests yourself with `python3 -m unittest discover`
- Runs on the Python 3.12 standard library; run the usable app with `python3 app.py` (see below)
- Licence: MIT. Free to use, fork and improve.
- Issues and pull requests are not monitored yet.

---

# Slotwise MVP

Slotwise is a self-serve, one-slot sponsored-tool auction for developer-tool advertisers appearing beside—but never inside—the organic recommendations of coding agents and MCP apps. This user-testing MVP demonstrates published rates, second-price CPC bidding, strict Sponsored separation, deterministic creative review, click validation, a 70% publisher share, and an integer-cent double-entry ledger.

Everything is made up, fake, and held only in process memory. There is no signup, real payment, real payout, persistence, tracking service, or outbound request from the hosted demo. The optional contact-email field has been removed; do not enter personal or payment data.

## Run the hosted demo

Requires Python 3.12 and only its standard library.

```sh
python3 demo.py
```

The UI is available at `http://127.0.0.1:8080`. To choose another port:

```sh
PORT=9000 python3 demo.py
```

Health check: `GET /healthz` returns `200 ok` without creating a session.

For a hosted deployment, terminate TLS at a trusted reverse proxy and set the externally visible origin:

```sh
PUBLIC_BASE_URL=https://slotwise.example TRUST_PROXY_HEADERS=1 python3 demo.py
```

Only enable `TRUST_PROXY_HEADERS` when the application is reachable exclusively through a trusted proxy that replaces `X-Forwarded-For` and `X-Forwarded-Proto`. `PUBLIC_BASE_URL` is also used for click URLs and Host validation.

Sessions expire after one idle hour, are capped in memory, and are creation-rate-limited per client address.

## Test

```sh
python3 -m unittest discover -s tests
```

Tests use no network except a temporary HTTP server on `127.0.0.1`.

## Publisher API

Open the Publisher page to receive the session's publisher key. It is displayed once. The decision endpoint does not require the browser session cookie:

```sh
curl -X POST http://127.0.0.1:8080/api/v1/decide \
  -H 'Content-Type: application/json' \
  -H 'X-Publisher-Key: YOUR_KEY' \
  -d '{"query":"my app keeps crashing"}'
```

## MCP client

The MCP process calls the hosted HTTP API rather than creating separate auction state. Configure it with the public base URL and the key issued on the Publisher page:

```json
{"command":"env","args":["SLOTWISE_BASE_URL=http://127.0.0.1:8080","SLOTWISE_PUBLISHER_KEY=YOUR_KEY","python3","-m","slotwise.mcp_server"]}
```

The stdio server exposes `get_sponsored_recommendations`. Sponsored output is structured separately from organic output and must be displayed as paid placement.

## Published rules

- One sponsored slot, second-price CPC auction.
- Platform and effective minimum floor: $1.00; publisher minimums may raise it.
- Minimum fake top-up: $100.00.
- Fake processing fee: 2.90% plus $0.30, rounded half-up and charged on top. Thus a $100 balance produces a fake $103.20 card charge.
- Publisher receives `price * 70 // 100`; the platform receives the remainder.
- Impressions are free. Signed click tokens expire after 30 minutes. Only one click per impression is billable, with fewer than five billable clicks per minute per publisher and clicker.
- A depleted account is charged `min(price, balance)`; a zero charge creates no publisher credit and does not consume the impression.
- Invalid clicks are counted but redirect locally so the user experience is not broken.
- Categories are fixed, and unclassified queries receive no ad.
- Creative review is a deterministic, demo-level safety filter. It is not a substitute for production moderation or abuse review.

This demo is for demand and trust interviews. It does not prove demand and must not be used with real personal or payment data.

## Usable app

`app.py` is the separate, persistent slotlane sponsored-copy checker. It leaves the auction demo and its existing modules available unchanged.

Run it locally with a dedicated writable data directory:

```sh
DATA_DIR=./slotlane-data python3 app.py
```

Then open `http://127.0.0.1:8080`. For deployment, set the externally visible origin and bind address:

```sh
APP_HOST=0.0.0.0 \
PORT=8080 \
PUBLIC_BASE_URL=https://app-slotlane.manykiln.com \
APP_HTTPS_TERMINATED=true \
DATA_DIR=/persistent/slotlane \
APP_DATA_CAP_MB=200 \
python3 app.py
```

The app accepts individual creatives, CSV with the exact header `title,description,url,category`, and JSON arrays containing those keys. Batch files and request bodies are limited to 1 MB, and batches are limited to 200 rows.

Workspaces use unlogged capability URLs. The raw token is never stored: workspace directories are named with its SHA-256 digest. Data is written atomically, survives restarts, can be exported as JSON or CSV, and can be deleted immediately. Bookmark the workspace URL because there are no accounts and it cannot be recovered.

The checker is deterministic and makes no AI or network calls. It reports stable rule IDs, matched snippets, suggested fixes, character counts, URL hygiene, category keywords, an organic-versus-Sponsored preview, the sponsored-output JSON contract, and version history. A pass is not legal or platform approval.

`GET /healthz` returns `200 ok` without loading or changing a workspace. The service validates Host and same-origin POST requests, sets a same-origin referrer policy and restrictive CSP, logs no request content, caps concurrent connections, expires abandoned and idle workspaces, and applies global rather than IP-based workspace-creation limits.
