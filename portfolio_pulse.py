"""
Portfolio Pulse — 终端投资组合看板
一杯咖啡的时间，看清自己的钱在哪里
"""

import time
from datetime import datetime

import yfinance as yf
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── 在这里改你的持仓，随时手动调 ────────────────────────────────
HOLDINGS = {
    'AAPL':  {'shares': 10, 'avg_cost': 150.0},
    'MSFT':  {'shares': 5,  'avg_cost': 320.0},
    'GOOGL': {'shares': 3,  'avg_cost': 140.0},
    'TSLA':  {'shares': 8,  'avg_cost': 200.0},
    'SPY':   {'shares': 4,  'avg_cost': 450.0},
}
# ─────────────────────────────────────────────────────────────────

REFRESH_INTERVAL = 30   # 多少秒刷一次，改成 60 也没问题
BAR_TOTAL_CHARS  = 20   # 横条总宽（字符），调大调小随意

console = Console()

# 横条里的实心/空心字符，换成别的也行
BLOCK_FILLED = "█"
BLOCK_EMPTY  = "░"

# 每只票用不同颜色，纯粹好看
TICKER_COLORS = ["cyan", "magenta", "yellow", "green", "blue", "red", "white"]


def fetch_prices(tickers: list[str]) -> dict[str, float]:
    """
    批量拉当前价格，yfinance 走 1d/1m 数据
    市场关闭的时候会返回最后收盘价，延迟 15 分钟，凑合用
    """
    raw = yf.download(
        tickers,
        period="1d",
        interval="1m",
        progress=False,
        auto_adjust=True,
    )
    prices: dict[str, float] = {}

    if len(tickers) == 1:
        # 单只票的时候 yfinance 返回的 DataFrame 列名没有 ticker，单独处理
        try:
            prices[tickers[0]] = float(raw["Close"].dropna().iloc[-1])
        except Exception:
            prices[tickers[0]] = 0.0
    else:
        for t in tickers:
            try:
                prices[t] = float(raw["Close"][t].dropna().iloc[-1])
            except Exception:
                prices[t] = 0.0  # 拉不到就用 0，总比崩了强

    return prices


# ── UI 组件 ──────────────────────────────────────────────────────

def build_header(refresh_time: str) -> Panel:
    """顶部标题栏，显示名字和上次刷新时间"""
    content = Align.center(
        Text(
            f"📈  Portfolio Pulse  ·  最后刷新：{refresh_time}  ·  每 {REFRESH_INTERVAL}s 自动更新",
            style="bold white",
        ),
        vertical="middle",
    )
    return Panel(content, style="on dark_blue", height=3)


def build_holdings_table(prices: dict[str, float]) -> tuple[Panel, float, float, float]:
    """
    持仓明细表格
    同时返回 (Panel, 总市值, 总盈亏金额, 总盈亏%)
    """
    table = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Ticker",  style="bold white", justify="center", min_width=7)
    table.add_column("股数",     justify="right",    min_width=6)
    table.add_column("成本价",   justify="right",    min_width=9)
    table.add_column("现价",     justify="right",    min_width=9)
    table.add_column("市值",     justify="right",    min_width=12)
    table.add_column("盈亏金额", justify="right",    min_width=12)
    table.add_column("盈亏%",   justify="right",    min_width=9)

    total_market = 0.0
    total_cost   = 0.0

    for ticker, info in HOLDINGS.items():
        shares   = info["shares"]
        avg_cost = info["avg_cost"]
        price    = prices.get(ticker, 0.0)

        mv      = shares * price
        cost    = shares * avg_cost
        pnl     = mv - cost
        pnl_pct = (pnl / cost * 100) if cost else 0.0

        total_market += mv
        total_cost   += cost

        color    = "green" if pnl >= 0 else "red"
        sign     = "+" if pnl >= 0 else ""

        table.add_row(
            ticker,
            str(shares),
            f"${avg_cost:.2f}",
            f"${price:.2f}",
            f"${mv:,.2f}",
            Text(f"{sign}${pnl:,.2f}", style=color),
            Text(f"{sign}{pnl_pct:.2f}%", style=color),
        )

    total_pnl     = total_market - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0

    # 底部汇总行，直接拼文字加在 Panel 标题里
    pnl_color = "green" if total_pnl >= 0 else "red"
    pnl_sign  = "+" if total_pnl >= 0 else ""
    subtitle  = (
        f"[bold white]总市值 [bold yellow]${total_market:,.2f}[/bold yellow]"
        f"   总盈亏 [{pnl_color}]{pnl_sign}${total_pnl:,.2f}  ({pnl_sign}{total_pnl_pct:.2f}%)[/{pnl_color}][/bold white]"
    )
    panel = Panel(table, title="[bold cyan]持仓明细[/bold cyan]", subtitle=subtitle, border_style="bright_black")

    return panel, total_market, total_pnl, total_pnl_pct


def build_bar_chart(prices: dict[str, float], total_market: float) -> Panel:
    """
    用 block characters 拼伪饼图（其实是横向比例条）
    AAPL  ████████████░░░░  32.4%
    就这风格，简单直接
    """
    lines = Text()

    for i, (ticker, info) in enumerate(HOLDINGS.items()):
        price = prices.get(ticker, 0.0)
        mv    = info["shares"] * price
        pct   = (mv / total_market * 100) if total_market else 0.0

        filled = round(pct / 100 * BAR_TOTAL_CHARS)
        empty  = BAR_TOTAL_CHARS - filled
        bar    = BLOCK_FILLED * filled + BLOCK_EMPTY * empty

        color = TICKER_COLORS[i % len(TICKER_COLORS)]

        lines.append(f"  {ticker:<6}", style="bold white")
        lines.append(f" {bar} ", style=color)
        lines.append(f" {pct:5.1f}%\n", style="white")

    return Panel(lines, title="[bold]权重分布[/bold]", border_style="bright_black", padding=(1, 2))


def make_layout(prices: dict[str, float], refresh_time: str) -> Layout:
    """把所有模块组装成 Layout，交给 Live 渲染"""
    header                                     = build_header(refresh_time)
    holdings_panel, total_mv, total_pnl, total_pnl_pct = build_holdings_table(prices)
    chart_panel                                = build_bar_chart(prices, total_mv)

    layout = Layout()
    layout.split_column(
        Layout(header,         name="header",  size=3),
        Layout(name="body"),
    )
    layout["body"].split_row(
        Layout(holdings_panel, name="holdings", ratio=3),
        Layout(chart_panel,    name="chart",    ratio=2),
    )

    return layout


# ── 主循环 ───────────────────────────────────────────────────────

def main() -> None:
    tickers = list(HOLDINGS.keys())

    # 启动时先拉一次数据，别直接进 Live 显示一堆 0
    console.print("[bold cyan]Portfolio Pulse 启动中...[/bold cyan]")
    console.print(f"[dim]正在拉取 {', '.join(tickers)} 的行情数据...[/dim]\n")

    prices       = fetch_prices(tickers)
    refresh_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    last_fetch   = time.time()

    with Live(make_layout(prices, refresh_time), refresh_per_second=2, screen=True) as live:
        while True:
            time.sleep(1)

            now = time.time()
            if now - last_fetch >= REFRESH_INTERVAL:
                try:
                    prices       = fetch_prices(tickers)
                    refresh_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    last_fetch   = now
                except Exception:
                    pass  # 网络抽风就用上次缓存的，佛系

            live.update(make_layout(prices, refresh_time))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold green]Goodbye！[/bold green]\n")
