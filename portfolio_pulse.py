#!/usr/bin/env python3
"""
Portfolio Pulse — Real-time terminal portfolio tracker

Install dependencies:
    pip install yfinance rich plotext

Usage:
    python portfolio_pulse.py                # default 30-second refresh
    python portfolio_pulse.py --refresh 60   # custom interval
"""

# ── HOLDINGS ──────────────────────────────────────────────────────────────────
# Edit this dict to match your actual positions: {ticker: number_of_shares}
HOLDINGS: dict[str, float] = {
    "AAPL":  10,
    "MSFT":   5,
    "NVDA":   8,
    "BRK-B":  3,
    "GOOGL":  4,
}
# ─────────────────────────────────────────────────────────────────────────────

import argparse
import sys
import time
from datetime import datetime
from typing import Optional

try:
    import pandas as pd
    import yfinance as yf
    import plotext as plt
    from rich.live import Live
    from rich.layout import Layout
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.console import Console
    from rich import box
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with:  pip install yfinance rich plotext")
    sys.exit(1)

console = Console()

# ── Price cache ───────────────────────────────────────────────────────────────
_cache: dict[str, dict] = {}   # ticker → {price, prev_close, day_change_pct}
_last_fetch: Optional[float] = None
_fetch_failed = False
# ─────────────────────────────────────────────────────────────────────────────


