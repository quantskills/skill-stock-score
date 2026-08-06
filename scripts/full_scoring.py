#!/usr/bin/env python3
"""半导体行业TOP50 - 五维基本面评分完整脚本"""

import sys, os, json, math
from datetime import datetime, timedelta

sys.path.insert(0, os.path.expanduser("~/.claude/skills/skill-pandadata-api/scripts"))
from pandadata_runtime import init_pandadata

panda_data = init_pandadata()

# ========== 1. 获取成分股 & 排序 ==========
print("STEP 1: 获取半导体行业成分股...")
constituents = panda_data.get_industry_constituents(
    industry_code="801081", level="L2", fields=[]
)
all_symbols = list(constituents["stock_symbol"])
print(f"  成分股总数: {len(all_symbols)}")

# 行情
daily = panda_data.get_stock_daily(
    symbol=all_symbols,
    start_date="20260706", end_date="20260706",
    fields=["symbol", "name", "close", "amount"],
    st=True
)
share_float = panda_data.get_share_float(
    symbol=all_symbols,
    start_date="20260706", end_date="20260706",
    fields=["symbol", "circulation_a"]
)

price_map = {}
for _, r in daily.iterrows():
    price_map[r["symbol"]] = r["close"]
float_map = {}
for _, r in share_float.iterrows():
    try: float_map[r["symbol"]] = float(r["circulation_a"])
    except: float_map[r["symbol"]] = 0

stock_list = []
for _, row in constituents.iterrows():
    sym, name = row["stock_symbol"], row["stock_name"]
    price = price_map.get(sym, 0)
    shares = float_map.get(sym, 0)
    mcap = price * shares / 1e8 if shares else 0
    if price > 0:
        stock_list.append({"symbol": sym, "name": name, "close": price, "mcap": round(mcap, 2)})

stock_list.sort(key=lambda x: x["mcap"], reverse=True)
top50 = stock_list[:50]
top10_syms = [s["symbol"] for s in top50[:10]]

print(f"\nTOP10 股票: {top10_syms}")

# ========== 2. 批量获取财务数据（利润表+资产负债表）==========
print("\nSTEP 2: 批量获取财务数据...")

# 获取最近3年年报（2023-2025）和最新季度数据
def get_fina_safe(symbols, start_q, end_q):
    """安全获取财务报表"""
    try:
        return panda_data.get_fina_reports(
            symbol=symbols,
            start_quarter=start_q,
            end_quarter=end_q,
            is_latest=False,
            fields=["symbol","quarter","date","is_revenue","is_oper_cost","is_end_net_profit",
                    "is_n_income_attr_p","is_gross_profit","bs_total_assets","bs_total_liab",
                    "bs_total_cur_assets","bs_total_cur_liab","bs_inventory","bs_st_borr",
                    "bs_lt_borr","bs_operate_profit","is_total_profit","is_income_tax",
                    "is_fin_exp"]
        )
    except Exception as e:
        print(f"   财务数据获取失败: {e}")
        return None

# 获取年报数据 (end_type=4 表示年报)
fina_all = get_fina_safe(
    top10_syms,  # 先算TOP10
    "2023q1", "2025q4"
)

if fina_all is None or len(fina_all) == 0:
    print("ERROR: 无法获取财务数据")
    sys.exit(1)

print(f"  获取到 {len(fina_all)} 条财务记录")

# ========== 3. 行业前景评分（同行业统一评分）==========
print("\nSTEP 3: 行业前景评分...")

# 行业前景维度 - 半导体行业统一评分
industry_score = {
    "景气度": 7,    # 半导体受AI国产替代持续高景气
    "估值水位": 4,  # PE偏高但成长性支撑
    "政策环境": 3,  # 国家大基金、国产替代强鼓励
    "竞争格局": 2.5 # 龙头集中但竞争激烈
}
industry_total = sum(industry_score.values())  # 7+4+3+2.5 = 16.5/20
print(f"  行业评分: {industry_total}/20")

