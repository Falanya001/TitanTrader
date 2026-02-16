import flet as ft
import os
import json
import sqlite3
from datetime import datetime

# --- 1. FILE SYSTEM SAFEGUARD ---
try:
    INTERNAL_DIR = os.environ.get("FLET_APP_STORAGE_DATA", os.getcwd())
except:
    INTERNAL_DIR = ""

DB_PATH = os.path.join(INTERNAL_DIR, 'market_data.db')
USER_PF = os.path.join(INTERNAL_DIR, 'user_portfolio.json')

# --- 2. LAZY IMPORTS ---
pd = None
ta = None
yf = None

def lazy_load():
    global pd, ta, yf
    if pd is None:
        import pandas as pd
        import pandas_ta as ta
        import yfinance as yf
        # Disable cache to avoid permission crashes
        yf.set_tz_cache_location(os.path.join(INTERNAL_DIR, "yf_cache"))

# --- 3. DATA LOGIC ---
def load_json(filename):
    if not os.path.exists(filename):
        return {"cash": 1000000, "equity": 1000000, "holdings": {}, "history": []}
    with open(filename, 'r') as f: return json.load(f)

def save_json(data, filename):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

TICKERS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", 
           "ITC.NS", "SBIN.NS", "TATAMOTORS.NS", "TRENT.NS", "ZOMATO.NS"]

def fetch_data():
    lazy_load()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS daily_prices (ticker TEXT PRIMARY KEY, close REAL, roc REAL, rsi REAL)')
    
    for t in TICKERS:
        try:
            df = yf.download(t, period="3mo", progress=False)
            if not df.empty:
                close = float(df['Close'].iloc[-1])
                roc = float(ta.roc(df['Close'], length=20).iloc[-1])
                rsi = float(ta.rsi(df['Close'], length=14).iloc[-1])
                conn.execute('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?)', (t, close, roc, rsi))
        except: continue
    conn.commit()
    conn.close()

def get_scan():
    lazy_load()
    conn = sqlite3.connect(DB_PATH)
    results = []
    try:
        cursor = conn.execute("SELECT ticker, close, roc, rsi FROM daily_prices")
        for row in cursor:
            # Simple Logic: Positive Momentum + Not Overbought
            if row[2] > 0 and row[3] < 70:
                results.append({"ticker": row[0], "price": row[1], "roc": row[2]})
    except: pass
    conn.close()
    return sorted(results, key=lambda x: x['roc'], reverse=True)

# --- 4. THE UI (Bare Metal) ---
def main(page: ft.Page):
    page.title = "Titan V3"
    page.scroll = "auto"
    
    # State
    user_pf = load_json(USER_PF)

    # --- WIDGETS ---
    txt_status = ft.Text("Ready")
    txt_equity = ft.Text(f"Net Worth: {user_pf['equity']}", size=20, weight="bold")
    txt_cash = ft.Text(f"Cash: {user_pf['cash']}", color="green")
    
    # ACTIONS
    def run_sync(e):
        txt_status.value = "Syncing... (Wait 10s)"
        page.update()
        try:
            fetch_data()
            txt_status.value = "Sync Complete!"
        except Exception as err:
            txt_status.value = f"Error: {err}"
        page.update()

    def run_buy(ticker, price):
        qty = int((user_pf['cash'] * 0.1) / price)
        if qty > 0:
            user_pf['cash'] -= (qty * price)
            if ticker in user_pf['holdings']:
                user_pf['holdings'][ticker]['qty'] += qty
            else:
                user_pf['holdings'][ticker] = {"qty": qty, "entry_price": price}
            
            save_json(user_pf, USER_PF)
            txt_equity.value = f"Net Worth: {user_pf['equity']}"
            txt_cash.value = f"Cash: {user_pf['cash']}"
            txt_status.value = f"Bought {qty} {ticker}"
            page.update()

    # TABS CONTENT
    def get_dashboard():
        return ft.Column([
            ft.Text("DASHBOARD", size=20),
            ft.Divider(),
            txt_equity,
            txt_cash,
            ft.Divider(),
            ft.ElevatedButton("Sync Data", on_click=run_sync),
            txt_status
        ])

    def get_scanner():
        # Dynamic content loader
        items = []
        results = get_scan()
        if not results:
            items.append(ft.Text("No Data. Click Sync on Home."))
        else:
            for r in results:
                items.append(
                    ft.Row([
                        ft.Text(f"{r['ticker']} ({r['price']:.0f})"),
                        ft.ElevatedButton("BUY", on_click=lambda e, t=r['ticker'], p=r['price']: run_buy(t, p))
                    ], alignment="spaceBetween")
                )
        return ft.Column([ft.Text("SCANNER"), ft.Divider()] + items)

    def get_portfolio():
        items = []
        if not user_pf['holdings']:
            items.append(ft.Text("Empty Portfolio"))
        else:
            for t, pos in user_pf['holdings'].items():
                items.append(ft.Text(f"{t}: {pos['qty']} units"))
        
        # Refresh button logic is simple: just re-render
        return ft.Column([
            ft.Text("PORTFOLIO"), 
            ft.Divider(),
            ft.ElevatedButton("Refresh View", on_click=lambda e: page.update()), 
            ft.Column(items)
        ])

    # NAVIGATION
    # Using 'content' in Tabs is safer than switching views manually
    t = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="Home", icon="home", content=get_dashboard()),
            ft.Tab(text="Scan", icon="search", content=get_scanner()),
            ft.Tab(text="Port", icon="list", content=get_portfolio()),
        ],
        expand=True
    )

    page.add(t)

ft.app(target=main)
