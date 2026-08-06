#!/usr/bin/env python3
"""半导体行业五维评分 - 完整版 (v2)"""

import sys, os, json, math
sys.path.insert(0, os.path.expanduser("~/.claude/skills/skill-pandadata-api/scripts"))
from pandadata_runtime import init_pandadata

panda_data = init_pandadata()

SYMBOLS = [
    "688256.SH","688041.SH","002371.SZ","603986.SH","688012.SH",
    "688008.SH","688981.SH","688072.SH","688525.SH","688498.SH",
    "301308.SZ","688082.SH","600584.SH","688521.SH","001309.SZ",
    "300604.SZ","688120.SH","688347.SH","688361.SH","603501.SH",
    "688396.SH","688766.SH","300223.SZ","002156.SZ","688126.SH",
    "688172.SH","688200.SH","300661.SZ","600460.SH","688110.SH",
    "688141.SH","688409.SH","688048.SH","688037.SH","603893.SH",
    "688249.SH","688702.SH","300666.SZ","300373.SZ","002049.SZ",
    "002185.SZ","688234.SH","002409.SZ","688047.SH","300672.SZ",
    "688469.SH","688728.SH","688432.SH","688220.SH","688536.SH",
]

# ========== 1. 获取最新行情和代码-名称映射 ==========
print("STEP 1: 加载数据...")
daily = panda_data.get_stock_daily(
    symbol=SYMBOLS, start_date="20260706", end_date="20260706",
    fields=["symbol","name","close"], st=True
)
sf = panda_data.get_share_float(
    symbol=SYMBOLS, start_date="20260706", end_date="20260706",
    fields=["symbol","circulation_a"]
)

name_map = {}; price_map = {}; mcap_map = {}
for _, r in daily.iterrows():
    sym = r["symbol"]; name_map[sym] = r["name"]; price_map[sym] = r["close"]
for _, r in sf.iterrows():
    sym = r["symbol"]; shares = float(r["circulation_a"] or 0)
    price = price_map.get(sym, 0)
    mcap_map[sym] = round(price * shares / 1e8, 1) if shares > 0 and price > 0 else 0

# ========== 2. 获取财务数据 (is_latest=True) ==========
print("STEP 2: 获取财务数据...")
FIN_FIELDS = ["symbol","quarter","is_n_income_attr_p","is_revenue","is_oper_cost",
              "bs_total_assets","bs_total_liab","bs_total_cur_assets","bs_total_cur_liab",
              "bs_inventory","bs_st_borr","bs_lt_borr","is_gross_profit"]
fina = panda_data.get_fina_reports(
    symbol=SYMBOLS, start_quarter="2023q1", end_quarter="2025q4",
    is_latest=True, fields=FIN_FIELDS
)
print(f"  财务数据: {len(fina)} 行")

# 按stock+quarter去重，取最新date
fina = fina.sort_values("date").drop_duplicates(subset=["symbol","quarter"], keep="last")

def get_fina(sym):
    """获取某股票的去重财报"""
    return fina[fina["symbol"] == sym].copy()

# ========== 3. 行业评分 ==========
IND_SCORE = 16.5
IND_DETAIL = {
    "景气度": (7, "AI算力+国产替代，芯片景气度持续高位"),
    "估值水位": (4, "PE 60-70%分位，合理偏高"),
    "政策环境": (3, "国家大基金三期+国产替代政策强力扶持"),
    "竞争格局": (2.5, "细分赛道龙头格局初现，部分赛道仍分散")
}