industry_detail = {
    "景气度": {"得分": 7, "说明": "AI算力需求爆发+国产替代加速，芯片行业高景气"},
    "估值水位": {"得分": 4, "说明": "PE处于历史60-70%分位，偏高但成长股合理"},
    "政策环境": {"得分": 3, "说明": "国家大基金持续投入，国产芯片强鼓励政策"},
    "竞争格局": {"得分": 2.5, "说明": "龙头发力但国产替代空间大，竞争加剧"}
}

# ========== 4. 逐股评分函数 ==========
def score_finance(sym, fina_df):
    """财务状况评分 (30分)"""
    try:
        stock_fina = fina_df[fina_df["symbol"] == sym].copy()
        if len(stock_fina) == 0:
            return 0, {"error": "无财务数据"}

        # 按quarter排序去重，取年报(ending with q4)
        stock_fina = stock_fina.drop_duplicates(subset=["quarter"])
        annual = stock_fina[stock_fina["quarter"].str.contains("q4", na=False)].sort_values("quarter")

        # 如果没有足够的年报数据，尝试用最近3期数据
        if len(annual) < 2:
            # 用最新数据
            all_q = stock_fina.sort_values("quarter")
            periods = all_q.tail(3)
        else:
            periods = annual.tail(3)

        if len(periods) < 2:
            return 0, {"error": "财务数据不足3期"}

        # 提取净利润和营收
        p_list = []
        for _, r in periods.iterrows():
            try:
                np_val = float(r.get("is_n_income_attr_p", 0) or 0)
                rev_val = float(r.get("is_revenue", 0) or 0)
                cost_val = float(r.get("is_oper_cost", 0) or 0)
                gp_val = float(r.get("is_gross_profit", 0) or 0)
            except:
                np_val, rev_val, cost_val, gp_val = 0, 0, 0, 0
            p_list.append({"np": np_val, "rev": rev_val, "cost": cost_val, "gp": gp_val})

        details = {}
        total = 0

        # 1.1 净利润趋势 (10分)
        np_vals = [p["np"] for p in p_list]
        np_pos = [v > 0 for v in np_vals]

        if len(np_vals) >= 3:
            p3, p2, p1 = np_vals[-1], np_vals[-2], np_vals[-3]
            if p3 > p2 > p1 and all(v > 0 for v in [p3, p2, p1]):
                np_trend_score = 10
                np_trend_desc = "利润持续增长"
            elif p2 > p3 > p1 and all(v > 0 for v in [p3, p2, p1]):
                np_trend_score = 6
                np_trend_desc = "高位微调"
            elif p3 < p2 and p3 > p1 and all(v > 0 for v in [p3, p2, p1]):
                np_trend_score = 4
                np_trend_desc = "小幅回落"
            elif p3 < p2 < p1 and all(v > 0 for v in [p3, p2, p1]):
                np_trend_score = 3
                np_trend_desc = "持续下滑中"
            elif all(v <= 0 for v in [p3, p2, p1]):
                np_trend_score = 0
                np_trend_desc = "持续亏损"
            elif p1 <= 0 and p3 > 0:
                np_trend_score = 8
                np_trend_desc = "扭亏为盈"
            elif p1 > 0 and p3 <= 0:
                np_trend_score = 0
                np_trend_desc = "由盈转亏"
            elif p3 > p2 and p1 > p2:
                np_trend_score = 7
                np_trend_desc = "V型反转"
            else:
                np_trend_score = 4
                np_trend_desc = "波动盈利"
        elif len(np_vals) == 2:
            p2, p1 = np_vals[-1], np_vals[-2]
            if p2 > p1 and all(v > 0 for v in [p2, p1]):
                np_trend_score = 6
                np_trend_desc = "增长中（仅2期）"
            elif p2 < p1 and all(v > 0 for v in [p2, p1]):
                np_trend_score = 4
                np_trend_desc = "回落中（仅2期）"
            else:
                np_trend_score = 3
                np_trend_desc = "波动（仅2期）"
        else:
            np_trend_score = 5
            np_trend_desc = "数据不足"

        total += np_trend_score
        details["净利润趋势"] = {"得分": np_trend_score, "说明": np_trend_desc}

        # 1.2 盈利模式 (8分)
        if len(p_list) >= 2:
            p1_np = p_list[0]["np"]
            p3_np = p_list[-1]["np"]
            if p1_np > 0 and p3_np > 0 and (len(p_list) < 3 or (p_list[-1]["np"] > p_list[-2]["np"])):
                pm_score = 8
                pm_desc = "持续盈利"
            elif p1_np <= 0 and p3_np > 0:
                pm_score = 6
                pm_desc = "扭亏为盈"
            elif p1_np > 0 and p3_np <= 0:
                pm_score = 0
                pm_desc = "由盈转亏"
            elif p1_np <= 0 and p3_np <= 0:
                pm_score = 1
                pm_desc = "持续亏损"
            else:
                pm_score = 4
                pm_desc = "波动盈利"
        else:
            pm_score = 4
            pm_desc = "数据有限"

        total += pm_score
        details["盈利模式"] = {"得分": pm_score, "说明": pm_desc}

        # 1.3 营收增速 (6分)
        if len(p_list) >= 2:
            latest_rev = p_list[-1]["rev"]
            prev_rev = p_list[-2]["rev"]
            if prev_rev > 0:
                rev_growth = (latest_rev - prev_rev) / prev_rev
            else:
                rev_growth = 0

            if rev_growth > 0.30: rev_score = 6; rev_desc = f"高速增长({rev_growth*100:.1f}%)"
            elif rev_growth > 0.15: rev_score = 5; rev_desc = f"快速增长({rev_growth*100:.1f}%)"
            elif rev_growth > 0.05: rev_score = 4; rev_desc = f"稳定增长({rev_growth*100:.1f}%)"
            elif rev_growth > 0: rev_score = 3; rev_desc = f"低速增长({rev_growth*100:.1f}%)"
            elif rev_growth > -0.10: rev_score = 2; rev_desc = f"轻微下滑({rev_growth*100:.1f}%)"
            elif rev_growth > -0.30: rev_score = 1; rev_desc = f"明显下滑({rev_growth*100:.1f}%)"
            else: rev_score = 0; rev_desc = f"大幅下滑({rev_growth*100:.1f}%)"
        else:
            rev_score = 3; rev_desc = "数据不足"

        total += rev_score
        details["营收增速"] = {"得分": rev_score, "说明": rev_desc}

        # 1.4 毛利率 (6分)
        latest = p_list[-1]
        if latest["rev"] > 0:
            if latest["gp"] > 0:
                gp_margin = latest["gp"] / latest["rev"]
            else:
                gp_margin = 0
            np_margin = latest["np"] / latest["rev"] if latest["np"] > 0 else 0

            if gp_margin > 0.50: gp_score = 6; gp_desc = f"高毛利({gp_margin*100:.1f}%)"
            elif gp_margin > 0.30: gp_score = 5; gp_desc = f"中高毛利({gp_margin*100:.1f}%)"
            elif gp_margin > 0.20: gp_score = 4; gp_desc = f"中等毛利({gp_margin*100:.1f}%)"
            elif gp_margin > 0.10: gp_score = 3; gp_desc = f"低毛利({gp_margin*100:.1f}%)"
            elif gp_margin > 0.05: gp_score = 2; gp_desc = f"微利({gp_margin*100:.1f}%)"
            elif gp_margin > 0: gp_score = 1; gp_desc = f"极低毛利({gp_margin*100:.1f}%)"
            else: gp_score = 0; gp_desc = "毛利为负"

            # 净利率修正
            if np_margin < 0:
                gp_score = max(0, gp_score - 2)
                gp_desc += "[净利率为负，扣2分]"
        else:
            gp_score = 3; gp_desc = "数据不足"

        total += gp_score
        details["毛利率"] = {"得分": gp_score, "说明": gp_desc}

        return min(total, 30), details

    except Exception as e:
        return 0, {"error": str(e)}


