# Prediction Market Arbitrage

Detects same-venue and cross-venue mispricing on binary prediction markets
(Polymarket and Kalshi), prices it net of venue fees and depth-walked
slippage, sizes it with risk-adjusted Kelly, and streams the result to a live
dashboard.

The build spec this implements is in
[`01_Prediction_Market_Arbitrage_README.md`](01_Prediction_Market_Arbitrage_README.md).

## Quick start

No credentials and no services are needed: the default feed is a synthetic
simulator and the default database is a local SQLite file.

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload
```

The API must be started from the repository root, because the backend imports
the top-level `engine` package.

```bash
cd frontend
npm install
npm run dev
```

Dashboard on <http://localhost:3000>, OpenAPI docs on
<http://localhost:8000/docs>.

### Docker

```bash
docker compose up --build
```

Brings up Postgres, Redis, the API and the dashboard on the same ports.

## Configuration

Every setting has a working default. Copy `.env.example` to `.env` only to
override one. See that file for the full annotated list; the settings that
change behaviour most are:

| Variable | Default | Effect |
| --- | --- | --- |
| `FEED_MODE` | `simulator` | `live` connects to real venue websockets |
| `MIN_NET_EDGE` | `0.002` | Minimum net edge per contract, in dollars |
| `LATENCY_MS` | `250` | Round trip assumed between snapshot and fill |
| `KELLY_MULTIPLIER` | `0.25` | Fraction of full Kelly actually bet |
| `LOSS_FRACTION` | `0.5` | Share of stake lost when a hedge breaks |
| `PERSIST` | `true` | Write snapshots and opportunities to the database |

Live mode needs a Kalshi API key pair (`KALSHI_API_KEY_ID` and
`KALSHI_PRIVATE_KEY_PEM`); Kalshi signs every request. Polymarket's market
websocket is public and needs no credentials.

## Layout

```text
engine/     Quant core. No web, database or network dependencies.
backend/    FastAPI transport, feeds, persistence and cross-venue pairing.
frontend/   Next.js dashboard.
```

### Engine

| Module | Responsibility |
| --- | --- |
| `models.py` | Canonical types. Prices are dollars-per-contract in [0, 1] |
| `normalizer.py` | Venue payloads to one book shape. Kalshi publishes bids only, so YES asks are reconstructed as `1 - no_bid` |
| `orderbook.py` | Depth walking. Every price used for sizing eats the ladder, never the touch |
| `arbitrage.py` | Basket detection: assemble legs paying exactly $1.00, check the basket costs less |
| `fees.py` | Venue fee models. Both venues price fees off `p * (1 - p)`, so fees peak at 50c and vanish at the tails |
| `slippage.py` | Depth cost, latency decay and adverse selection, kept apart |
| `kelly.py` | Generalised Kelly. The trade is riskless only if both legs fill and both venues resolve the same fact the same way |
| `execution.py` | Single-shot fill simulation, including one-leg-fills, plus Monte Carlo equity curves |

`backend/app/services/pairing.py` matches events across venues from question
text. It is deliberately conservative: numbers and years are hard constraints,
because matching "Fed cuts in March" against "Fed cuts in June" shows a fake
30c edge and loses the whole stake.

## API

| Endpoint | Returns |
| --- | --- |
| `GET /health` | Status, feed mode, live market and opportunity counts |
| `GET /api/markets` | Normalized markets across both venues |
| `GET /api/markets/{venue}/{market_id}/book` | Full ladder for one market |
| `GET /api/divergence` | Cross-venue price divergence history |
| `GET /api/events/{event_key}/history` | Price history for one paired event |
| `GET /api/feeds` | Per-feed connection status |
| `GET /api/opportunities` | Live priced and sized opportunities |
| `GET /api/opportunities/summary` | Aggregate edge and engine statistics |
| `GET /api/opportunities/history` | Persisted opportunities |
| `GET /api/opportunities/{opportunity_id}` | One live opportunity in full |
| `POST /api/simulate/execute` | Fill simulation against the live book |
| `POST /api/simulate/kelly` | Kelly sizing for a hypothetical edge |
| `POST /api/simulate/montecarlo` | Equity curve over repeated bets |
| `GET /api/config` | Effective runtime settings |
| `WS /ws/stream` | Books, opportunities and stats pushed on each scan |

## Math

A basket of binary legs that pays exactly $1.00 on every resolution is an
arbitrage when it costs less than $1.00 to assemble.

- Same-venue long: `ask_yes + ask_no < 1`, so edge is `1 - (ask_yes + ask_no)`.
- Same-venue short: shorting YES at bid `p` equals buying NO at `1 - p`, so the
  basket costs `2 - bid_yes - bid_no`.
- Cross-venue: YES on one venue and NO on the other, valid only if both settle
  on the same fact.

Net edge subtracts fees and all three slippage components before sizing. Kelly
then treats the trade as winning the net edge with probability `p` and losing
`LOSS_FRACTION` of the stake otherwise, scaled by `KELLY_MULTIPLIER` and capped
by `MAX_FRACTION_PER_TRADE`.

## Tests

```bash
python -m pytest          # 81 tests
python -m ruff check .
cd frontend && npm run typecheck && npm run build
```

## Disclaimer

Research and simulation tooling. It places no orders, and the fee coefficients
and venue endpoints change without notice. Re-calibrate before trusting a
number.