# ========== 4. 评分函数 ==========
def score_finance(sym):
    """财务状况 30分"""
    df = get_fina(sym)
    if len(df) == 0: return 0, "无财务数据"

    # 取年报(q4)数据，如果没有足够q4则用全部可用数据
    annual = df[df["quarter"].str.contains("q4", na=False)].sort_values("quarter")

    if len(annual) >= 2:
        periods = annual.tail(3) if len(annual) >= 3 else annual
    else:
        # 使用全部季度数据尾部合并
        all_q = df.sort_values("quarter")
        if len(all_q) >= 3:
            periods = all_q.tail(3)
        elif len(all_q) >= 2:
            periods = all_q.tail(2)
        else:
            return 0, f"数据不足(仅{len(df)}行)"

    score = 0; parts = {}

    # 提取数据
    p_data = []
    for _, r in periods.iterrows():
        p_data.append({
            "np": float(r.get("is_n_income_attr_p", 0) or 0),
            "rev": float(r.get("is_revenue", 0) or 0),
            "gp": float(r.get("is_gross_profit", 0) or 0),
            "cost": float(r.get("is_oper_cost", 0) or 0),
        })

    # 1.1 净利润趋势 10分
    nps = [p["np"] for p in p_data]
    if all(v > 0 for v in nps):
        if nps[2] > nps[1] > nps[0]:
            s = 10; desc = f"持续增长({nps[0]/1e8:.1f}→{nps[1]/1e8:.1f}→{nps[2]/1e8:.1f}亿)"
        elif nps[1] > nps[2] > nps[0]:
            s = 6; desc = "高位微调"
        elif nps[2] > nps[1] and nps[0] > nps[1]:
            s = 7; desc = "V型反转"
        elif nps[2] < nps[1] and nps[2] > nps[0]:
            s = 4; desc = "小幅回落"
        elif nps[2] < nps[1] < nps[0]:
            s = 3; desc = "持续下滑"
        else:
            s = 6; desc = "波动向上"
    elif nps[0] <= 0 and nps[2] > 0:
        s = 8; desc = f"扭亏为盈({nps[0]/1e8:.1f}→{nps[2]/1e8:.1f}亿)"
    elif nps[0] > 0 and nps[2] <= 0:
        s = 0; desc = "由盈转亏"
    elif all(v <= 0 for v in nps):
        s = 0; desc = "持续亏损"
    else:
        s = 4; desc = "波动盈利"
    score += s; parts["净利润趋势"] = (s, desc)

    # 1.3 营收增速 6分
    if len(p_data) >= 2 and p_data[-2]["rev"] > 0:
        growth = (p_data[-1]["rev"] - p_data[-2]["rev"]) / p_data[-2]["rev"]
        if growth > 0.30: s=6; desc=f"高速增长({growth*100:.1f}%)"
        elif growth > 0.15: s=5; desc=f"快速增长({growth*100:.1f}%)"
        elif growth > 0.05: s=4; desc=f"稳定增长({growth*100:.1f}%)"
        elif growth > 0: s=3; desc=f"低速增长({growth*100:.1f}%)"
        elif growth > -0.10: s=2; desc=f"轻微下滑({growth*100:.1f}%)"
        elif growth > -0.30: s=1; desc=f"明显下滑({growth*100:.1f}%)"
        else: s=0; desc=f"大幅下滑({growth*100:.1f}%)"
    else:
        s=3; desc="营收数据不足"
    score += s; parts["营收增速"] = (s, desc)

    # 1.2 盈利模式 8分 - 基于最近2期
    if len(p_data) >= 2:
        p1, p3 = p_data[0]["np"], p_data[-1]["np"]
        if p1 > 0 and p3 > 0 and nps[-1] > nps[-2] if len(nps)>=2 else False:
            s=8; desc="持续盈利"
        elif p1 <= 0 and p3 > 0:
            s=6; desc="扭亏为盈"
        elif p1 > 0 and p3 <= 0:
            s=0; desc="由盈转亏"
        elif p1 <= 0 and p3 <= 0:
            s=1; desc="持续亏损"
        else:
            s=4; desc="波动盈利"
    else:
        s=4; desc="数据有限"
    score += s; parts["盈利模式"] = (s, desc)

    # 1.4 毛利率 6分
    latest = p_data[-1]
    if latest["rev"] > 0:
        gp_r = latest["gp"] / latest["rev"] if latest["gp"] > 0 else 0
        np_r = latest["np"] / latest["rev"] if latest["np"] > 0 else 0

        if gp_r > 0.50: s = 6; d = f"高毛利({gp_r*100:.1f}%)"
        elif gp_r > 0.30: s = 5; d = f"中高毛利({gp_r*100:.1f}%)"
        elif gp_r > 0.20: s = 4; d = f"中等毛利({gp_r*100:.1f}%)"
        elif gp_r > 0.10: s = 3; d = f"低毛利({gp_r*100:.1f}%)"
        elif gp_r > 0.05: s = 2; d = f"微利({gp_r*100:.1f}%)"
        elif gp_r > 0: s = 1; d = f"极低毛利({gp_r*100:.1f}%)"
        else: s = 0; d = "毛利为负"

        if np_r < 0:
            s = max(0, s - 2)
            d += " [净利率为负，扣2分]"
    else:
        s=3; d="营收为0"
    score += s; parts["毛利率水平"] = (s, d)

    return min(score, 30), parts