def score_news(sym):
    """消息面评分 (20分) - 简化版"""
    details = {}
    total = 0

    # 2.1 业绩预告 (6分)
    try:
        forecast = panda_data.get_fina_forecast(symbol=sym, fields=[])
        if forecast is not None and len(forecast) > 0:
            latest = forecast.iloc[-1]
            content = str(latest.get("forecast_content", "") or "")
            if any(k in content for k in ["预增","大幅上升","扭亏"]):
                fc_score, fc_desc = 6, "业绩预增/扭亏"
            elif any(k in content for k in ["略增","小幅上升"]):
                fc_score, fc_desc = 5, "业绩略增"
            elif any(k in content for k in ["续盈","持平"]):
                fc_score, fc_desc = 3, "业绩平稳"
            elif any(k in content for k in ["略减","小幅下降"]):
                fc_score, fc_desc = 2, "业绩略降"
            elif any(k in content for k in ["预减","大幅下降","预亏","首亏"]):
                fc_score, fc_desc = 0, "业绩预亏/预警"
            else:
                fc_score, fc_desc = 3, "中性"
        else:
            fc_score, fc_desc = 3, "已披露正式财报，按中性处理"
    except:
        fc_score, fc_desc = 3, "数据获取失败，按中性处理"

    total += fc_score
    details["业绩预告"] = {"得分": fc_score, "说明": fc_desc}

    # 2.2 机构调研 (4分)
    try:
        inv = panda_data.get_investor_activity(symbol=sym, fields=[])
        if inv is not None and len(inv) > 0:
            recent = inv[inv["date"] >= "20260401"] if "date" in inv.columns else inv.tail(3)
            count = len(recent) if len(recent) > 0 else 1
            # Count participants
            total_part = 0
            for _, r in recent.iterrows():
                try: total_part += float(r.get("participants", 0) or 0)
                except: pass
            avg_part = total_part / count if count > 0 else 0

            if count > 2 and avg_part > 20:
                inv_score, inv_desc = 4, f"近3月{count}次调研，均超20家机构"
            elif count > 0 and avg_part > 10:
                inv_score, inv_desc = 3, f"近3月有调研，参与机构较多"
            elif count > 0:
                inv_score, inv_desc = 2, f"有调研但参与机构较少"
            else:
                inv_score, inv_desc = 1, "近6个月无调研"
        else:
            inv_score, inv_desc = 2, "无机构调研数据"
    except:
        inv_score, inv_desc = 2, "数据获取失败"

    total += inv_score
    details["机构调研"] = {"得分": inv_score, "说明": inv_desc}

    # 2.3 研报评级 (4分)
    try:
        rec = panda_data.get_stock_recommendation_consensus(symbol=sym, fields=[])
        if rec is not None and len(rec) > 0:
            ratings = rec["rating"].tolist() if "rating" in rec.columns else []
            buy_count = sum(1 for r in ratings if "买入" in str(r) or "buy" in str(r).lower())
            hold_count = sum(1 for r in ratings if any(k in str(r) for k in ["增持","持有","hold"]))
            neutral_count = sum(1 for r in ratings if "中性" in str(r) or "neutral" in str(r).lower())

            if buy_count >= 2:
                rec_score, rec_desc = 4, f"近{len(ratings)}家券商，{buy_count}家买入"
            elif buy_count >= 1 or hold_count >= 2:
                rec_score, rec_desc = 3, f"买入/增持评级"
            elif neutral_count > 0:
                rec_score, rec_desc = 2, "中性评级为主"
            else:
                rec_score, rec_desc = 1, "研报覆盖较少"
        else:
            rec_score, rec_desc = 1, "无研报覆盖"
    except:
        rec_score, rec_desc = 1, "数据获取失败"

    total += rec_score
    details["研报评级"] = {"得分": rec_score, "说明": rec_desc}

    # 2.4 事件情绪 (6分) - 默认中性
    total += 3
    details["事件情绪"] = {"得分": 3, "说明": "默认中性（未获取实时新闻事件）"}

    return min(total, 20), details


