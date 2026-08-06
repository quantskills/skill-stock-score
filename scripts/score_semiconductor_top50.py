#!/usr/bin/env python3
"""半导体行业TOP50评分脚本"""

import sys, json, os

sys.path.insert(0, os.path.expanduser("~/.claude/skills/skill-pandadata-api/scripts"))
from pandadata_runtime import init_pandadata

panda_data = init_pandadata()

# ========== 1. 获取半导体行业成分股 ==========
print("📡 获取半导体行业成分股...")
constituents = panda_data.get_industry_constituents(
    industry_code="801081", level="L2", fields=[]
)
print(f"   成分股总数: {len(constituents)}")

# ========== 2. 获取最新行情 + 股本数据 ==========
print("📡 获取最新行情和股本数据...")
symbols = list(constituents["stock_symbol"])

# 分批获取行情（批次太大可能失败）
daily = panda_data.get_stock_daily(
    symbol=symbols,
    start_date="20260706", end_date="20260706",
    fields=["symbol", "name", "close", "amount"],
    st=True
)
print(f"   行情数据: {len(daily)} 条")

# 获取股本数据
share_float = panda_data.get_share_float(
    symbol=symbols,
    start_date="20260706", end_date="20260706",
    fields=["symbol", "circulation_a", "total"]
)
print(f"   股本数据: {len(share_float)} 条")

# ========== 3. 合并计算流通市值 ==========
price_map = {}
for _, row in daily.iterrows():
    price_map[row["symbol"]] = row["close"]

float_map = {}
for _, row in share_float.iterrows():
    try:
        float_map[row["symbol"]] = float(row["circulation_a"])
    except:
        float_map[row["symbol"]] = 0

# 计算流通市值并排序
stock_list = []
for _, row in constituents.iterrows():
    sym = row["stock_symbol"]
    name = row["stock_name"]
    price = price_map.get(sym, 0)
    shares = float_map.get(sym, 0)
    market_cap = price * shares / 1e8 if shares else 0  # 亿元
    if price > 0:
        stock_list.append({"symbol": sym, "name": name, "close": price, "mcap": round(market_cap, 2)})

stock_list.sort(key=lambda x: x["mcap"], reverse=True)
top50 = stock_list[:50]

print(f"\n📊 流通市值TOP50:")
for i, s in enumerate(top50, 1):
    print(f"  {i:2d}. {s['symbol']} {s['name']:8s} 收盘{s['close']:>8.2f} 流通市值{s['mcap']:>8.1f}亿")

print("\n=== TOP50 股票列表 ===")
sym_list = [s["symbol"] for s in top50]
print(json.dumps(sym_list))
