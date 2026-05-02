[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/xaynov-osint/txfetch)
[![Python](https://img.shields.io/badge/python-3.9+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-linux%20%7C%20windows%20%7C%20macos-lightgrey)]()

# TXFetch
🔍 Blockchain Transaction Retrieval Tool — find a transaction hash using only indirect data: time, amount, and network.
by xaynov (@ownstates)

---

<img width="1280" height="866" alt="image" src="https://github.com/user-attachments/assets/5b649469-5c24-452f-9445-c945f0774ba4" />


---

## What it does
**TXFetch** is a specialized search engine for blockchain exploration and forensics. It allows you to retrieve TXIDs (transaction identifiers) even when you have incomplete data—such as when both the sender’s and recipient’s addresses are missing—across the TRON, TON, BTC, and EVM networks.

You know approximately when a transfer happened and how much was sent — but you don't have the TX hash. TXFetch queries public blockchain APIs, filters results by time window and amount, and returns a ranked list of candidates with a confidence score.

Supported networks: TRON · TON · EVM • BTC

---

## Installation
**Requirements**: Python 3.10+
```
# 1. Clone the repository
git clone https://github.com/ownstates/txfetch.git
cd txfetch

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create the modules package file
touch modules/__init__.py

# 5. After installing dependencies, register the CLI command
pip install -e .

```

---

## Usage
```/usr/bin/python3 main.py```

The interactive menu will open. Use ↑ ↓ to select a network, Enter to confirm.

Then enter step by step:
| Step |                         Field                         |  Required  |
|:----:|:-----------------------------------------------------:|:----------:|
| 1    | Time in UTC — DD.MM.YYYY HH:MM or DD.MM.YYYY HH:MM:SS | ✅          |
| 2    | Coin (e.g. USDT, BTC, TON)                            | ✅          |
| 3    | Amount                                                | ⬜ optional |
| 4    | Memo / comment                                        | ⬜ optional |

⚠️ **Always enter time in UTC**. If your local time is UTC+3, subtract 3 hours before entering.

### Interactive mode
```bash
txf
```

### Direct search (no TUI)
```bash
txf --network tron --coin USDT --date 07.04.2026 --time 17:38 --amount 800
txf -n ton -c TON -d 14.04.2026 -t 23:39
txf -n btc -c BTC -d 02.05.2026 -t 00:24 --range 5min
```

### All flags
| Flag | Short | Required | Description |
|------|-------|----------|-------------|
| `--network` | `-n` | ✅ | tron / ton / eth / bsc / base / btc |
| `--coin` | `-c` | ✅ | USDT, BTC, TON, etc. |
| `--date` | `-d` | ✅ | DD.MM.YYYY or YYYY-MM-DD (UTC) |
| `--time` | `-t` | ✅ | HH:MM or HH:MM:SS (UTC) |
| `--amount` | `-a` | ⬜ | expected amount |
| `--memo` | `-m` | ⬜ | comment / memo |
| `--range` | `-r` | ⬜ | second / minute / 1min / 5min / 15min |
| `--tolerance` | | ⬜ | amount tolerance, default 0.01 (±1%) |

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
  #    TXID                                Conf      Amount    Time
  ────────────────────────────────────────────────────────────────────
  1    6d2902a3ad3da3afe8aaae…871c2f33    100%      800.00    17:38:00
  2    7ac519740338db9348f92b…c4edc        74%      797.80    17:38:15
```

---

## Project structure
```
txfetch/
├── main.py              # entry point — TUI, input, output
├── requirements.txt     # dependencies
└── modules/
    ├── __init__.py
    ├── models.py        # TXQuery, TXCandidate, score_candidate
    ├── tron.py          # TRON / USDT-TRC20
    ├── ton.py           # TON / Jetton
    ├── eth.py           # Ethereum / EVM
    └── btc.py           # Bitcoin
```

---
## Dependencies
|     Package    | Version |               Purpose              |
|:--------------:|:-------:|:----------------------------------:|
| requests       | ≥ 2.31  | HTTP requests to blockchain APIs   |
| prompt_toolkit | ≥ 3.0   | Interactive terminal UI            |
| openpyxl       | ≥ 3.1   | Excel export for large result sets |

---

## Notes
- Results with 100% confidence mean exact time and amount match
- If more than 100 candidates are found, the tool will ask for a limit or offer Excel export
- API keys are optional but recommended for TRON (TronGrid) and ETH (Etherscan) to avoid rate limiting
- Bitcoin adapter searches confirmed blocks only — unconfirmed mempool transactions are not supported