def score_debt(sym, fina_df):
    """债务偿债评分 (15分)"""
    try:
        stock_fina = fina_df[fina_df["symbol"] == sym].copy()
        if len(stock_fina) == 0:
            return 0, {"error": "无数据"}

        stock_fina = stock_fina.drop_duplicates(subset=["quarter"])
        latest = stock_fina.sort_values("quarter").iloc[-1]

        ta = float(latest.get("bs_total_assets", 0) or 0)
        tl = float(latest.get("bs_total_liab", 0) or 0)
        tca = float(latest.get("bs_total_cur_assets", 0) or 0)
        tcl = float(latest.get("bs_total_cur_liab", 0) or 0)
        inv = float(latest.get("bs_inventory", 0) or 0)
        st_borr = float(latest.get("bs_st_borr", 0) or 0)
        lt_borr = float(latest.get("bs_lt_borr", 0) or 0)

        details = {}
        total = 0

        # 4.1 资产负债率 (5分)
        debt_ratio = tl / ta if ta > 0 else 0
        if debt_ratio < 0.30: dr_score = 5; dr_desc = f"低负债({debt_ratio*100:.1f}%)"
        elif debt_ratio < 0.45: dr_score = 4; dr_desc = f"健康水平({debt_ratio*100:.1f}%)"
        elif debt_ratio < 0.60: dr_score = 3; dr_desc = f"中等水平({debt_ratio*100:.1f}%)"
        elif debt_ratio < 0.70: dr_score = 2; dr_desc = f"偏高({debt_ratio*100:.1f}%)"
        elif debt_ratio < 0.85: dr_score = 1; dr_desc = f"高负债({debt_ratio*100:.1f}%)"
        else: dr_score = 0; dr_desc = f"极高负债({debt_ratio*100:.1f}%)"

        total += dr_score
        details["资产负债率"] = {"得分": dr_score, "说明": dr_desc}

        # 4.2 流动/速动比率 (4分)
        cr = tca / tcl if tcl > 0 else 99
        qr = (tca - inv) / tcl if tcl > 0 else 99
        if cr > 2 and qr > 1: cr_score = 4; cr_desc = f"流动{cr:.2f}速动{qr:.2f}，偿债能力优秀"
        elif cr > 1.5 and qr > 0.8: cr_score = 3; cr_desc = f"流动{cr:.2f}速动{qr:.2f}"
        elif cr > 1 and qr > 0.5: cr_score = 2; cr_desc = f"流动{cr:.2f}速动{qr:.2f}"
        elif cr > 0.5 and qr > 0.2: cr_score = 1; cr_desc = f"流动{cr:.2f}速动{qr:.2f}"
        else: cr_score = 0

        total += cr_score
        details["流动/速动比率"] = {"得分": cr_score, "说明": cr_desc}

        # 4.3 质押 (3分) - 中性处理
        try:
            pledge = panda_data.get_stock_pledge_stat(symbol=sym, fields=[])
            if pledge is not None and len(pledge) > 0:
                pr = float(pledge.iloc[-1].get("pledge_ratio", 0) or 0)
            else:
                pr = 0
        except:
            pr = 0

        if pr < 0.10: pl_score = 3; pl_desc = f"低质押({pr*100:.1f}%)"
        elif pr < 0.30: pl_score = 2; pl_desc = f"中等质押({pr*100:.1f}%)"
        elif pr < 0.50: pl_score = 1; pl_desc = f"偏高质押({pr*100:.1f}%)"
        else: pl_score = 0; pl_desc = f"高质押({pr*100:.1f}%)"

        total += pl_score
        details["股权质押"] = {"得分": pl_score, "说明": pl_desc}

        # 4.4 有息负债率 (3分)
        int_debt = (st_borr + lt_borr) / ta if ta > 0 else 0
        if int_debt < 0.10: id_score = 3; id_desc = f"极低有息负债({int_debt*100:.1f}%)"
        elif int_debt < 0.20: id_score = 2.5; id_desc = f"低有息负债({int_debt*100:.1f}%)"
        elif int_debt < 0.30: id_score = 2
        elif int_debt < 0.40: id_score = 1.5
        elif int_debt < 0.50: id_score = 1
        else: id_score = 0

        total += id_score
        details["有息负债率"] = {"得分": id_score, "说明": id_desc}

        return min(total, 15), details

    except Exception as e:
        return 0, {"error": str(e)}


