#!/usr/bin/env python3
"""
💹 Portfolio Pulse — 终端投资组合看板
实时追踪持仓盈亏，数据来自 Yahoo Finance
"""

import contextlib
import io
import json
import queue
import select
import sys
import termios
import threading
import time
import tty
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import plotext as plt
import yfinance as yf
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── 配置文件路径 ────────────────────────────────────────────────────
CONFIG_FILE = Path(__file__).parent / "portfolio.json"

# 持仓占比条颜色，循环使用
TICKER_COLORS = [
    "cyan", "magenta", "yellow", "green",
    "blue", "bright_red", "bright_cyan", "bright_yellow",
]
BAR_WIDTH = 30  # 横向 bar 字符宽度

console = Console()


# ── 配置加载 ────────────────────────────────────────────────────────

def load_config() -> tuple[dict, int]:
    """读取 portfolio.json，返回 (holdings_dict, refresh_interval)"""
    with open(CONFIG_FILE, encoding="utf-8") as f:
        data = json.load(f)
    holdings = {
        h["symbol"]: {"shares": h["shares"], "avg_cost": h["avg_cost"]}
        for h in data["holdings"]
    }
    refresh_interval = data.get("refresh_interval", 30)
    return holdings, refresh_interval


# ── 行情拉取 ────────────────────────────────────────────────────────

def _fetch_one(symbol: str) -> tuple[str, dict]:
    """拉取单只 ticker 的实时价格和24h涨跌幅"""
    try:
        fi = yf.Ticker(symbol).fast_info
        price = float(fi.last_price or 0)
        prev = float(fi.previous_close or 0)
        change_pct = (price - prev) / prev * 100 if prev else 0.0
        return symbol, {"price": price, "change_pct": change_pct, "cached": False}
    except Exception:
        return symbol, {"price": 0.0, "change_pct": 0.0, "cached": True}


