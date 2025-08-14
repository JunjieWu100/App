from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import os
import random

app = FastAPI()

# === GAME STATE ===
players = ["You", "Competitor A", "Competitor B"]
markets = {
    "NA": {"base_demand": 100_000},
    "EU": {"base_demand": 80_000},
    "APAC": {"base_demand": 120_000}
}
prod_cost = 200
state = {p: {"quality": 50, "capacity": 200_000, "cash": 10_000_000, "cumul_profit": 0} for p in players}
current_round = 1
last_results = {}
last_detailed_results = None
history = {"rounds": [], "market_share": {p: [] for p in players}, "svi": {p: [] for p in players}}
round_history = []


# === HELPER: AI DECISIONS ===
def ai_decisions(name):
    return {
        "NA Price": random.randint(550, 650),
        "EU Price": random.randint(550, 650),
        "APAC Price": random.randint(550, 650),
        "NA Mkt": random.randint(2, 6),
        "EU Mkt": random.randint(2, 6),
        "APAC Mkt": random.randint(2, 6),
        "R&D": random.randint(5, 10),
        "HR": random.randint(3, 7),
        "Alloc": {
            "NA": random.randint(50_000, 80_000),
            "EU": random.randint(40_000, 70_000),
            "APAC": random.randint(60_000, 90_000)
        }
    }


# === ROUTES ===
@app.get("/", response_class=HTMLResponse)
def form_page():
    html = open("templates/form.html").read()
    return html


@app.post("/submit-ajax")
def submit_ajax(
    na_price: int = Form(...),
    eu_price: int = Form(...),
    apac_price: int = Form(...),
    na_mkt: float = Form(...),
    eu_mkt: float = Form(...),
    apac_mkt: float = Form(...),
    rd: float = Form(...),
    hr: float = Form(...),
    na_alloc: int = Form(...),
    eu_alloc: int = Form(...),
    apac_alloc: int = Form(...)
):
    global current_round, last_results, last_detailed_results, round_history

    # Gather decisions
    decisions = {
        "You": {
            "NA Price": na_price, "EU Price": eu_price, "APAC Price": apac_price,
            "NA Mkt": na_mkt, "EU Mkt": eu_mkt, "APAC Mkt": apac_mkt,
            "R&D": rd, "HR": hr,
            "Alloc": {"NA": na_alloc, "EU": eu_alloc, "APAC": apac_alloc}
        },
        "Competitor A": ai_decisions("Competitor A"),
        "Competitor B": ai_decisions("Competitor B")
    }

    # Update qualities
    for p in players:
        state[p]["quality"] += decisions[p]["R&D"] * 0.5

    market_results = {m: {} for m in markets}
    avg_market_share = {p: 0 for p in players}
    detailed = {p: {"regions": {}, "costs": {}} for p in players}

    for region, params in markets.items():
        min_price = min(decisions[p][f"{region} Price"] for p in players)
        max_mkt = max(decisions[p][f"{region} Mkt"] for p in players)
        max_quality = max(state[p]["quality"] for p in players)

        attractiveness = {}
        for p in players:
            price_score = (min_price / decisions[p][f"{region} Price"]) * 100
            mkt_score = (decisions[p][f"{region} Mkt"] / max_mkt) * 100 if max_mkt else 0
            qual_score = (state[p]["quality"] / max_quality) * 100 if max_quality else 0
            attractiveness[p] = (price_score * 0.4) + (mkt_score * 0.3) + (qual_score * 0.3)

        total_attr = sum(attractiveness.values())
        for p in players:
            share = attractiveness[p] / total_attr
            demand = params["base_demand"] * share
            sold = min(demand, decisions[p]["Alloc"][region])
            price = decisions[p][f"{region} Price"]
            revenue = sold * price
            market_results[region][p] = {"share": share, "sold": sold, "revenue": revenue}
            avg_market_share[p] += share
            detailed[p]["regions"][region] = {
                "sold": int(sold),
                "price": price,
                "share": round(share * 100, 2),
                "revenue": revenue
            }

    results = {}
    for p in players:
        total_revenue = sum(market_results[reg][p]["revenue"] for reg in markets)
        total_mkt_cost = sum(decisions[p][f"{reg} Mkt"] for reg in markets) * 1_000_000
        prod_costs = state[p]["capacity"] * prod_cost
        rd_costs = decisions[p]["R&D"] * 1_000_000
        hr_costs = decisions[p]["HR"] * 1_000_000
        total_costs = prod_costs + total_mkt_cost + rd_costs + hr_costs
        profit = total_revenue - total_costs
        state[p]["cash"] += profit
        state[p]["cumul_profit"] += profit
        avg_share = avg_market_share[p] / len(markets)
        svi = (state[p]["cumul_profit"] / 1_000_000) + (avg_share * 100) + (state[p]["cash"] / 1_000_000)

        results[p] = {
            "Revenue": total_revenue, "Profit": profit, "Cash": state[p]["cash"], "SVI": svi, "Share": avg_share
        }

        detailed[p]["costs"] = {
            "production": prod_costs,
            "marketing": total_mkt_cost,
            "r&d": rd_costs,
            "hr": hr_costs,
            "total": total_costs
        }

    # Save trends & history
    history["rounds"].append(current_round)
    for p in players:
        history["market_share"][p].append(results[p]["Share"] * 100)
        history["svi"][p].append(results[p]["SVI"])

    last_results = results
    last_detailed_results = detailed
    round_history.append({"round": current_round, "decisions": decisions, "results": results, "detailed": detailed})

    current_round += 1
    return JSONResponse({"results": results, "history": history})