def score_shareholder(sym):
    """股东增减持评分 (15分)"""
    details = {}
    total = 0

    # 5.1 大股东增减持 (6分)
    try:
        sh = panda_data.get_stock_shareholder_change(symbol=sym, fields=[])
        if sh is not None and len(sh) > 0:
            plans = sh["plan_type"].tolist() if "plan_type" in sh.columns else []
            inc = sum(1 for p in plans if "增" in str(p))
            dec = sum(1 for p in plans if "减" in str(p))
            if inc > 0 and dec == 0:
                sh_score, sh_desc = 6, "大股东增持计划"
            elif inc > 0 and dec > 0:
                sh_score, sh_desc = 3, "增减持并存，中性"
            elif dec > 0:
                sh_score, sh_desc = 1, "存在减持计划"
            else:
                sh_score, sh_desc = 3, "无明显增减持计划"
        else:
            sh_score, sh_desc = 3, "无增减持数据"
    except:
        sh_score, sh_desc = 3, "数据获取失败"

    total += sh_score
    details["大股东增减持"] = {"得分": sh_score, "说明": sh_desc}

    # 5.2 高管增减持 (3分) - 默认中性
    total += 2
    details["高管增减持"] = {"得分": 2, "说明": "默认无显著变动"}

    # 5.3 回购 (3分)
    try:
        rep = panda_data.get_repurchase(symbol=sym, fields=[])
        if rep is not None and len(rep) > 0:
            latest = rep.iloc[-1]
            amount = float(latest.get("repo_amount", 0) or 0)
            if amount > 5e8:  # >5亿
                rep_score, rep_desc = 3, f"大额回购({amount/1e8:.1f}亿)"
            elif amount > 0:
                rep_score, rep_desc = 2, f"回购实施中({amount/1e8:.2f}亿)"
            else:
                rep_score, rep_desc = 1.5, "有回购预案"
        else:
            rep_score, rep_desc = 1.5, "无回购计划"
    except:
        rep_score, rep_desc = 1.5, "数据获取失败"

    total += rep_score
    details["回购计划"] = {"得分": rep_score, "说明": rep_desc}

    # 5.4 限售解禁 (3分)
    try:
        rest = panda_data.get_restricted_list(symbol=sym, fields=[])
        if rest is not None and len(rest) > 0:
            dates = rest["list_date"].tolist() if "list_date" in rest.columns else []
            future = [d for d in dates if str(d) > "20260706"]
            if len(future) == 0:
                rest_score, rest_desc = 3, "未来无解禁"
            elif len(future) <= 2:
                rest_score, rest_desc = 2.5, f"未来有{len(future)}笔解禁，规模较小"
            else:
                rest_score, rest_desc = 1, f"未来有{len(future)}笔解禁"
        else:
            rest_score, rest_desc = 3, "无限售解禁数据"
    except:
        rest_score, rest_desc = 3, "数据获取失败"

    total += rest_score
    details["限售解禁"] = {"得分": rest_score, "说明": rest_desc}

    return min(total, 15), details