def score_debt(sym):
    """债务偿债 15分"""
    df = get_fina(sym)
    if len(df) == 0: return 0, "无数据"

    latest = df.sort_values("quarter").iloc[-1]

    def safe_float(v, default=0.0):
        try:
            f = float(v) if v is not None and v == v else default  # v == v catches NaN
            return f
        except: return default

    ta = safe_float(latest.get("bs_total_assets"))
    tl = safe_float(latest.get("bs_total_liab"))
    tca = safe_float(latest.get("bs_total_cur_assets"))
    tcl = safe_float(latest.get("bs_total_cur_liab"))
    inv = safe_float(latest.get("bs_inventory"))
    stb = safe_float(latest.get("bs_st_borr"))
    ltb = safe_float(latest.get("bs_lt_borr"))

    if ta <= 0: return 0, "资产数据为空"

    score = 0; parts = {}

    # 4.1 资产负债率 5分
    dr = tl / ta
    if dr < 0.30: s=5; d=f"低负债({dr*100:.1f}%)"
    elif dr < 0.45: s=4; d=f"健康({dr*100:.1f}%)"
    elif dr < 0.60: s=3; d=f"中等({dr*100:.1f}%)"
    elif dr < 0.70: s=2; d=f"偏高({dr*100:.1f}%)"
    elif dr < 0.85: s=1; d=f"高负债({dr*100:.1f}%)"
    else: s=0; d=f"极高({dr*100:.1f}%)"
    score += s; parts["资产负债率"] = (s, d)

    # 4.2 流动/速动 4分
    cr = tca / tcl if tcl > 0 else 99
    qr = (tca - inv) / tcl if tcl > 0 and inv >= 0 else cr
    if cr > 2 and qr > 1: s=4; d=f"优秀(流动{cr:.2f}/速动{qr:.2f})"
    elif cr > 1.5 and qr > 0.8: s=3; d=f"良好(流动{cr:.2f}/速动{qr:.2f})"
    elif cr > 1 and qr > 0.5: s=2; d=f"一般(流动{cr:.2f}/速动{qr:.2f})"
    elif cr > 0.5 and qr > 0.2: s=1; d=f"偏弱(流动{cr:.2f}/速动{qr:.2f})"
    else: s=0; d=f"差(流动{cr:.2f}/速动{qr:.2f})"
    score += s; parts["流动/速动比率"] = (s, d)

    # 4.3 质押 3分
    try:
        pl = panda_data.get_stock_pledge_stat(symbol=sym, fields=[])
        if pl is not None and len(pl) > 0:
            pr = float(pl.iloc[-1].get("pledge_ratio", 0) or 0)
        else:
            pr = 0
    except: pr = 0

    if pr < 0.10: s=3; d=f"低质押({pr*100:.1f}%)"
    elif pr < 0.30: s=2; d=f"中等({pr*100:.1f}%)"
    elif pr < 0.50: s=1; d=f"较高({pr*100:.1f}%)"
    else: s=0; d=f"极高({pr*100:.1f}%)"
    score += s; parts["股权质押"] = (s, d)

    # 4.4 有息负债率 3分
    idr = (stb + ltb) / ta
    if idr < 0.10: s=3; d=f"极低({idr*100:.1f}%)"
    elif idr < 0.20: s=2.5; d=f"低({idr*100:.1f}%)"
    elif idr < 0.30: s=2; d=f"中等({idr*100:.1f}%)"
    elif idr < 0.40: s=1.5; d=f"偏高({idr*100:.1f}%)"
    elif idr < 0.50: s=1; d=f"高({idr*100:.1f}%)"
    else: s=0; d=f"极高({idr*100:.1f}%)"
    score += s; parts["有息负债率"] = (s, d)

    return min(score, 15), parts


