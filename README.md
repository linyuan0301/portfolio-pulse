# 💹 Portfolio Pulse

实时终端投资组合看板，用 Rich + yfinance + plotext 构建。

## 安装

```bash
pip install -r requirements.txt
```

## 配置持仓

编辑 `portfolio.json`，填入自己的持仓：

```json
{
  "holdings": [
    {"symbol": "AAPL",    "shares": 10,  "avg_cost": 150.0},
    {"symbol": "BTC-USD", "shares": 0.5, "avg_cost": 40000.0},
    {"symbol": "TSLA",    "shares": 5,   "avg_cost": 200.0},
    {"symbol": "QQQ",     "shares": 8,   "avg_cost": 380.0}
  ],
  "refresh_interval": 30
}
```

- `symbol`：Yahoo Finance ticker（股票、ETF、加密货币均可）
- `shares`：持仓数量
- `avg_cost`：持仓均价（用于计算盈亏）
- `refresh_interval`：自动刷新间隔（秒）

## 启动

```bash
python portfolio_pulse.py
```

## 键盘操作

| 键 | 功能 |
|----|------|
| `r` | 立即刷新价格 |
| `q` | 退出 |

## 界面说明

```
┌──────────────────────────────────────────────────────────────────┐
│  💹 Portfolio Pulse    2026-03-31 10:25:01    下次刷新: 28s      │
├───────────────────────────────────┬──────────────────────────────┤
│  持仓明细                          │  市值占比                    │
│  Symbol  当前价  涨跌幅  持仓量  ... │  AAPL     ████████  35.1%   │
│  AAPL   $214.23  +1.2%  10  ...   │  BTC-USD  ████████  28.4%   │
│  ...                              │  ...                         │
│  合计    $xx,xxx          +$x,xxx  │                              │
├───────────────────────────────────┴──────────────────────────────┤
│              [r] 立即刷新    [q] 退出                             │
└──────────────────────────────────────────────────────────────────┘
```

- 价格拉取失败时显示上次缓存值并标注 `(cached)`
- 数据来自 Yahoo Finance，可能有15分钟延迟
