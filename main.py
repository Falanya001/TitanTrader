import flet as ft
import os
import json
import sqlite3
import traceback # To catch the exact error

# --- 1. SETUP PATHS (Do not run logic here, just define paths) ---
try:
    # Android storage path
    INTERNAL_DIR = os.environ.get("FLET_APP_STORAGE_DATA", os.getcwd())
except:
    INTERNAL_DIR = ""

DB_PATH = os.path.join(INTERNAL_DIR, 'market_data.db')
USER_PF = os.path.join(INTERNAL_DIR, 'user_portfolio.json')

# --- 2. GLOBAL STATE ---
# We keep these empty to start. We load them only when needed.
pd = None
ta = None
yf = None

def lazy_load():
    """Imports heavy libraries only when buttons are clicked"""
    global pd, ta, yf
    if pd is None:
        import pandas as pd
        import pandas_ta as ta
        import yfinance as yf
        # Disable cache to avoid Android permission errors
        yf.set_tz_cache_location(os.path.join(INTERNAL_DIR, "yf_cache"))

# --- 3. DATA FUNCTIONS ---
def get_default_portfolio():
    return {"cash": 1000000, "equity": 1000000, "holdings": {}, "history": []}

def load_portfolio_safe():
    try:
        if not os.path.exists(USER_PF):
            return get_default_portfolio()
        with open(USER_PF, 'r') as f:
            return json.load(f)
    except Exception as e:
        return get_default_portfolio() # Fail safe

def save_portfolio_safe(data):
    try:
        with open(USER_PF, 'w') as f:
            json.dump(data, f, indent=4)
    except:
        pass # Ignore save errors for now to keep app alive

# --- 4. THE UI ---
def main(page: ft.Page):
    # CRITICAL: Set these first to ensure the window appears
    page.title = "Titan Debugger"
    page.scroll = "auto"
    page.theme_mode = "dark"
    
    # Text Log to show us what is happening
    log_view = ft.Column()
    
    def log(msg, color="white"):
        log_view.controls.append(ft.Text(f"{msg}", color=color))
        page.update()

    # --- UI WRAPPER ---
    try:
        log("App Started...", "green")
        log(f"Storage Path: {INTERNAL_DIR}", "grey")

        # 1. Load Portfolio
        user_pf = load_portfolio_safe()
        log("Portfolio Loaded.", "green")

        # 2. Define UI Elements (Simple strings only)
        txt_equity = ft.Text(f"Net Worth: {user_pf['equity']}", size=24, weight="bold")
        txt_cash = ft.Text(f"Cash: {user_pf['cash']}", color="green")

        # 3. Define Actions
        def run_sync(e):
            log("Sync Started...", "yellow")
            try:
                lazy_load() # Import heavy stuff now
                log("Libraries Imported.", "blue")
                
                # Fetch Data
                conn = sqlite3.connect(DB_PATH)
                conn.execute('CREATE TABLE IF NOT EXISTS daily_prices (ticker TEXT PRIMARY KEY, close REAL, roc REAL)')
                
                tickers = ["RELIANCE.NS", "TCS.NS", "SBIN.NS", "TATAMOTORS.NS"]
                for t in tickers:
                    try:
                        log(f"Fetching {t}...", "grey")
                        df = yf.download(t, period="1mo", progress=False)
                        if not df.empty:
                            close = float(df['Close'].iloc[-1])
                            roc = float(ta.roc(df['Close'], length=10).iloc[-1])
                            conn.execute('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?)', (t, close, roc))
                    except Exception as ex:
                        log(f"Skip {t}: {ex}", "red")
                
                conn.commit()
                conn.close()
                log("Sync Complete!", "green")
                
            except Exception as err:
                log(f"SYNC ERROR: {err}", "red")
                # Print full error for debugging
                log(traceback.format_exc(), "red")

        def run_scan(e):
            log("Scanning...", "yellow")
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.execute("SELECT ticker, close, roc FROM daily_prices")
                found = False
                for row in cursor:
                    if row[2] > 0: # Positive Momentum
                        found = True
                        log(f"BUY: {row[0]} (ROC: {row[2]:.1f})", "green")
                if not found:
                    log("No signals found.", "grey")
                conn.close()
            except:
                log("Scan failed (Try Sync first)", "red")

        # 4. Build Layout
        # We use a simple Column instead of Tabs to ensure it renders 100%
        page.add(
            ft.Column([
                ft.Text("TITAN PRO (SAFE MODE)", size=20, weight="bold"),
                ft.Divider(),
                txt_equity,
                txt_cash,
                ft.Divider(),
                ft.Row([
                    ft.ElevatedButton("SYNC DATA", on_click=run_sync),
                    ft.ElevatedButton("SCAN", on_click=run_scan),
                ]),
                ft.Divider(),
                ft.Text("SYSTEM LOG:", size=16),
                log_view
            ])
        )
        
        log("UI Rendered Successfully.", "green")

    except Exception as e:
        # THE SAFETY NET
        page.add(ft.Text(f"CRITICAL CRASH: {e}", color="red", size=30))
        page.add(ft.Text(traceback.format_exc(), color="red"))

ft.app(target=main)