def score_news(sym):
    """消息面 20分"""
    score = 0; parts = {}

    # 2.1 业绩预告 6分
    try:
        fc = panda_data.get_fina_forecast(symbol=sym, fields=[])
        if fc is not None and len(fc) > 0:
            lr = fc.iloc[-1]
            c = str(lr.get("forecast_content","") or "")
            if any(k in c for k in ["预增","大幅上升","扭亏"]): s=6; d="业绩预增"
            elif any(k in c for k in ["略增","小幅上升"]): s=5; d="业绩略增"
            elif any(k in c for k in ["续盈","持平"]): s=3; d="业绩平稳"
            elif any(k in c for k in ["略减","小幅下降"]): s=2; d="业绩略降"
            elif any(k in c for k in ["预减","大幅下降","预亏","首亏"]): s=0; d="业绩预警"
            else: s=3; d="中性"
        else:
            s=3; d="已披露正式财报，中性"
    except: s=3; d="数据获取中性"
    score += s; parts["业绩预告"] = (s, d)

    # 2.2-2.3-2.4 简化处理
    # 事件情绪 (简化:默认中性)
    score += 3; parts["事件情绪"] = (3, "中性（基本面分析不包含实时新闻事件）")

    return min(score, 20), parts


def score_sh(sym):
    """增减持 15分"""
    score = 0; parts = {}

    # 5.1 大股东增减持 6分
    try:
        sh = panda_data.get_stock_shareholder_change(symbol=sym, fields=[])
        if sh is not None and len(sh) > 0:
            pts = sh["plan_type"].tolist() if "plan_type" in sh.columns else []
            inc = sum(1 for p in pts if "增" in str(p))
            dec = sum(1 for p in pts if "减" in str(p))
            if inc > 0 and dec == 0: s=6; d="大股东增持" if inc>1 else "有增持计划"
            elif inc > dec: s=4; d="增持为主"
            elif inc > 0 and dec > 0: s=3; d="增减并存"
            elif dec > 0: s=1; d="存在减持"
            else: s=3; d="无明显增减持"
        else:
            s=3; d="无数据"
    except: s=3; d="数据获取失败"
    score += s; parts["大股东增减持"] = (s, d)

    # 5.2 高管 3分
    score += 2; parts["高管增减持"] = (2, "默认中性")

    # 5.3 回购 3分
    try:
        rp = panda_data.get_repurchase(symbol=sym, fields=[])
        if rp is not None and len(rp) > 0:
            amt = float(rp.iloc[-1].get("repo_amount", 0) or 0)
            if amt > 5e8: s=3; d=f"大额回购({amt/1e8:.1f}亿)"
            elif amt > 0: s=2; d=f"有回购({amt/1e4:.0f}万)"
            else: s=1.5; d="有回购预案"
        else:
            s=1.5; d="无回购计划"
    except: s=1.5; d="数据失败"
    score += s; parts["回购计划"] = (s, d)

    # 5.4 解禁 3分
    try:
        rt = panda_data.get_restricted_list(symbol=sym, fields=[])
        if rt is not None and len(rt) > 0:
            future = [r for _, r in rt.iterrows() if str(r.get("list_date","")) > "20260706"]
            if len(future) == 0: s=3; d="未来无解禁"
            elif len(future) <= 2: s=2.5; d=f"未来{len(future)}笔，压力小"
            else: s=1; d=f"未来{len(future)}笔解禁"
        else:
            s=3; d="无限售解禁"
    except: s=3; d="数据失败"
    score += s; parts["限售解禁"] = (s, d)

    return min(score, 15), parts


