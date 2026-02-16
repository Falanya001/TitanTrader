import flet as ft
import sqlite3
import pandas as pd
import pandas_ta as ta
import json
import os
import yfinance as yf
from datetime import datetime

# --- CONFIG ---
DB_PATH = 'market_data.db'
USER_PF = 'user_portfolio.json'
BOT_PF = 'shadow_portfolio.json'
# A smaller list for mobile to keep it fast
TICKERS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "ITC.NS", 
           "SBIN.NS", "BHARTIARTL.NS", "LT.NS", "ASIANPAINT.NS", "AXISBANK.NS", 
           "MARUTI.NS", "TITAN.NS", "ADANIENT.NS", "TATASTEEL.NS", "TRENT.NS", 
           "ZOMATO.NS", "TATAMOTORS.NS"]

# --- HELPER FUNCTIONS ---
def load_json(filename):
    if not os.path.exists(filename):
        return {"cash": 1000000, "equity": 1000000, "holdings": {}, "history": []}
    with open(filename, 'r') as f: return json.load(f)

def save_json(data, filename):
    with open(filename, 'w') as f: json.dump(data, f, indent=4)

def fetch_fresh_data():
    """Updates the DB directly on the phone"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS daily_prices 
                    (date TIMESTAMP, ticker TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, 
                    PRIMARY KEY (date, ticker))''')
    
    for ticker in TICKERS:
        try:
            # Fetch last 30 days for speed
            df = yf.download(ticker, period="1mo", progress=False)
            if not df.empty:
                df.reset_index(inplace=True)
                # Fix column names if multi-index
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                # Standardize names
                df.rename(columns={'Date':'date','Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'}, inplace=True)
                
                for _, row in df.iterrows():
                    conn.execute('INSERT OR IGNORE INTO daily_prices VALUES (?,?,?,?,?,?,?)', 
                                 (row['date'], ticker, row['open'], row['high'], row['low'], row['close'], row['volume']))
        except: continue
    conn.commit()
    conn.close()

def get_scan_results():
    conn = sqlite3.connect(DB_PATH)
    results = []
    for t in TICKERS:
        try:
            query = f"SELECT * FROM daily_prices WHERE ticker='{t}' ORDER BY date DESC LIMIT 200"
            df = pd.read_sql(query, conn, parse_dates=['date']).set_index('date').sort_index()
            if len(df) < 50: continue
            
            # Indicators
            df['SMA200'] = ta.sma(df['close'], length=200)
            df['SMA50'] = ta.sma(df['close'], length=50)
            df['ROC'] = ta.roc(df['close'], length=125)
            df['RSI'] = ta.rsi(df['close'], length=14)
            df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=20)
            
            curr = df.iloc[-1]
            # Logic: Simple Trend + Momentum
            score = 0
            if curr['close'] > curr['SMA200']: score += 1
            if curr['ROC'] > 20: score += 1
            if curr['RSI'] < 70: score += 1
            
            if score >= 2: # Good candidate
                results.append({
                    "ticker": t,
                    "price": curr['close'],
                    "roc": curr['ROC'],
                    "stop": curr['close'] - (3.0 * curr['ATR'])
                })
        except: continue
    conn.close()
    return sorted(results, key=lambda x: x['roc'], reverse=True)

# --- MAIN UI ---
def main(page: ft.Page):
    page.title = "Titan Pro"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 10
    
    # Load State
    user_pf = load_json(USER_PF)
    
    # --- UI COMPONENTS ---
    
    # 1. Dashboard View
    txt_equity = ft.Text(f"₹{user_pf['equity']:,.0f}", size=30, weight="bold", color="white")
    txt_cash = ft.Text(f"Cash: ₹{user_pf['cash']:,.0f}", color="green")
    
    def refresh_data(e):
        page.snack_bar = ft.SnackBar(ft.Text("Updating Market Data..."), open=True)
        page.update()
        fetch_fresh_data()
        page.snack_bar = ft.SnackBar(ft.Text("Data Updated!"), open=True)
        page.update()

    dashboard_view = ft.Column([
        ft.Container(
            content=ft.Column([
                ft.Text("NET WORTH", size=12, color="grey"),
                txt_equity,
                txt_cash
            ]),
            padding=20, bgcolor=ft.colors.GREY_900, border_radius=10
        ),
        ft.ElevatedButton("Sync Market Data", icon=ft.icons.REFRESH, on_click=refresh_data, width=400)
    ])

    # 2. Scanner View
    lv_scan = ft.ListView(expand=True, spacing=10)
    
    def load_scanner(e=None):
        lv_scan.controls.clear()
        data = get_scan_results()
        if not data:
            lv_scan.controls.append(ft.Text("No Data. Click Sync on Home."))
        else:
            for item in data:
                lv_scan.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(item['ticker'], weight="bold"),
                                ft.Text(f"₹{item['price']:.2f}", size=12, color="grey")
                            ]),
                            ft.ElevatedButton(
                                "BUY", 
                                on_click=lambda e, t=item['ticker'], p=item['price']: buy_stock(t, p),
                                bgcolor="green", color="white"
                            )
                        ], alignment="spaceBetween"),
                        padding=10, bgcolor=ft.colors.GREY_800, border_radius=5
                    )
                )
        page.update()

    scanner_view = ft.Column([
        ft.ElevatedButton("Run Scanner", on_click=load_scanner),
        lv_scan
    ])

    # 3. Portfolio View
    lv_holdings = ft.ListView(expand=True, spacing=10)

    def load_holdings(e=None):
        lv_holdings.controls.clear()
        if not user_pf['holdings']:
            lv_holdings.controls.append(ft.Text("No Positions"))
        else:
            for t, pos in user_pf['holdings'].items():
                lv_holdings.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(t, weight="bold"),
                                ft.Text(f"Qty: {pos['qty']} | Avg: {pos['entry_price']:.0f}", size=12)
                            ]),
                            ft.Text(f"Stop: {pos['stop_loss']:.0f}", color="red")
                        ], alignment="spaceBetween"),
                        padding=10, bgcolor=ft.colors.GREY_800, border_radius=5
                    )
                )
        page.update()

    # --- LOGIC ---
    def buy_stock(ticker, price):
        qty = int((user_pf['cash'] * 0.1) / price)
        if qty > 0 and user_pf['cash'] >= (qty * price):
            user_pf['cash'] -= (qty * price)
            
            if ticker in user_pf['holdings']:
                user_pf['holdings'][ticker]['qty'] += qty
            else:
                user_pf['holdings'][ticker] = {
                    "qty": qty, "entry_price": price, 
                    "stop_loss": price * 0.9, "highest_high": price
                }
            
            save_json(user_pf, USER_PF)
            # Update UI
            txt_equity.value = f"₹{user_pf['equity']:,.0f}"
            txt_cash.value = f"Cash: ₹{user_pf['cash']:,.0f}"
            page.snack_bar = ft.SnackBar(ft.Text(f"Bought {qty} {ticker}"), open=True)
            page.update()

    # --- TABS LAYOUT ---
    t = ft.Tabs(
        selected_index=0,
        animation_duration=300,
        tabs=[
            ft.Tab(text="Dash", icon=ft.icons.DASHBOARD, content=dashboard_view),
            ft.Tab(text="Scan", icon=ft.icons.RADAR, content=scanner_view),
            ft.Tab(text="Port", icon=ft.icons.PIE_CHART, content=ft.Column([ft.ElevatedButton("Refresh", on_click=load_holdings), lv_holdings])),
        ],
        expand=1,
    )
    
    page.add(t)
    load_holdings() # Init load

ft.app(target=main)