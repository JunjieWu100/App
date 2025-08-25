from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
import random
import socket

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

    if current_round > 4:  # cap at 4 rounds
        placements = sorted(
            [(p, state[p]["cumul_profit"]) for p in players],
            key=lambda x: x[1],
            reverse=True
        )
        return JSONResponse({"game_over": True, "placements": placements})

    # === Gather decisions ===
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

    # === Update Quality ===
    for p in players:
        if state[p]["cash"] < 0:
            continue
        growth = decisions[p]["R&D"] * (1 - state[p]["quality"] / 200)
        decay = 0.2 if decisions[p]["R&D"] == 0 else 0
        state[p]["quality"] = max(0, state[p]["quality"] + growth - decay)

    market_results = {m: {} for m in markets}
    avg_market_share = {p: 0 for p in players}
    detailed = {p: {"regions": {}, "costs": {}} for p in players}

    # === Market Simulation ===
    for region, params in markets.items():
        active_players = [p for p in players if state[p]["cash"] >= 0]
        if not active_players:
            continue

        min_price = min(decisions[p][f"{region} Price"] for p in active_players)
        max_mkt = max(decisions[p][f"{region} Mkt"] for p in active_players)
        max_quality = max(state[p]["quality"] for p in active_players)

        attractiveness = {}
        for p in active_players:
            price_score = (min_price / decisions[p][f"{region} Price"]) * 100
            mkt_score = (decisions[p][f"{region} Mkt"] / max_mkt) * 100 if max_mkt else 0
            qual_score = (state[p]["quality"] / max_quality) * 100 if max_quality else 0
            attractiveness[p] = (price_score * 0.4) + (mkt_score * 0.3) + (qual_score * 0.3)

        total_attr = sum(attractiveness.values())
        for p in active_players:
            share = attractiveness[p] / total_attr
            demand = params["base_demand"] * share
            alloc = decisions[p]["Alloc"][region]
            produced = min(alloc, state[p]["capacity"])
            sold = min(demand, produced)
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

    # === Financials ===
    results = {}
    for p in players:
        if state[p]["cash"] < 0:
            results[p] = {"Revenue": 0, "Profit": 0, "Cash": state[p]["cash"], "SVI": 0, "Share": 0}
            continue

        total_revenue = sum(market_results[reg][p]["revenue"] for reg in markets if p in market_results[reg])
        total_units = sum(market_results[reg][p]["sold"] for reg in markets if p in market_results[reg])
        prod_costs = total_units * prod_cost
        total_mkt_cost = sum(decisions[p][f"{reg} Mkt"] for reg in markets) * 1_000_000
        rd_costs = decisions[p]["R&D"] * 1_000_000
        hr_costs = decisions[p]["HR"] * 1_000_000
        total_costs = prod_costs + total_mkt_cost + rd_costs + hr_costs
        profit = total_revenue - total_costs
        state[p]["cash"] += profit
        state[p]["cumul_profit"] += profit
        avg_share = avg_market_share[p] / len(markets)
        svi = (state[p]["cumul_profit"] / 1_000_000 * 0.4) \
              + (avg_share * 100 * 0.3) \
              + (state[p]["cash"] / 1_000_000 * 0.3)

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

    # === Save Trends ===
    history["rounds"].append(current_round)
    for p in players:
        history["market_share"][p].append(results[p]["Share"] * 100)
        history["svi"][p].append(results[p]["SVI"])

    last_results = results
    last_detailed_results = detailed
    round_history.append({"round": current_round, "decisions": decisions, "results": results, "detailed": detailed})

    # === End of round check ===
    game_over = False
    placements = None
    if current_round == 4:
        game_over = True
        placements = sorted(
            [(p, results[p]["SVI"]) for p in players],
            key=lambda x: x[1],
            reverse=True
        )

    current_round += 1
    return JSONResponse({
        "results": results,
        "history": history,
        "game_over": game_over,
        "placements": placements
    })