@app.get("/chart-data")
def get_chart_data():
    return JSONResponse(history)


@app.get("/full-report", response_class=HTMLResponse)
def full_report():
    html = open("templates/full_report.html").read()
    region_rows = ""
    cost_rows = ""
    chart_data_js = "const chartData = { companies: [], data: {} };"

    for p, pdata in last_detailed_results.items():
        for region, rdata in pdata["regions"].items():
            region_rows += f"<tr><td>{p}</td><td>{region}</td><td>{rdata['sold']}</td><td>{rdata['price']}</td><td>{rdata['share']}%</td><td>${rdata['revenue']/1_000_000:.2f}M</td></tr>"

        c = pdata["costs"]
        cost_rows += f"<tr><td>{p}</td><td>${c['production']/1_000_000:.2f}M</td><td>${c['marketing']/1_000_000:.2f}M</td><td>${c['r&d']/1_000_000:.2f}M</td><td>${c['hr']/1_000_000:.2f}M</td><td>${c['total']/1_000_000:.2f}M</td></tr>"
        total_revenue = sum(r["revenue"] for r in pdata["regions"].values())
        profit = total_revenue - c["total"]
        chart_data_js += f"""
chartData.companies.push("{p}");
chartData.data["{p}"] = {{
    revenue: {total_revenue},
    production: {c['production']},
    marketing: {c['marketing']},
    rd: {c['r&d']},
    hr: {c['hr']},
    profit: {profit}
}};
"""

    return html.replace("{{region_rows}}", region_rows).replace("{{cost_rows}}", cost_rows).replace("{{chart_data_js}}", chart_data_js)


@app.get("/history", response_class=HTMLResponse)
def history_page():
    html = open("templates/history.html").read()
    rows_html = ""
    for entry in round_history:
        r = entry["results"]
        d = entry["decisions"]
        for company in players:
            rows_html += f"""
<tr>
    <td>{entry['round']}</td>
    <td>{company}</td>
    <td>{d[company]['NA Price']}</td>
    <td>{d[company]['EU Price']}</td>
    <td>{d[company]['APAC Price']}</td>
    <td>{d[company]['NA Mkt']}</td>
    <td>{d[company]['EU Mkt']}</td>
    <td>{d[company]['APAC Mkt']}</td>
    <td>{d[company]['R&D']}</td>
    <td>{d[company]['HR']}</td>
    <td>{d[company]['Alloc']['NA']}</td>
    <td>{d[company]['Alloc']['EU']}</td>
    <td>{d[company]['Alloc']['APAC']}</td>
    <td>${r[company]['Revenue']/1_000_000:.2f}M</td>
    <td>${r[company]['Profit']/1_000_000:.2f}M</td>
    <td>${r[company]['Cash']/1_000_000:.2f}M</td>
    <td>{r[company]['SVI']:.2f}</td>
    <td>{r[company]['Share']*100:.1f}%</td>
</tr>
"""
    return html.replace("{{rows}}", rows_html)
