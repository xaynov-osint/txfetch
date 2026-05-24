[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/xaynov-osint/txfetch)
[![Python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-linux%20%7C%20windows%20%7C%20macos-lightgrey)]()

# TXFetch
🔍 Blockchain Transaction Retrieval Tool — find a transaction hash using only indirect data: time, amount, and network.
by xaynov (@ownstates)

---

<img width="1920" height="1300" alt="TXFetch" src="https://github.com/user-attachments/assets/7280b770-1dcd-4c1d-bff7-c1304cabd6ef" />

---

## What it does

**TXFetch** is a specialized search engine for blockchain exploration and forensics. It allows you to retrieve TXIDs even when you have incomplete data — such as when both sender and recipient addresses are unknown — across 10 supported networks.

You know approximately when a transfer happened and how much was sent — but you don't have the TX hash. TXFetch queries public blockchain APIs, filters results by time window and amount, scores each candidate and returns a ranked list.

**Supported networks:**

| Network | Coins | API |
|---------|-------|-----|
| TRON | USDT, USDC | TronGrid |
| TON | TON, USDT, NOT | TONAPI / TONCenter |
| ETH | USDT, USDC, ETH | Etherscan |
| BSC | USDT, USDC, BNB | BscScan |
| Base | USDC, ETH | Basescan |
| Solana | SOL, USDC, USDT, RAY, JUP | Public RPC / Helius |
| Bitcoin | BTC | mempool.space |
| Litecoin | LTC | litecoinspace.org |
| Dogecoin | DOGE | dogechain |
| Bitcoin Cash | BCH | blockchair |

---

## Installation

**Requirements:** Python 3.10+

```bash
# 1. clone the repository
git clone https://github.com/ownstates/txfetch.git
cd txfetch

# 2. create and activate virtual environment
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows

# 3. install dependencies
pip install -r requirements.txt

# 4. register CLI commands (optional)
pip install -e .

# 5. copy env template
cp .env.example .env
```

---

## API keys (optional)

All adapters work without API keys using public access. Keys remove rate limits and improve speed.

Edit `.env` to add your keys:

```env
TRONGRID_API_KEY=
ETHERSCAN_API_KEY=
BSCSCAN_API_KEY=
TONAPI_KEY=
HELIUS_API_KEY=
```

Free keys: [trongrid.io](https://trongrid.io) · [etherscan.io](https://etherscan.io/apis) · [bscscan.com](https://bscscan.com/apis) · [tonconsole.com](https://tonconsole.com) · [helius.dev](https://helius.dev)

---

## Usage

### Interactive mode (TUI)

```bash
python3 main.py
# or if installed via pip install -e .
txf
txfetch
```

Use **↑ ↓** to select a network, **Enter** to confirm. Then enter step by step:

| Step | Field | Required | Format |
|------|-------|----------|--------|
| 1 | Date (UTC) | ✅ | `07.04.2026` or range `07.04.2026-09.04.2026` |
| 2 | Time (UTC) | ✅ if single date | `17:38` or `17:38:45` |
| 3 | Time range | ✅ if single date | menu: exact / ±1min / ±5min / ±15min / custom |
| 4 | Coin | ✅ | USDT, BTC, SOL, etc. |
| 5 | Amount | ⬜ | `800` or range `500-800` |
| 6 | Memo | ⬜ | any text |

> ⚠️ **Always enter time in UTC.** If your local time is UTC+3, subtract 3 hours.

### Direct search (no TUI)

```bash
txf --network tron --coin USDT --date 07.04.2026 --time 17:38 --amount 800
txf -n ton  -c TON  -d 14.04.2026 -t 23:39
txf -n btc  -c BTC  -d 02.05.2026 -t 00:24 -a 0.5 --range 5min
txf -n sol  -c USDC -d 01.05.2026 -t 12:00 -a 100-500
```

### All flags

| Flag | Short | Required | Description |
|------|-------|----------|-------------|
| `--network` | `-n` | ✅ | tron / ton / eth / bsc / base / sol / btc / ltc / doge / bch |
| `--coin` | `-c` | ✅ | USDT, BTC, SOL, etc. |
| `--date` | `-d` | ✅ | DD.MM.YYYY or range DD.MM.YYYY-DD.MM.YYYY |
| `--time` | `-t` | ✅ | HH:MM or HH:MM:SS (UTC) |
| `--amount` | `-a` | ⬜ | exact `800` or range `500-800` |
| `--memo` | `-m` | ⬜ | comment / memo |
| `--range` | `-r` | ⬜ | second / minute / 1min / 5min / 15min |
| `--tolerance` | | ⬜ | amount tolerance, default `0.01` (±1%) |

---

## Example

```
Network:  TRON
Coin:     USDT
Time:     07.04.2026 17:38      ← UTC
Amount:   800
```

Output:
```
  #    TXID (short)              Conf        Amount    Time
  ────────────────────────────────────────────────────────────────────
  1    6d2902a3ad3da3afe8aaae…  100%        800.00    17:38:00
  2    7ac519740338db9348f92b…   74%        797.80    17:38:15
  ────────────────────────────────────────────────────────────────────

  Enter # to get full TXID  (or Enter to skip) › 1

  Full TXID #1:
  6d2902a3ad3da3afe8aaae870dc1b3af54d12c504eb184a8bdebd8eb871c2f33
```

---

## How scoring works

Each candidate receives a confidence score from 0 to 1:

| Criterion | Weight | Logic |
|-----------|--------|-------|
| Time | 0.5 | linear from time_from. TX at exact time → 1.0 |
| Amount | 0.4 | exact match → 1.0, within tolerance → linear, outside → rejected |
| Memo | 0.1 | case-insensitive substring match → 1.0 |

If memo is not specified — its weight is redistributed to time and amount. If a specified amount is outside tolerance — the candidate is immediately discarded regardless of time score.

**Memo fallback:** if no results found with memo — automatically retries without it.

---

## Project structure

```
txfetch/
├── main.py              # entry point — TUI, argparse, search pipeline
├── pyproject.toml       # package config and CLI entry points
├── requirements.txt     # dependencies
├── .env.example         # api keys and runtime constants template
└── modules/
    ├── __init__.py
    ├── models.py        # TXQuery, TXCandidate, score_candidate, amount_matches
    ├── config.py        # api keys and constants from .env
    ├── matcher.py       # universal filter and scorer
    ├── tron.py          # TRON / USDT-TRC20
    ├── ton.py           # TON / Jetton
    ├── evm_base.py      # base class for EVM networks
    ├── eth.py           # Ethereum
    ├── bsc.py           # BNB Smart Chain
    ├── base_chain.py    # Base (Coinbase L2)
    ├── sol.py           # Solana / SPL tokens
    ├── utxo_base.py     # base class for UTXO networks
    ├── btc.py           # Bitcoin
    ├── ltc.py           # Litecoin
    ├── doge.py          # Dogecoin
    └── bch.py           # Bitcoin Cash
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| requests | ≥ 2.31 | HTTP requests to blockchain APIs |
| prompt_toolkit | ≥ 3.0 | interactive terminal UI |
| openpyxl | ≥ 3.1 | Excel export for large result sets |

---

## Notes

- All times must be in **UTC** — convert local time before entering
- Bitcoin amount is the sum of all outputs — may include change, use wider tolerance
- Dogecoin API structure may differ from mempool-compatible APIs — results may vary
- Solana without Helius key uses public RPC which has strict rate limits
- Results with >100 candidates trigger Excel export prompt