# ========== 5. 执行评分 ==========
print("\nSTEP 4: 逐股五维评分...\n")

results = []
STOCK_NAMES = {s["symbol"]: s["name"] for s in top50}

for i, s in enumerate(top50):
    sym = s["symbol"]
    name = s["name"]
    mcap = s["mcap"]

    print(f"  [{i+1}/50] {name}({sym}) 流通市值{mcap:.1f}亿")

    # 维度一：财务状况 (30分)
    fin_score, fin_detail = score_finance(sym, fina_all)
    print(f"    财务状况: {fin_score:.1f}/30")

    # 维度二：消息面 (20分)
    news_score, news_detail = score_news(sym)
    print(f"    消息面: {news_score:.1f}/20")

    # 维度四：债务 (15分)
    debt_score, debt_detail = score_debt(sym, fina_all)
    print(f"    债务偿债: {debt_score:.1f}/15")

    # 维度五：增减持 (15分)
    sh_score, sh_detail = score_shareholder(sym)
    print(f"    增减持: {sh_score:.1f}/15")

    # 维度三：行业 (20分) - 同行业统一
    ind_score = industry_total

    total_score = fin_score + news_score + ind_score + debt_score + sh_score

    # 等级
    if total_score >= 85: grade = "A+"; stars = "★★★★★"
    elif total_score >= 70: grade = "A"; stars = "★★★★"
    elif total_score >= 55: grade = "B+"; stars = "★★★"
    elif total_score >= 40: grade = "B"; stars = "★★"
    else: grade = "C"; stars = "★"

    results.append({
        "rank": i + 1,
        "symbol": sym,
        "name": name,
        "mcap": mcap,
        "finance": round(fin_score, 1),
        "news": round(news_score, 1),
        "industry": round(ind_score, 1),
        "debt": round(debt_score, 1),
        "shareholder": round(sh_score, 1),
        "total": round(total_score, 1),
        "grade": grade,
        "stars": stars,
        "fin_detail": fin_detail,
        "news_detail": news_detail,
        "debt_detail": debt_detail,
        "sh_detail": sh_detail
    })

    print(f"    ⭐ 总分: {total_score:.1f}/100 → {stars} {grade}")
    print()

