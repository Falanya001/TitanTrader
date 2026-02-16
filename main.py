import flet as ft
import os
import json
import sqlite3
from datetime import datetime

# --- 1. ANDROID FILE SYSTEM SETUP (The Fix) ---
# We must find a folder where Android allows us to write files.
try:
    # This gets the internal app storage directory
    INTERNAL_DIR = os.environ.get("FLET_APP_STORAGE_DATA", os.getcwd())
except:
    INTERNAL_DIR = ""

# Define paths relative to the writable directory
DB_PATH = os.path.join(INTERNAL_DIR, 'market_data.db')
USER_PF = os.path.join(INTERNAL_DIR, 'user_portfolio.json')

# --- 2. SAFE IMPORTS (To prevent black screen crashes) ---
# We import these later to ensure the UI loads first
pd = None
ta = None
yf = None

def lazy_load_libraries():
    global pd, ta, yf
    if pd is None:
        import pandas as pd
        import pandas_ta as ta
        import yfinance as yf
        # Disable yfinance cache to prevent permission errors
        yf.set_tz_cache_location(os.path.join(INTERNAL_DIR, "yf_cache"))

# --- HELPER FUNCTIONS ---
def load_json(filename):
    if not os.path.exists(filename):
        # Default starting state
        return {"cash": 1000000, "equity": 1000000, "holdings": {}, "history": []}
    with open(filename, 'r') as f: return json.load(f)

def save_json(data, filename):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

TICKERS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "ITC.NS", 
           "SBIN.NS", "TATAMOTORS.NS", "TRENT.NS", "ZOMATO.NS"]

def fetch_fresh_data():
    lazy_load_libraries()
    conn = sqlite3.connect(DB_PATH)
    conn.execute('CREATE TABLE IF NOT EXISTS daily_prices (date TIMESTAMP, ticker TEXT, close REAL, ROC REAL, RSI REAL, PRIMARY KEY (date, ticker))')
    
    for ticker in TICKERS:
        try:
            df = yf.download(ticker, period="3mo", progress=False)
            if not df.empty:
                # Calculate Indicators immediately to save storage
                df['ROC'] = ta.roc(df['Close'], length=20)
                df['RSI'] = ta.rsi(df['Close'], length=14)
                
                curr = df.iloc[-1]
                conn.execute('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?)', 
                             (str(curr.name), ticker, float(curr['Close']), float(curr['ROC']), float(curr['RSI'])))
        except: continue
    conn.commit()
    conn.close()

def get_scan_results():
    lazy_load_libraries()
    conn = sqlite3.connect(DB_PATH)
    results = []
    try:
        cursor = conn.execute("SELECT ticker, close, ROC, RSI FROM daily_prices")
        for row in cursor:
            t, price, roc, rsi = row
            # Simple Logic: Momentum > 0 and Not Overbought
            if roc > 0 and rsi < 70:
                results.append({"ticker": t, "price": price, "roc": roc})
    except: pass
    conn.close()
    return sorted(results, key=lambda x: x['roc'], reverse=True)

# --- MAIN UI ---
def main(page: ft.Page):
    page.title = "Titan Pro V2"
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = "adaptive"
    
    # Error Catcher
    def show_error(msg):
        page.snack_bar = ft.SnackBar(ft.Text(f"Error: {msg}"), bgcolor="red")
        page.snack_bar.open = True
        page.update()

    try:
        # Load User Data
        user_pf = load_json(USER_PF)
        
        # --- VIEWS ---
        txt_equity = ft.Text(f"₹{user_pf['equity']:,.0f}", size=30, weight="bold")
        txt_cash = ft.Text(f"Cash: ₹{user_pf['cash']:,.0f}", color="green")
        
        # Action: Sync Data
        def on_sync(e):
            btn_sync.disabled = True
            btn_sync.text = "Syncing..."
            page.update()
            try:
                fetch_fresh_data()
                page.snack_bar = ft.SnackBar(ft.Text("Market Data Updated!"), bgcolor="green")
            except Exception as err:
                show_error(str(err))
            btn_sync.disabled = False
            btn_sync.text = "Sync Market Data"
            page.snack_bar.open = True
            page.update()

        btn_sync = ft.ElevatedButton("Sync Market Data", icon=ft.icons.REFRESH, on_click=on_sync)

        # Action: Buy
        def buy_stock(ticker, price):
            qty = int((user_pf['cash'] * 0.1) / price)
            if qty > 0:
                user_pf['cash'] -= (qty * price)
                if ticker in user_pf['holdings']:
                    user_pf['holdings'][ticker]['qty'] += qty
                else:
                    user_pf['holdings'][ticker] = {"qty": qty, "entry_price": price}
                save_json(user_pf, USER_PF)
                txt_equity.value = f"₹{user_pf['equity']:,.0f}" # Simplified equity update
                txt_cash.value = f"Cash: ₹{user_pf['cash']:,.0f}"
                page.update()
                page.snack_bar = ft.SnackBar(ft.Text(f"Bought {qty} {ticker}"))
                page.snack_bar.open = True
                page.update()

        # Tab 1: Dashboard
        dash_view = ft.Column([
            ft.Container(
                content=ft.Column([ft.Text("NET WORTH"), txt_equity, txt_cash]),
                padding=20, bgcolor=ft.colors.GREY_900, border_radius=10
            ),
            ft.Divider(),
            btn_sync
        ])

        # Tab 2: Scanner
        lv_scan = ft.ListView(expand=True, spacing=10)
        def load_scanner(e):
            lv_scan.controls.clear()
            results = get_scan_results()
            if not results:
                lv_scan.controls.append(ft.Text("No Data. Please Sync first."))
            else:
                for res in results:
                    lv_scan.controls.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Column([ft.Text(res['ticker'], weight="bold"), ft.Text(f"₹{res['price']:.0f}")]),
                                ft.ElevatedButton("BUY", on_click=lambda e, t=res['ticker'], p=res['price']: buy_stock(t,p))
                            ], alignment="spaceBetween"),
                            padding=10, bgcolor=ft.colors.GREY_800, border_radius=5
                        )
                    )
            page.update()

        scan_view = ft.Column([
            ft.ElevatedButton("Scan Market", on_click=load_scanner),
            lv_scan
        ])

        # Tab 3: Portfolio
        lv_port = ft.ListView(expand=True)
        def load_port(e):
            lv_port.controls.clear()
            for t, pos in user_pf['holdings'].items():
                lv_port.controls.append(ft.ListTile(title=ft.Text(t), subtitle=ft.Text(f"Qty: {pos['qty']}")))
            page.update()
            
        port_view = ft.Column([ft.ElevatedButton("Refresh", on_click=load_port), lv_port])

        # Navigation
        t = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Home", content=dash_view),
                ft.Tab(text="Scan", content=scan_view),
                ft.Tab(text="Port", content=port_view),
            ],
            expand=1
        )
        page.add(t)

    except Exception as e:
        # THE SAFETY NET: If app crashes, show why on screen
        page.add(ft.Text(f"CRITICAL ERROR: {e}", color="red", size=20))

ft.app(target=main)
