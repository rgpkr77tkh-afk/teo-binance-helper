# teo-binance-helper

Free GitHub Actions helper for Natalia's Teo paper-trading workflow.

## What it does
- uses public Binance USD-M Futures market data only;
- uses no Binance API key;
- never places real orders;
- scans liquid USDT perpetual altcoins;
- shortlists 5 candidates;
- checks CLOSED H1 / M15 / M5 structure;
- applies pullback/confirmation, Remaining Fuel, RR and anti-chase;
- saves the newest result to `reports/latest.md` and `reports/latest.json`.

## Schedule
The helper runs at minute **15, 30 and 45** of each hour.  
Natalia's main Teo remains separate.

## Safety
This repository is **PAPER / SIGNAL ONLY**. It is not connected to a real Binance trading account.