# ========== 6. 按总分排序并输出TOP10 ==========
results.sort(key=lambda x: x["total"], reverse=True)

print("=" * 60)
print("🏆 半导体行业基本面评分 TOP10")
print("=" * 60)
print(f"评分日期: 2026-07-06")
print(f"行业评分: {industry_total:.1f}/20（所有股票同行业评分）")
print(f"{'排名':>4} {'股票名称':>8} {'代码':>10} {'总分':>6} {'财务':>6} {'消息':>6} {'行业':>6} {'债务':>6} {'增减持':>6} {'等级':>6}")
print("-" * 70)
for i, r in enumerate(results[:10], 1):
    print(f"{i:4d} {r['name']:>8} {r['symbol']:>10} {r['total']:6.1f} {r['finance']:6.1f} {r['news']:6.1f} {r['industry']:6.1f} {r['debt']:6.1f} {r['shareholder']:6.1f} {r['stars']:>6}")

# 输出详细报告
print("\n" + "=" * 60)
print("📊 详细评分报告")
print("=" * 60)

for i, r in enumerate(results[:10], 1):
    print(f"\n{'─' * 50}")
    print(f"#{i} {r['name']}({r['symbol']}) | 总分 {r['total']}/100 | {r['stars']} {r['grade']}")
    print(f"   流通市值: {r['mcap']:.1f}亿")
    print(f"   财务状况: {r['finance']}/30分")
    fd = r.get("fin_detail", {})
    if not isinstance(fd, dict): fd = {}
    if "error" in fd:
        print(f"      ⚠️ {fd['error']}")
    else:
        for k, v in fd.items():
            if isinstance(v, dict) and "得分" in v:
                print(f"      {k}: {v['得分']}分 - {v.get('说明','')}")
    print(f"   消息面: {r['news']}/20分")
    nd = r.get("news_detail", {})
    if isinstance(nd, dict):
        for k, v in nd.items():
            if isinstance(v, dict) and "得分" in v:
                print(f"      {k}: {v['得分']}分 - {v.get('说明','')}")
    print(f"   行业前景: {r['industry']}/20分")
    for k, v in industry_detail.items():
        print(f"      {k}: {v['得分']}分 - {v['说明']}")
    print(f"   债务偿债: {r['debt']}/15分")
    dd = r.get("debt_detail", {})
    if isinstance(dd, dict):
        for k, v in dd.items():
            if isinstance(v, dict) and "得分" in v:
                print(f"      {k}: {v['得分']}分 - {v.get('说明','')}")
    print(f"   增减持: {r['shareholder']}/15分")
    sd = r.get("sh_detail", {})
    if isinstance(sd, dict):
        for k, v in sd.items():
            if isinstance(v, dict) and "得分" in v:
                print(f"      {k}: {v['得分']}分 - {v.get('说明','')}")

# ========== 输出JSON结果 ==========
top10_output = []
for i, r in enumerate(results[:10], 1):
    top10_output.append({
        "排名": i, "名称": r["name"], "代码": r["symbol"],
        "总分": r["total"], "财务状况": r["finance"],
        "消息面": r["news"], "行业前景": r["industry"],
        "债务偿债": r["debt"], "增减持": r["shareholder"],
        "等级": f"{r['stars']} {r['grade']}",
        "流通市值(亿)": r["mcap"]
    })

print("\n\n=== JSON_OUTPUT ===")
print(json.dumps(top10_output, ensure_ascii=False, indent=2))
print("=== END ===")
