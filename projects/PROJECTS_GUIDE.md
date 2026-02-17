# Stock Market Automation Projects

5 automation projects built on the same architecture as the original Quantsapp Unusual Activity tracker. Each project follows the same pipeline: **Scrape -> Store -> Analyze -> Visualize -> Notify**.

**Priority Project 1: Option Triggers Module** – See below for full details.

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

## Project 5: Option Triggers Module (PRIORITY 1)

**Directory:** `projects/option_triggers/`

**What it does:**
- Scrapes Quantsapp **Option Triggers** page every 40 minutes
- Applies a **4-Rule Filter** to identify stock picks:
  - **Rule 1:** Highest CE OI Changes (configurable threshold)
  - **Rule 2:** Call-Put diff between -1% to +1% (balanced activity)
  - **Rule 3:** Stock must exist in WBRam Google Sheet watchlist
  - **Rule 4:** Column O (LTP) must be TRUE, then check price columns (P, Q, R)
- For each qualifying stock, navigates to **ALL 7 Quantsapp tools** and collects detailed data
- Generates **40+ column Excel** with per-tool analysis
- Creates **per-stock PDF visual reports** with IVP gauge, signal dashboard, verdict
- Sends Telegram: `"Stock Pick from WBRam Excel is <STOCK NAME>"` + full analysis

**Data Sources:** ALL Quantsapp tools via Selenium navigation:
| Tool | URL | Data Collected |
|------|-----|----------------|
| Option Triggers | `option-triggers` | CE/PE OI, OI Change %, Volume, Trigger Type |
| IV Analysis | `iv-analysis` | IV, IVP, IV Rank, HV, IV vs HV |
| OI Analysis | `oi-analysis` | Total CE/PE OI, Max OI strikes, PCR |
| PCR Analysis | `pcr` | PCR by OI, PCR by Volume, Trend |
| Buildup | `buildup` | Long/Short Buildup, Unwinding, Covering |
| Futures OI | `futures-oi` | Futures OI, OI Change, Basis |
| Max Pain | `max-pain` | Max Pain strike, Distance from CMP |

**Output Sheets:**
| Sheet | Content |
|-------|---------|
| `Triggers_Raw` | All scraped Option Triggers data (cumulative log) |
| `Stock_Picks` | Current cycle picks with 40+ columns from all tools |
| `Pick_History` | Historical log of all picks across cycles |
| `Daily_Summary` | Per-day pick count, symbols, dominant signal |

**Excel Column Groups (40+ columns):**
| Prefix | Tool | Columns |
|--------|------|---------|
| `OT_` | Option Triggers | CE OI, CE OI Change, CE OI Change %, PE OI, PE OI Change, PE OI Change %, CE Volume, PE Volume, Trigger Type, LTP, Change %, Call-Put Diff % |
| `IV/IVP/HV` | IV Analysis | IV, IVP, IV Rank, IVP Status (Very Low→Very High), HV, IV vs HV (Overpriced/Underpriced/Fair), IV Signal |
| `OI_` | OI Analysis | Total CE OI, Total PE OI, CE OI Change, PE OI Change, Max CE Strike (Resistance), Max PE Strike (Support), PCR from OI, OI Trend |
| `PCR_` | PCR Analysis | PCR (OI), PCR (Volume), PCR Trend, PCR Signal |
| `BU_` | Buildup | Buildup Type, Price Change %, OI Change %, Buildup Signal |
| `FUT_` | Futures OI | Futures OI, OI Change, OI Change %, Price, Basis, Signal |
| `MP_` | Max Pain | Max Pain Strike, Current Price, Distance, Distance %, Signal |
| `GS_` | Google Sheet | LTP Status, Price columns from WBRam sheet |
| - | Overall | **Overall Verdict** (Bullish/Bearish/Mixed with signal count) |

**IVP Classification:**
| IVP Range | Status | Signal |
|-----------|--------|--------|
| 0-20% | Very Low | Options Cheap - Good for Buying |
| 20-40% | Low | Below Avg - Favorable Buy |
| 40-60% | Medium | Neutral |
| 60-80% | High | Expensive - Consider Selling |
| 80-100% | Very High | Very Expensive - Sell Strategies |

**Google Sheet Setup:**
1. Create a Google Cloud Service Account (or publish sheet as CSV)
2. Place service account JSON in `credentials/google_service_account.json`
3. Set `GOOGLE_SHEET_ID` in `.env` or `config.json`
4. Sheet structure: Column A = Stock symbols, Column O = LTP TRUE/FALSE, Columns P/Q/R = Price data

**Telegram Alerts:**
- Per-stock announcement: `"Stock Pick from WBRam Excel is <NAME>"` with full tool analysis
- Per-tool breakdown: IVP status, OI trend, PCR signal, Buildup type, Futures signal, Max Pain
- Overall verdict with bullish/bearish signal count
- Excel file attachment per cycle
- Daily summary report at 15:30 (post market close)
- PDF visual report per stock (IVP gauge, signal dashboard, key metrics table, verdict card)

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
