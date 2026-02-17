# Stock Market Automation Projects

4 automation projects built on the same architecture as the original Quantsapp Unusual Activity tracker. Each project follows the same pipeline: **Scrape -> Store -> Analyze -> Visualize -> Notify**.

---

## Quick Start (Same for all projects)

### Prerequisites
```bash
pip install -r requirements.txt
```

### Environment Setup
Create a `.env` file in each project directory:
```
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### Run Any Project
```bash
cd projects/<project_name>
python main.py
```

---

## Project 1: Stock of the Day Screener

**Directory:** `projects/stock_of_the_day/`

**What it does:**
- Scrapes Quantsapp Unusual Option Activity data
- Scores each stock using a weighted composite: OI Change (40%) + Volume Spike (30%) + Price Momentum (30%)
- Ranks stocks and picks the **Stock of the Day**
- Sends ranked leaderboard to Telegram with scores

**Data Source:** `web.quantsapp.com/unusual-option-activity`

**Output Sheets:**
| Sheet | Content |
|-------|---------|
| `Data_Log` | Raw scraped data with timestamps |
| `Daily_Summary` | Per-day avg/max/min change statistics |
| `Stock_Rankings` | Today's top 5 stocks with composite scores |

**Key Analysis:**
- Composite scoring algorithm normalizes OI change, signal count (volume proxy), and price momentum to 0-100 scale
- Aggregates by symbol to find the most active stock
- Configurable weights in `config.json` under `scoring_weights`

**Telegram Alerts:**
- Per-cycle fetch confirmation
- Stock of the Day announcement with score breakdown
- Daily summary at 23:59
- PDF report with ranking bar chart + performance trend

---

## Project 2: Options Chain Analyzer

**Directory:** `projects/options_chain_analyzer/`

**What it does:**
- Scrapes full options chain (Call OI, Put OI, IV, Volume, LTP by strike)
- Computes **Max Pain** strike price
- Calculates **Put-Call Ratio (PCR)** for bullish/bearish sentiment
- Identifies **Support** (highest Put OI) and **Resistance** (highest Call OI) levels

**Data Source:** `web.quantsapp.com/option-chain`

**Output Sheets:**
| Sheet | Content |
|-------|---------|
| `Chain_Log` | Raw options chain snapshots |
| `Analysis` | Computed Max Pain, PCR, Support, Resistance per fetch |
| `Daily_Summary` | Aggregated daily PCR trends |

**Key Analysis:**
- **Max Pain:** Strike where total option writer losses are minimized
- **PCR:** Put OI / Call OI ratio (>1 = bullish put writing, <1 = bearish)
- **Support/Resistance:** Derived from highest OI concentration strikes

**Telegram Alerts:**
- Per-fetch analysis with Max Pain, PCR, sentiment label
- Daily summary at 23:59
- PDF report with OI distribution bar chart + PCR trend line

---

## Project 3: FII/DII Activity Tracker

**Directory:** `projects/fii_dii_tracker/`

**What it does:**
- Scrapes FII (Foreign Institutional Investor) and DII (Domestic Institutional Investor) buy/sell data
- Computes **net flows** (Buy - Sell) for both FII and DII
- Tracks **cumulative flows** over time
- Classifies daily **sentiment** (Strong Bullish, FII Bullish, DII Support, Bearish)

**Data Source:** `web.quantsapp.com/fii-dii-data`

**Output Sheets:**
| Sheet | Content |
|-------|---------|
| `Daily_Flow` | Raw FII/DII buy/sell values |
| `Daily_Summary` | Net flows + sentiment classification |
| `Cumulative_Flow` | Running total of FII/DII flows |

**Key Analysis:**
- **Net Flow:** FII/DII Buy Value - Sell Value per day
- **Cumulative Tracking:** Running sum showing institutional money flow direction
- **Sentiment Classification:**
  - FII+ & DII+ = Strong Bullish
  - FII+ & DII- = FII Bullish
  - FII- & DII+ = DII Support
  - FII- & DII- = Bearish

**Telegram Alerts:**
- Per-fetch data confirmation
- Daily net flow summary with sentiment
- Daily PDF with FII vs DII bar chart + cumulative trend
- Weekly report every Friday with 5-day stacked view

---

## Project 4: Buildup Pattern Detector

**Directory:** `projects/buildup_pattern_detector/`

**What it does:**
- Scrapes unusual activity and **classifies buildup patterns** based on price + OI changes
- Detects **pattern reversals** (e.g., Short Buildup -> Short Covering)
- Generates **sector-wise buildup heatmap**
- Sends real-time alerts for significant reversals

**Data Source:** `web.quantsapp.com/unusual-option-activity`

**Output Sheets:**
| Sheet | Content |
|-------|---------|
| `Pattern_Log` | Raw data + classified buildup pattern |
| `Daily_Summary` | Pattern counts per day |
| `Sector_Buildup` | Sector-wise pattern aggregation |
| `Reversals` | Detected pattern changes per symbol |

**Buildup Classification Rules:**
| Price Change | OI Change | Pattern | Signal |
|-------------|-----------|---------|--------|
| UP | UP | Long Buildup | Bullish |
| DOWN | UP | Short Buildup | Bearish |
| DOWN | DOWN | Long Unwinding | Bearish Exit |
| UP | DOWN | Short Covering | Bullish Exit |

**Key Analysis:**
- Real-time pattern classification for every signal
- Reversal detection by comparing consecutive fetches per symbol
- Sector mapping for 30+ NSE stocks across 8 sectors
- Heatmap visualization showing which sectors have bullish/bearish concentration

**Telegram Alerts:**
- Per-cycle pattern count breakdown
- Reversal alerts when a stock changes buildup type
- Daily sector summary
- PDF with stacked pattern distribution + sector heatmap

---

## Architecture (Common to All Projects)

```
project/
├── main.py              # Entry point: Selenium setup, scraping loop, scheduler
├── config.json          # All configurable parameters
├── helpers/
│   ├── __init__.py
│   ├── excel_utils.py   # Append DataFrame to Excel with header management
│   ├── notify.py        # Telegram bot messaging
│   ├── report_utils.py  # Analysis logic + daily summary + Excel formatting
│   └── report_visuals.py # Matplotlib charts + PDF export + Telegram file send
├── output/              # Excel files (auto-created)
├── reports/             # PDF reports (auto-created)
└── logs/                # Log files (auto-created)
```

### How to Run
1. `cd` into the project directory
2. Ensure `.env` file has Telegram credentials
3. Run `python main.py`
4. Login manually to Quantsapp when prompted (OTP required)
5. Press Enter to start automation
6. The system runs continuously, fetching at configured intervals

### Configuration
Each project's `config.json` controls:
- `fetch_interval_minutes` – How often to scrape
- `headless` – Run Chrome without UI
- `auto_refresh_page` – Refresh before each fetch
- `max_retry_attempts` – Excel write retries
- Project-specific settings (weights, symbols, etc.)