def fetch_prices(symbols: list[str], cached: dict) -> dict[str, dict]:
    """
    并发拉取所有 symbol 行情。
    拉取失败时保留上次缓存值并标记 cached=True。
    """
    result = dict(cached)
    with ThreadPoolExecutor(max_workers=min(len(symbols), 8)) as ex:
        futures = {ex.submit(_fetch_one, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, data = future.result()
            if data["price"] > 0:
                result[sym] = data
            elif sym in result:
                # 拉取失败，保留旧价格但标记 cached
                result[sym] = {**result[sym], "cached": True}
            else:
                result[sym] = data
    return result


# ── UI 组件 ─────────────────────────────────────────────────────────

def build_header(refresh_time: str, next_refresh: int, fetching: bool) -> Panel:
    """顶部标题栏：图标 + 时间 + 倒计时"""
    t = Text(justify="center")
    t.append("💹 Portfolio Pulse", style="bold bright_white")
    t.append(f"   {refresh_time}", style="dim white")
    if fetching:
        t.append("   ⟳ 正在获取最新价格...", style="bright_cyan")
    else:
        t.append(f"   下次刷新: {next_refresh}s", style="dim cyan")
    return Panel(t, style="on grey11", height=3)


def build_table(holdings: dict, price_data: dict) -> tuple[Panel, float, float]:
    """
    持仓明细表格
    列：Symbol / 当前价 / 涨跌幅(24h) / 持仓量 / 持仓市值 / 成本 / 盈亏金额 / 盈亏%
    返回 (Panel, total_market_value, total_cost)
    """
    tbl = Table(
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
        padding=(0, 1),
    )
    tbl.add_column("Symbol",       style="bold white", justify="center", min_width=8)
    tbl.add_column("当前价",        justify="right",    min_width=10)
    tbl.add_column("涨跌幅(24h)",   justify="right",    min_width=12)
    tbl.add_column("持仓量",        justify="right",    min_width=8)
    tbl.add_column("持仓市值",      justify="right",    min_width=13)
    tbl.add_column("成本",          justify="right",    min_width=13)
    tbl.add_column("盈亏金额",      justify="right",    min_width=13)
    tbl.add_column("盈亏%",        justify="right",    min_width=10)

    total_mv   = 0.0
    total_cost = 0.0

    for symbol, info in holdings.items():
        shares   = info["shares"]
        avg_cost = info["avg_cost"]
        pd_      = price_data.get(symbol, {"price": 0.0, "change_pct": 0.0, "cached": True})

        price      = pd_["price"]
        change_pct = pd_["change_pct"]
        is_cached  = pd_["cached"]

        mv      = shares * price
        cost    = shares * avg_cost
        pnl     = mv - cost
        pnl_pct = pnl / cost * 100 if cost else 0.0

        total_mv   += mv
        total_cost += cost

        pnl_color = "green" if pnl >= 0 else "red"
        chg_color = "green" if change_pct >= 0 else "red"
        pnl_sign  = "+" if pnl >= 0 else ""
        chg_sign  = "+" if change_pct >= 0 else ""

        # 拉取失败时标注 (cached)
        price_text = Text()
        price_text.append(f"${price:,.2f}")
        if is_cached:
            price_text.append(" (cached)", style="dim yellow")

        tbl.add_row(
            symbol,
            price_text,
            Text(f"{chg_sign}{change_pct:.2f}%", style=chg_color),
            str(shares),
            f"${mv:,.2f}",
            f"${cost:,.2f}",
            Text(f"{pnl_sign}${pnl:,.2f}",   style=pnl_color),
            Text(f"{pnl_sign}{pnl_pct:.2f}%", style=pnl_color),
        )

    # 汇总行
    total_pnl     = total_mv - total_cost
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0.0
    pnl_color     = "green" if total_pnl >= 0 else "red"
    pnl_sign      = "+" if total_pnl >= 0 else ""

    tbl.add_section()
    tbl.add_row(
        Text("合计", style="bold white"),
        "", "", "",
        Text(f"${total_mv:,.2f}",                    style="bold yellow"),
        Text(f"${total_cost:,.2f}",                  style="bold white"),
        Text(f"{pnl_sign}${total_pnl:,.2f}",         style=f"bold {pnl_color}"),
        Text(f"{pnl_sign}{total_pnl_pct:.2f}%",      style=f"bold {pnl_color}"),
    )

    panel = Panel(
        tbl,
        title="[bold cyan]持仓明细[/bold cyan]",
        subtitle="[dim]数据来自 Yahoo Finance，可能有15分钟延迟[/dim]",
        border_style="bright_black",
    )
    return panel, total_mv, total_cost


def _build_plotext_chart(symbols: list[str], pcts: list[float]) -> str:
    """用 plotext 生成横向 bar chart，返回 ANSI 字符串"""
    plt.clf()
    plt.theme("dark")
    # 截断过长的 symbol 名，保持图表整洁
    labels = [s[:8] for s in symbols]
    plt.simple_bar(labels, pcts, width=40, title="市值占比 (%)")
    plt.plotsize(50, len(symbols) * 2 + 5)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        plt.show()
    return buf.getvalue()


def build_chart(holdings: dict, price_data: dict, total_mv: float) -> Panel:
    """
    持仓占比图表（plotext 横向 bar chart）。
    plotext 不可用时降级为 block-char 横条。
    """
    symbols = list(holdings.keys())
    mvs     = [holdings[s]["shares"] * price_data.get(s, {}).get("price", 0.0) for s in symbols]
    pcts    = [mv / total_mv * 100 if total_mv else 0.0 for mv in mvs]

    # ── 尝试 plotext ──────────────────────────────────────────────
    try:
        chart_str = _build_plotext_chart(symbols, pcts)
        chart_renderable = Text.from_ansi(chart_str)
        return Panel(
            chart_renderable,
            title="[bold]市值占比[/bold]",
            border_style="bright_black",
            padding=(0, 1),
        )
    except Exception:
        pass

    # ── 降级：block-char 横条 ─────────────────────────────────────
    lines = Text()
    for i, (symbol, pct) in enumerate(zip(symbols, pcts)):
        filled = round(pct / 100 * BAR_WIDTH)
        bar    = "█" * filled + "░" * (BAR_WIDTH - filled)
        color  = TICKER_COLORS[i % len(TICKER_COLORS)]
        lines.append(f"  {symbol:<8}", style="bold white")
        lines.append(f"{bar}", style=color)
        lines.append(f"  {pct:5.1f}%\n", style="bright_white")

    return Panel(
        lines,
        title="[bold]市值占比[/bold]",
        border_style="bright_black",
        padding=(1, 2),
    )


def build_footer() -> Panel:
    t = Text(justify="center")
    t.append("[r]", style="bold yellow")
    t.append(" 立即刷新", style="dim white")
    t.append("   [q]", style="bold red")
    t.append(" 退出", style="dim white")
    return Panel(t, style="on grey11", height=3)


def make_layout(
    holdings: dict,
    price_data: dict,
    refresh_time: str,
    next_refresh: int,
    fetching: bool,
) -> Layout:
    header                     = build_header(refresh_time, next_refresh, fetching)
    table_panel, total_mv, _   = build_table(holdings, price_data)
    chart_panel                = build_chart(holdings, price_data, total_mv)
    footer                     = build_footer()

    layout = Layout()
    layout.split_column(
        Layout(header,      name="header", size=3),
        Layout(name="body"),
        Layout(footer,      name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(table_panel, name="table", ratio=3),
        Layout(chart_panel, name="chart", ratio=2),
    )
    return layout


# ── 键盘监听（非阻塞，独立线程）─────────────────────────────────────

def _keyboard_thread(key_queue: queue.Queue, stop_event: threading.Event) -> None:
    """在 raw 模式下监听 stdin，把按键放入队列"""
    fd           = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while not stop_event.is_set():
            if select.select([sys.stdin], [], [], 0.1)[0]:
                ch = sys.stdin.read(1)
                key_queue.put(ch.lower())
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# ── 主循环 ───────────────────────────────────────────────────────────

def main() -> None:
    holdings, refresh_interval = load_config()
    symbols = list(holdings.keys())

    console.print("[bold cyan]💹 Portfolio Pulse 启动中...[/bold cyan]")
    console.print(f"[dim]正在获取 {', '.join(symbols)} 行情...[/dim]\n")

    # 首次拉取
    price_data   = fetch_prices(symbols, {})
    refresh_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    last_fetch   = time.time()
    fetching     = False

    # 线程安全锁（保护 price_data / refresh_time / last_fetch）
    lock       = threading.Lock()
    key_queue  = queue.Queue()
    stop_event = threading.Event()

    kb = threading.Thread(
        target=_keyboard_thread,
        args=(key_queue, stop_event),
        daemon=True,
    )
    kb.start()

    def do_refresh() -> None:
        """在后台线程里拉取行情，完成后更新共享状态"""
        nonlocal price_data, refresh_time, last_fetch, fetching
        try:
            new_data = fetch_prices(symbols, price_data)
        except Exception:
            new_data = {s: {**price_data.get(s, {"price": 0.0, "change_pct": 0.0}), "cached": True}
                        for s in symbols}
        with lock:
            price_data   = new_data
            refresh_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            last_fetch   = time.time()
            fetching     = False

    running = True
    layout  = make_layout(holdings, price_data, refresh_time, refresh_interval, False)

    with Live(layout, refresh_per_second=4, screen=True) as live:
        while running:
            time.sleep(0.1)

            # 处理键盘事件
            while True:
                try:
                    key = key_queue.get_nowait()
                except queue.Empty:
                    break
                if key in ("q", "\x03", "\x1b"):   # q / Ctrl-C / Esc
                    running = False
                    break
                elif key == "r":
                    with lock:
                        if not fetching:
                            fetching   = True
                            last_fetch = 0  # 强制立即刷新

            if not running:
                break

            with lock:
                _price_data   = price_data
                _refresh_time = refresh_time
                _last_fetch   = last_fetch
                _fetching     = fetching

            now          = time.time()
            elapsed      = now - _last_fetch
            next_refresh = max(0, int(refresh_interval - elapsed))

            # 触发后台刷新
            if elapsed >= refresh_interval and not _fetching:
                with lock:
                    fetching = True
                threading.Thread(target=do_refresh, daemon=True).start()

            layout = make_layout(
                holdings, _price_data, _refresh_time, next_refresh,
                fetching or _fetching,
            )
            live.update(layout)

    stop_event.set()
    console.print("\n[bold green]再见！[/bold green]\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold green]再见！[/bold green]\n")