@app.post("/reset-game")
def reset_game():
    global state, current_round, last_results, last_detailed_results, history, round_history

    state = {p: {"quality": 50, "capacity": 200_000, "cash": 10_000_000, "cumul_profit": 0} for p in players}
    current_round = 1
    last_results = {}
    last_detailed_results = None
    history = {"rounds": [], "market_share": {p: [] for p in players}, "svi": {p: [] for p in players}}
    round_history = []

    return JSONResponse({"status": "reset"})


@app.get("/rules", response_class=HTMLResponse)
def rules_page():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Game Rules</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }
            h1, h2 { color: #2c3e50; }
            ul { margin-bottom: 20px; }
            li strong { color: #34495e; }
            a { display: inline-block; margin-top: 20px; text-decoration: none; color: #2980b9; }
        </style>
    </head>
    <body>
        <h1>📖 Game Rules & Mechanics</h1>
        <p>This page explains how every number in the game affects performance and outcomes.</p>
        <h2>1. Price ($500 – $700)</h2>
        <ul>
            <li>Higher prices → higher revenue per unit sold.</li>
            <li>Lower prices → higher attractiveness and market share.</li>
            <li>Price attractiveness counts for <strong>40%</strong> of market share calculation.</li>
        </ul>
        <h2>2. Marketing (2 – 6)</h2>
        <ul>
            <li>Marketing improves visibility and customer awareness.</li>
            <li>Each point of marketing = $1M cost per region.</li>
            <li>Marketing attractiveness counts for <strong>30%</strong> of market share.</li>
        </ul>
        <h2>3. R&D (0 – 10)</h2>
        <ul>
            <li>Improves product quality (diminishing returns after quality > 100).</li>
            <li>Each point of R&D = $1M cost.</li>
            <li>If R&D = 0 → quality slowly decays each round.</li>
            <li>Quality attractiveness counts for <strong>30%</strong> of market share.</li>
        </ul>
        <h2>4. HR (0 – 10)</h2>
        <ul>
            <li>Represents investment in employees and organizational strength.</li>
            <li>Each point of HR = $1M cost.</li>
            <li>Improves long-term stability (slows down random fluctuations).</li>
        </ul>
        <h2>5. Production Allocation (30k–100k per region)</h2>
        <ul>
            <li>Units allocated to each region, capped at 200,000 total.</li>
            <li>Too few → miss sales. Too many → wasted capacity.</li>
        </ul>
        <h2>6. Market Mechanics</h2>
        <ul>
            <li>Base demand: NA 100k, EU 80k, APAC 120k.</li>
            <li>Market share = 40% price + 30% marketing + 30% quality.</li>
            <li>Sales = min(demand share, allocated units, capacity).</li>
        </ul>
        <h2>7. Costs</h2>
        <ul>
            <li>Production = units × $200</li>
            <li>Marketing = decision × $1M/region</li>
            <li>R&D = decision × $1M</li>
            <li>HR = decision × $1M</li>
        </ul>
        <h2>8. Profits & Cash</h2>
        <ul>
            <li>Revenue = sales × price</li>
            <li>Profit = revenue − costs</li>
            <li>Cash < 0 → bankruptcy</li>
        </ul>
        <h2>9. Shareholder Value Index (SVI)</h2>
        <ul>
            <li>40% cumulative profit + 30% avg. market share + 30% cash</li>
        </ul>
        <h2>10. Rounds</h2>
        <ul>
            <li>Game lasts 4 rounds, then final placements shown.</li>
        </ul>
        <a href="/">⬅ Back to Game</a>
    </body>
    </html>
    """


# === AUTOSTART WITH PYTHON ===
if __name__ == "__main__":
    import uvicorn
    port = 8000
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                s.close()
                break
            except OSError:
                port += 1
    print(f"🚀 Starting server at http://127.0.0.1:{port}")
    uvicorn.run("app:app", host="127.0.0.1", port=port, reload=True)
