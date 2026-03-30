# 安装依赖：pip install yfinance rich
# 运行方式：python portfolio.py

from __future__ import annotations

import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime

import yfinance as yf
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── 硬编码持仓（ticker → 持仓份额）────────────────────────────────
HOLDINGS: dict[str, float] = {
    "AAPL":    10,
    "MSFT":     5,
    "NVDA":     8,
    "VOO":     15,
    "BTC-USD":  0.5,
}

REFRESH_SECONDS = 30
BAR_MAX_WIDTH   = 40   # 条形图最大宽度（字符）


# ── 数据结构 ───────────────────────────────────────────────────────
@dataclass
class Position:
    ticker:       str
    shares:       float
    price:        float    # 当前价格
    prev_close:   float    # 前收盘价
    market_value: float    # 当前市值
    day_change_pct: float  # 日涨跌幅 %


# ── 数据拉取 ───────────────────────────────────────────────────────
def fetch_positions() -> tuple[list[Position], list[str]]:
    """用 yfinance 批量拉取价格，返回持仓列表和错误信息"""
    symbols  = list(HOLDINGS.keys())
    tickers  = yf.Tickers(" ".join(symbols))
    positions: list[Position] = []
    errors:    list[str]      = []

    for ticker, shares in HOLDINGS.items():
        try:
            fi         = tickers.tickers[ticker].fast_info
            price      = float(fi.last_price)
            prev_close = float(fi.previous_close) if fi.previous_close else price
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
            price = prev_close = 0.0

        day_change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
        positions.append(Position(ticker, shares, price, prev_close,
                                  price * shares, day_change_pct))
    return positions, errors


# ── 颜色辅助 ───────────────────────────────────────────────────────
def signed_text(value: float, suffix: str = "") -> Text:
    """正数绿色、负数红色，带正负号"""
    sign  = "+" if value >= 0 else ""
    color = "bold green" if value >= 0 else "bold red"
    return Text(f"{sign}{value:.2f}{suffix}", style=color)


# ── 标题栏 ─────────────────────────────────────────────────────────
def build_header(positions: list[Position], updated_at: str, countdown: int) -> Panel:
    total_value   = sum(p.market_value for p in positions)
    total_prev    = sum(p.prev_close * p.shares for p in positions)
    total_day_pnl = total_value - total_prev
    total_day_pct = (total_day_pnl / total_prev * 100) if total_prev else 0.0

    t = Text()
    t.append("Total Value  ", style="bold white")
    t.append(f"${total_value:,.2f}", style="bold cyan")
    t.append("    Day P&L  ", style="bold white")
    t.append_text(signed_text(total_day_pnl, f"  ({'+' if total_day_pct >= 0 else ''}{total_day_pct:.2f}%)"))
    t.append(f"\n  Updated: {updated_at}   Refresh in {countdown}s   Ctrl+C to quit", style="dim")

    return Panel(t, title="[bold cyan] Portfolio Pulse [/bold cyan]",
                 border_style="bright_blue", padding=(0, 2))


# ── 持仓明细表格 ───────────────────────────────────────────────────
def build_table(positions: list[Position]) -> Panel:
    tbl = Table(
        show_header=True,
        header_style="bold magenta",
        border_style="bright_black",
        expand=True,
        show_lines=False,
        pad_edge=False,
    )
    tbl.add_column("Ticker",       style="bold cyan", min_width=10)
    tbl.add_column("Shares",       justify="right",   min_width=8)
    tbl.add_column("Price",        justify="right",   min_width=12)
    tbl.add_column("Market Value", justify="right",   min_width=14)
    tbl.add_column("Day Change%",  justify="right",   min_width=12)

    for p in positions:
        # 份额：去掉多余的尾零
        shares_str = f"{p.shares:,.4f}".rstrip("0").rstrip(".")
        tbl.add_row(
            p.ticker,
            shares_str,
            f"${p.price:,.2f}",
            f"${p.market_value:,.2f}",
            signed_text(p.day_change_pct, "%"),
        )
    return Panel(tbl, title="[bold]Holdings[/bold]",
                 border_style="bright_black", padding=(0, 1))


# ── ASCII 横向条形图 ───────────────────────────────────────────────
def build_bar_chart(positions: list[Position]) -> Panel:
    """每个 ticker 一行，用 █ 字符按持仓占比填充"""
    total = sum(p.market_value for p in positions) or 1.0
    # 按市值降序排列
    sorted_pos = sorted(positions, key=lambda p: p.market_value, reverse=True)

    lines = Text()
    for p in sorted_pos:
        pct     = p.market_value / total
        bar_len = max(1, round(pct * BAR_MAX_WIDTH))
        bar     = "█" * bar_len
        # 涨绿跌红
        color   = "green" if p.day_change_pct >= 0 else "red"
        label   = f"{p.ticker:<9} {pct * 100:5.1f}%  "
        lines.append(label, style="white")
        lines.append(bar + "\n", style=color)

    return Panel(lines, title="[bold]Allocation[/bold]",
                 border_style="bright_black", padding=(0, 1))


# ── 主循环 ─────────────────────────────────────────────────────────
def main() -> None:
    console = Console()

    def _exit(sig, frame):  # noqa: ANN001
        console.print("\n[dim]已退出。[/dim]")
        sys.exit(0)

    signal.signal(signal.SIGINT, _exit)

    positions:  list[Position] = []
    errors:     list[str]      = []
    updated_at  = "—"
    elapsed     = REFRESH_SECONDS  # 启动时立即刷新

    def render(countdown: int) -> Group:
        err_text = Text(f"⚠ {' | '.join(errors)}", style="yellow") if errors else Text()
        return Group(
            build_header(positions, updated_at, countdown),
            build_table(positions),
            build_bar_chart(positions),
            err_text,
        )

    with Live(console=console, refresh_per_second=2, screen=True) as live:
        while True:
            if elapsed >= REFRESH_SECONDS:
                live.update(render(0))        # 显示「刷新中」
                positions, errors = fetch_positions()
                updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                elapsed = 0

            countdown = max(0, REFRESH_SECONDS - int(elapsed))
            live.update(render(countdown))
            time.sleep(0.5)
            elapsed += 0.5


if __name__ == "__main__":
    main()