def fetch_prices() -> bool:
    """Batch-fetch latest prices via yfinance. Returns True on success."""
    global _cache, _last_fetch, _fetch_failed
    tickers = list(HOLDINGS.keys())
    try:
        raw = yf.download(
            tickers,
            period="2d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )

        if raw.empty:
            _fetch_failed = True
            return False

        # Normalize: single-ticker download returns a Series for "Close"
        close = raw["Close"]
        if isinstance(close, pd.Series):
            close = close.to_frame(name=tickers[0])

        updated_any = False
        for ticker in tickers:
            if ticker not in close.columns:
                continue
            col = close[ticker].dropna()
            if col.empty:
                continue
            price = float(col.iloc[-1])
            prev  = float(col.iloc[-2]) if len(col) >= 2 else price
            pct   = (price - prev) / prev * 100 if prev else 0.0
            _cache[ticker] = {
                "price":         price,
                "prev_close":    prev,
                "day_change_pct": pct,
            }
            updated_any = True

        if not updated_any:
            _fetch_failed = True
            return False

        _last_fetch   = time.time()
        _fetch_failed = False
        return True

    except Exception:
        _fetch_failed = True
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _total_mv() -> float:
    return sum(
        _cache[t]["price"] * HOLDINGS[t]
        for t in HOLDINGS if t in _cache
    )


# ── UI builders ───────────────────────────────────────────────────────────────

def build_header_panel(seconds_left: int) -> Panel:
    mv       = _total_mv() or 1.0
    pnl      = sum(
        (_cache[t]["price"] - _cache[t]["prev_close"]) * HOLDINGS[t]
        for t in HOLDINGS if t in _cache
    )
    prev_tot = mv - pnl
    pct      = (pnl / prev_tot * 100) if prev_tot else 0.0

    pnl_style = "bold green" if pnl >= 0 else "bold red"
    sign      = "+" if pnl >= 0 else ""
    ts        = (
        datetime.fromtimestamp(_last_fetch).strftime("%H:%M:%S")
        if _last_fetch else "—"
    )

    left = Text(no_wrap=True)
    left.append("Total  ", style="bold")
    left.append(f"${mv:>12,.2f}", style="bold cyan")
    left.append("    Day P&L  ", style="bold")
    left.append(f"{sign}${pnl:,.2f}  ({sign}{pct:.2f}%)", style=pnl_style)
    left.append(f"    Updated {ts}", style="dim")
    if _fetch_failed:
        left.append("   ⚠ Price fetch failed, showing cached data", style="bold yellow")

    right = Text(justify="right", no_wrap=True)
    right.append(f"Next refresh in {seconds_left:>3}s", style="dim")

    grid = Table.grid(expand=True, padding=0)
    grid.add_column(ratio=4)
    grid.add_column(justify="right", ratio=1)
    grid.add_row(left, right)

    return Panel(
        grid,
        title="[bold blue]◈ Portfolio Pulse[/bold blue]",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def build_table_panel() -> Panel:
    mv_total = _total_mv() or 1.0

    tbl = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold white",
        expand=True,
        show_edge=False,
    )
    tbl.add_column("Ticker",        style="bold cyan",  min_width=8)
    tbl.add_column("Shares",        justify="right",    min_width=8)
    tbl.add_column("Price",         justify="right",    min_width=12)
    tbl.add_column("Market Value",  justify="right",    min_width=14)
    tbl.add_column("% Portfolio",   justify="right",    min_width=12)
    tbl.add_column("Day Change%",   justify="right",    min_width=12)

    for ticker, shares in HOLDINGS.items():
        if ticker not in _cache:
            tbl.add_row(ticker, f"{shares:g}", "—", "—", "—", "—")
            continue

        d        = _cache[ticker]
        price    = d["price"]
        mv       = price * shares
        pct_port = mv / mv_total * 100
        day_pct  = d["day_change_pct"]

        day_style = "bold green" if day_pct >= 0 else "bold red"
        day_sign  = "+" if day_pct >= 0 else ""

        tbl.add_row(
            ticker,
            f"{shares:g}",
            f"${price:>10,.2f}",
            f"${mv:>12,.2f}",
            f"{pct_port:>6.1f}%",
            Text(f"{day_sign}{day_pct:.2f}%", style=day_style),
        )

    return Panel(
        tbl,
        title="[bold]Holdings[/bold]",
        box=box.ROUNDED,
        padding=(0, 1),
    )


def build_chart_panel(width: int, height: int) -> Panel:
    entries = [
        (t, HOLDINGS[t] * _cache[t]["price"])
        for t in HOLDINGS if t in _cache
    ]
    if not entries:
        return Panel(
            "Waiting for price data…",
            title="[bold]Portfolio Allocation[/bold]",
            box=box.ROUNDED,
        )

    labels = [t for t, _ in entries]
    values = [v for _, v in entries]

    try:
        plt.clear_figure()
        plt.plot_size(max(20, width - 4), max(8, height - 2))
        plt.pie(values, labels=labels)
        plt.title("Portfolio Allocation")
        chart_str = plt.build()
        content: object = Text.from_ansi(chart_str)
    except Exception as exc:
        content = Text(f"Chart unavailable: {exc}", style="dim")

    return Panel(
        content,
        title="[bold]Portfolio Allocation[/bold]",
        box=box.ROUNDED,
        padding=0,
    )


def build_root(seconds_left: int) -> Layout:
    h = console.height
    w = console.width

    chart_h = max(14, h // 3)

    root = Layout()
    root.split_column(
        Layout(name="header", size=3),
        Layout(name="table"),
        Layout(name="chart", size=chart_h),
    )

    root["header"].update(build_header_panel(seconds_left))
    root["table"].update(build_table_panel())
    root["chart"].update(build_chart_panel(w, chart_h))

    return root


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Portfolio Pulse — real-time terminal portfolio tracker"
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Refresh interval in seconds (default: 30, minimum: 5)",
    )
    args     = parser.parse_args()
    interval = max(5, args.refresh)

    console.print("[bold blue]Portfolio Pulse[/bold blue] — fetching initial prices…")
    fetch_prices()
    next_refresh = time.time() + interval

    with Live(console=console, screen=True, refresh_per_second=2) as live:
        while True:
            now          = time.time()
            seconds_left = max(0, int(next_refresh - now))
            live.update(build_root(seconds_left))

            if now >= next_refresh:
                fetch_prices()
                next_refresh = time.time() + interval

            time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye.[/dim]")
