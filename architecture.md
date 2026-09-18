# ROBI Trading Bot

## Architecture

Market Data
→ SCOUT
→ RISK
→ EXEC
→ Trade Log / P&L
→ Dashboard

## Safety

This project is paper trading only.
No real trades.
No private keys.
No seed phrases.

## Components

- SCOUT: generates simulated trading signals.
- RISK: checks simulated risk conditions.
- EXEC: executes paper trades only.
- Dashboard: displays balance, P&L and activity.
