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

# --- 2. LAZY LOAD GLOBALS ---
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

# --- 3. DATA ENGINE ---
def load_pf():
    if not os.path.exists(USER_PF):
        return {"cash": 1000000.0, "equity": 1000000.0, "holdings": {}}
    with open(USER_PF, 'r') as f: return json.load(f)

def save_pf(data):
    with open(USER_PF, 'w') as f: json.dump(data, f, indent=4)

TICKERS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", 
           "ITC.NS", "SBIN.NS", "TATAMOTORS.NS", "TRENT.NS", "ZOMATO.NS", 
           "BEL.NS", "HAL.NS", "VBL.NS", "TITAN.NS"]

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

            # --- FLATTEN COLUMNS FIX ---
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            close = float(df['Close'].iloc[-1])
            roc = float(ta.roc(df['Close'], length=20).iloc[-1])
            rsi = float(ta.rsi(df['Close'], length=14).iloc[-1])
            
            conn.execute('INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?)', (t, close, roc, rsi))
        except Exception as e:
            print(f"Skip {t}: {e}")
            continue
    
    conn.commit()
    conn.close()
    status_txt.value = "Market Data Synced."
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

# --- 4. UI BUILDER ---
def main(page: ft.Page):
    page.title = "Titan Pro V6"
    page.theme_mode = "dark"
    page.padding = 10
    
    try:
        user_pf = load_pf()

        # UI VARIABLES
        txt_equity = ft.Text(f"₹{user_pf['equity']:,.0f}", size=32, weight="bold", color="white")
        txt_cash = ft.Text(f"Cash: ₹{user_pf['cash']:,.0f}", color="green", size=16)
        txt_status = ft.Text("Ready", color="grey")
        
        # CONTAINER FOR CHANGING VIEWS
        body_container = ft.Column(expand=True, scroll="auto")

        # --- ACTIONS ---
        def run_sync(e):
            try:
                fetch_data(txt_status, page)
            except Exception as err:
                txt_status.value = f"Sync Error: {str(err)}"
                page.update()

        def run_buy(ticker, price):
            qty = int((user_pf['cash'] * 0.1) / price)
            if qty > 0:
                user_pf['cash'] -= (qty * price)
                if ticker in user_pf['holdings']:
                    user_pf['holdings'][ticker]['qty'] += qty
                else:
                    user_pf['holdings'][ticker] = {"qty": qty, "entry_price": price}
                
                user_pf['equity'] = user_pf['cash'] 
                for h_t, h_pos in user_pf['holdings'].items():
                    user_pf['equity'] += h_pos['qty'] * h_pos['entry_price']

                save_pf(user_pf)
                txt_equity.value = f"₹{user_pf['equity']:,.0f}"
                txt_cash.value = f"Cash: ₹{user_pf['cash']:,.0f}"
                txt_status.value = f"Bought {qty} {ticker}"
                page.update()

        # --- VIEW GENERATORS ---
        def show_home(e=None):
            body_container.controls = [
                ft.Container(
                    content=ft.Column([
                        ft.Text("NET WORTH", size=12, color="grey"),
                        txt_equity,
                        ft.Divider(),
                        txt_cash
                    ]),
                    padding=20, bgcolor="#1f1f1f", border_radius=15
                ),
                ft.Divider(height=20, color="transparent"),
                ft.ElevatedButton("Sync Data", icon="refresh", on_click=run_sync, height=50, width=400),
                ft.Divider(height=10, color="transparent"),
                txt_status
            ]
            page.update()

        def show_scan(e=None):
            results = get_scan()
            items = []
            if not results:
                items.append(ft.Text("No Data. Sync First."))
            else:
                for r in results:
                    items.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Column([
                                    ft.Text(r['ticker'], weight="bold", size=16),
                                    ft.Text(f"₹{r['price']:.0f}", color="grey")
                                ]),
                                ft.Row([
                                    ft.Text(f"+{r['roc']:.1f}%", color="green"),
                                    ft.IconButton(icon="add_shopping_cart", icon_color="green", 
                                                  on_click=lambda e, t=r['ticker'], p=r['price']: run_buy(t, p))
                                ])
                            ], alignment="spaceBetween"),
                            padding=15, bgcolor="#1f1f1f", border_radius=10
                        )
                    )
            
            body_container.controls = [
                ft.ElevatedButton("Run Scanner", icon="radar", on_click=show_scan),
                ft.Column(items, spacing=10)
            ]
            page.update()

        def show_port(e=None):
            items = []
            if not user_pf['holdings']:
                items.append(ft.Text("Portfolio Empty"))
            else:
                for t, pos in user_pf['holdings'].items():
                    items.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Column([ft.Text(t, weight="bold"), ft.Text(f"Avg: {pos['entry_price']:.0f}")]),
                                ft.Text(f"{pos['qty']} units", size=18, weight="bold")
                            ], alignment="spaceBetween"),
                            padding=15, bgcolor="#1f1f1f", border_radius=10
                        )
                    )
            body_container.controls = [
                ft.ElevatedButton("Refresh", icon="list", on_click=show_port),
                ft.Column(items, spacing=10)
            ]
            page.update()

        # --- MAIN LAYOUT (CUSTOM NAVBAR) ---
        # No ft.Tabs widget used here. Just a Row of Buttons.
        navbar = ft.Container(
            content=ft.Row([
                ft.IconButton(icon="home", icon_size=30, on_click=show_home),
                ft.IconButton(icon="search", icon_size=30, on_click=show_scan),
                ft.IconButton(icon="pie_chart", icon_size=30, on_click=show_port),
            ], alignment="spaceAround"),
            bgcolor="#1f1f1f",
            padding=10,
            border_radius=ft.border_radius.only(top_left=15, top_right=15)
        )

        page.add(
            ft.Column([
                ft.Text("TITAN PRO", size=20, weight="bold", text_align="center"),
                body_container, # The changing content
                navbar          # The static bottom bar
            ], expand=True)
        )

        # Init
        show_home()

    except Exception as e:
        page.add(ft.Text(f"CRITICAL ERROR: {e}\n{traceback.format_exc()}", color="red"))

ft.app(target=main)