# ========== 5. 执行评分 ==========
print("\nSTEP 3: 逐股评分...\n")
results = []

for i, sym in enumerate(SYMBOLS):
    name = name_map.get(sym, sym)
    mcap = mcap_map.get(sym, 0)

    fs, fd = score_finance(sym)
    ns, nd = score_news(sym)
    ds, dd = score_debt(sym)
    ss, sd = score_sh(sym)
    inds = IND_SCORE

    total = fs + ns + inds + ds + ss

    if total >= 85: grade, stars = "A+", "★★★★★"
    elif total >= 70: grade, stars = "A", "★★★★"
    elif total >= 55: grade, stars = "B+", "★★★"
    elif total >= 40: grade, stars = "B", "★★"
    else: grade, stars = "C", "★"

    results.append({
        "rank": i+1, "symbol": sym, "name": name, "mcap": mcap,
        "finance": round(fs, 1), "news": round(ns, 1),
        "industry": round(inds, 1), "debt": round(ds, 1),
        "shareholder": round(ss, 1), "total": round(total, 1),
        "grade": grade, "stars": stars,
        "fin_detail": fd, "debt_detail": dd,
    })

    print(f"  [{i+1}/50] {name:<8s} {sym:>10s} 财务{fs:>5.1f} 债务{ds:>5.1f} 增减持{ss:>5.1f} → {total:>5.1f}点 {stars}")

# ========== 6. 排序 ==========
results.sort(key=lambda x: x["total"], reverse=True)

print("\n" + "=" * 70)
print("🏆 半导体行业（L2:801081）基本面评分 TOP10")
print("=" * 70)
print(f"📅 评分日期: 2026-07-06 | 成分股: 172只 → 市值TOP50评分")
print(f"🏭 行业评分: {IND_SCORE}/20（统一评分）")
print()
print(f"{'排名':>4} {'名称':>8} {'代码':>10} {'总分':>6} {'财务':>6} {'消息':>6} {'行业':>6} {'债务':>6} {'增减持':>6} {'等级':>6}")
print("-" * 70)
for i, r in enumerate(results[:10], 1):
    print(f"{i:4d} {r['name']:>8} {r['symbol']:>10} {r['total']:6.1f} {r['finance']:6.1f} {r['news']:6.1f} {r['industry']:6.1f} {r['debt']:6.1f} {r['shareholder']:6.1f} {r['stars']:>6}")

print("\n\n📊 详细评分:")
for i, r in enumerate(results[:10], 1):
    print(f"\n{'─'*55}")
    print(f"#{i} {r['name']}({r['symbol']}) | {r['total']}/100 {r['stars']} {r['grade']} | 流通市值{r['mcap']:.0f}亿")
    fd = r["fin_detail"]
    if isinstance(fd, dict):
        for k, v in fd.items():
            if isinstance(v, tuple): print(f"  {k}: {v[0]}分 - {v[1]}")
            elif isinstance(v, str): print(f"  {k}: {v}")
    else:
        print(f"  {fd}")
    dd = r["debt_detail"]
    if isinstance(dd, dict):
        for k, v in dd.items():
            if isinstance(v, tuple): print(f"  {k}: {v[0]}分 - {v[1]}")
            elif isinstance(v, str): print(f"  {k}: {v}")
    else:
        print(f"  {dd}")
    # 行业
    for k, (s, d) in IND_DETAIL.items():
        print(f"  {k}: {s}分 - {d}")

# JSON
print("\n\n=== JSON ===")
print(json.dumps([{
    "排名": i+1, "名称": r["name"], "代码": r["symbol"],
    "总分": r["total"], "财务": r["finance"], "消息": r["news"],
    "行业": r["industry"], "债务": r["debt"], "增减持": r["shareholder"],
    "等级": f"{r['stars']} {r['grade']}", "流通市值_亿": r["mcap"]
} for i, r in enumerate(results[:10])], ensure_ascii=False, indent=2))
print("=== END ===")
