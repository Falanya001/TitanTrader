import flet as ft
import os
import json
import sqlite3
import traceback

# --- 1. SAFE PATHS ---
try:
    INTERNAL_DIR = os.environ.get("FLET_APP_STORAGE_DATA", os.getcwd())
except:
    INTERNAL_DIR = ""

DB_PATH = os.path.join(INTERNAL_DIR, 'market_data.db')
USER_PF = os.path.join(INTERNAL_DIR, 'user_portfolio.json')

# --- 2. LAZY LOAD ---
pd = None
ta = None
yf = None

def lazy_load():
    global pd, ta, yf
    if pd is None:
        import pandas as pd
        import pandas_ta as ta
        import yfinance as yf
        yf.set_tz_cache_location(os.path.join(INTERNAL_DIR, "yf_cache"))

# --- 3. DATA LOGIC ---
def load_pf():
    if not os.path.exists(USER_PF):
        return {"cash": 1000000.0, "equity": 1000000.0, "holdings": {}}
    with open(USER_PF, 'r') as f: return json.load(f)

def save_pf(data):
    with open(USER_PF, 'w') as f: json.dump(data, f, indent=4)

TICKERS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ITC.NS", 
           "SBIN.NS", "TATAMOTORS.NS", "TRENT.NS", "ZOMATO.NS", "TITAN.NS"]

def fetch_data(status_txt, page):
    lazy_load()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS daily_prices (ticker TEXT PRIMARY KEY, close REAL, roc REAL, rsi REAL)')
    
    total = len(TICKERS)
    for i, t in enumerate(TICKERS):
        try:
            status_txt.value = f"Fetching {i+1}/{total}: {t}"
            page.update()
            
            df = yf.download(t, period="3mo", progress=False)
            if df.empty: continue

            # FORCE FLATTEN COLUMNS (Prevents crash)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            close = float(df['Close'].iloc[-1])
            roc = float(ta.roc(df['Close'], length=20).iloc[-1])
            rsi = float(ta.rsi(df['Close'], length=14).iloc[-1])
            
            conn.execute('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?)', (t, close, roc, rsi))
        except: continue
    
    conn.commit()
    conn.close()
    status_txt.value = "Sync Complete."
    page.update()

def get_scan():
    lazy_load()
    conn = sqlite3.connect(DB_PATH)
    results = []
    try:
        cursor = conn.execute("SELECT ticker, close, roc, rsi FROM daily_prices")
        for row in cursor:
            if row[2] > 0 and row[3] < 70:
                results.append({"ticker": row[0], "price": row[1], "roc": row[2]})
    except: pass
    conn.close()
    return sorted(results, key=lambda x: x['roc'], reverse=True)

# --- 4. THE UI (PRIMITIVES ONLY) ---
def main(page: ft.Page):
    page.title = "Titan Tank"
    page.theme_mode = "dark"
    page.padding = 10
    
    try:
        user_pf = load_pf()

        # VARS
        txt_equity = ft.Text(f"NET: {user_pf['equity']:,.0f}", size=20, weight="bold")
        txt_cash = ft.Text(f"CASH: {user_pf['cash']:,.0f}", color="green")
        txt_status = ft.Text("Ready")
        
        # MAIN CONTAINER
        content_area = ft.Column(expand=True, scroll="auto")

        # ACTIONS
        def run_sync(e):
            try:
                fetch_data(txt_status, page)
            except Exception as err:
                txt_status.value = f"Err: {str(err)}"
                page.update()

        def run_buy(ticker, price):
            qty = int((user_pf['cash'] * 0.1) / price)
            if qty > 0:
                user_pf['cash'] -= (qty * price)
                if ticker in user_pf['holdings']:
                    user_pf['holdings'][ticker]['qty'] += qty
                else:
                    user_pf['holdings'][ticker] = {"qty": qty, "entry_price": price}
                
                # Simple Equity Update
                user_pf['equity'] = user_pf['cash'] 
                for h_t, h_pos in user_pf['holdings'].items():
                    user_pf['equity'] += h_pos['qty'] * h_pos['entry_price']

                save_pf(user_pf)
                txt_equity.value = f"NET: {user_pf['equity']:,.0f}"
                txt_cash.value = f"CASH: {user_pf['cash']:,.0f}"
                txt_status.value = f"Bought {qty} {ticker}"
                page.update()

        # VIEW CHANGERS
        def go_home(e=None):
            content_area.controls = [
                ft.Container(
                    content=ft.Column([txt_equity, txt_cash]),
                    padding=20, bgcolor="#222222"
                ),
                ft.Divider(),
                ft.ElevatedButton("SYNC MARKET DATA", on_click=run_sync),
                ft.Divider(),
                txt_status
            ]
            page.update()

        def go_scan(e=None):
            results = get_scan()
            rows = []
            if not results:
                rows.append(ft.Text("No Data. Sync First."))
            else:
                for r in results:
                    rows.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Column([ft.Text(r['ticker']), ft.Text(f"{r['price']:.0f}")]),
                                ft.ElevatedButton("BUY", on_click=lambda e, t=r['ticker'], p=r['price']: run_buy(t, p))
                            ], alignment="spaceBetween"),
                            padding=10, bgcolor="#222222"
                        )
                    )
            content_area.controls = [ft.ElevatedButton("REFRESH", on_click=go_scan)] + rows
            page.update()

        def go_port(e=None):
            rows = []
            if not user_pf['holdings']:
                rows.append(ft.Text("Empty"))
            else:
                for t, pos in user_pf['holdings'].items():
                    rows.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Column([ft.Text(t), ft.Text(f"Avg: {pos['entry_price']:.0f}")]),
                                ft.Text(f"{pos['qty']}")
                            ], alignment="spaceBetween"),
                            padding=10, bgcolor="#222222"
                        )
                    )
            content_area.controls = [ft.ElevatedButton("REFRESH", on_click=go_port)] + rows
            page.update()

        # NAVBAR (TEXT ONLY - NO ICONS)
        navbar = ft.Row([
            ft.TextButton("[ HOME ]", on_click=go_home),
            ft.TextButton("[ SCAN ]", on_click=go_scan),
            ft.TextButton("[ PORT ]", on_click=go_port),
        ], alignment="center")

        # ASSEMBLE
        page.add(
            ft.Column([
                ft.Text("TITAN PRO", size=20, weight="bold", text_align="center"),
                content_area,
                ft.Divider(),
                navbar
            ], expand=True)
        )
        
        go_home()

    except Exception as e:
        page.add(ft.Text(f"CRITICAL: {e}\n{traceback.format_exc()}", color="red"))

ft.app(target=main)
