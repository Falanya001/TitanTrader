import sqlite3
import pandas as pd
import pandas_ta as ta
import numpy as np
import json
import os
from datetime import datetime

# --- CONFIGURATION ---
DB_PATH = 'market_data.db'
BOT_PF_FILE = 'shadow_portfolio.json'  # The file the Dashboard reads
INITIAL_CAPITAL = 1000000
MAX_POSITIONS = 10
ALLOCATION_PCT = 0.09  # Invest 9% per trade
ATR_MULTIPLIER = 3.0
MIN_MOMENTUM = 20

# --- DATA LOADER ---
def get_market_data(conn, ticker):
    try:
        # Get last 300 days to ensure we can calculate 200 SMA
        query = f"SELECT date, open, high, low, close FROM daily_prices WHERE ticker='{ticker}' ORDER BY date DESC LIMIT 300"
        df = pd.read_sql(query, conn, parse_dates=['date'])
        
        if len(df) < 200: return None, None

        df.sort_index(ascending=True, inplace=True)
        df.set_index('date', inplace=True)
        
        # Calculate Indicators
        df['SMA200'] = ta.sma(df['close'], length=200)
        df['SMA50'] = ta.sma(df['close'], length=50)
        df['ROC'] = ta.roc(df['close'], length=125)
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=20)
        df['RSI'] = ta.rsi(df['close'], length=14)
        
        return df.iloc[-1], df # Return (Today's Row, Full DF)
    except Exception as e:
        return None, None

def load_portfolio():
    if not os.path.exists(BOT_PF_FILE):
        return {
            "cash": INITIAL_CAPITAL, 
            "equity": INITIAL_CAPITAL, 
            "holdings": {}, 
            "history": []
        }
    with open(BOT_PF_FILE, 'r') as f:
        return json.load(f)

def save_portfolio(pf):
    with open(BOT_PF_FILE, 'w') as f:
        json.dump(pf, f, indent=4)

# --- MAIN EXECUTION FUNCTION ---
def run_bot():
    print(f"\n🤖 TITAN BOT ENGINE STARTING ({datetime.now().date()})...")
    
    if not os.path.exists(DB_PATH):
        print("❌ Error: 'market_data.db' not found. Run the Data Pipeline first.")
        return

    conn = sqlite3.connect(DB_PATH)
    # Get universe of stocks
    try:
        tickers = [row[0] for row in conn.execute("SELECT DISTINCT ticker FROM daily_prices")]
    except:
        print("❌ Error: Database is empty.")
        return

    pf = load_portfolio()
    today_date = str(datetime.now().date())
    logs = []
    
    # -----------------------------------------------
    # 1. MARK TO MARKET & SELL LOGIC
    # -----------------------------------------------
    current_equity = pf['cash']
    active_tickers = list(pf['holdings'].keys())
    
    print(f"   Checking {len(active_tickers)} active positions...")
    
    for ticker in active_tickers:
        today, _ = get_market_data(conn, ticker)
        pos = pf['holdings'][ticker]
        
        # If no data for today (e.g., Sunday/Holiday), use last known price
        if today is None:
            current_equity += pos['qty'] * pos['entry_price']
            continue
            
        price = today['close']
        current_equity += pos['qty'] * price
        
        # A. Update Trailing Stop
        new_high = max(pos['highest_high'], today['high'])
        pf['holdings'][ticker]['highest_high'] = new_high
        
        # Only raise stop, never lower it
        if pd.notna(today['ATR']):
            dynamic_stop = new_high - (ATR_MULTIPLIER * today['ATR'])
            if dynamic_stop > pos['stop_loss']:
                pf['holdings'][ticker]['stop_loss'] = dynamic_stop
            
        # B. Sell Condition
        if price < pos['stop_loss']:
            revenue = pos['qty'] * price
            pf['cash'] += revenue
            
            # PnL Calculation
            pnl = revenue - (pos['qty'] * pos['entry_price'])
            pnl_pct = (pnl / (pos['qty'] * pos['entry_price'])) * 100
            
            logs.append(f"🔴 SELL {ticker} | Price: {price:.2f} | PnL: {pnl_pct:.1f}%")
            del pf['holdings'][ticker]

    # Update History
    pf['equity'] = current_equity
    # Only append history if it's a new date
    if not pf['history'] or pf['history'][-1]['date'] != today_date:
        pf['history'].append({"date": today_date, "equity": current_equity})
    else:
        pf['history'][-1]['equity'] = current_equity
    
    # -----------------------------------------------
    # 2. BUY LOGIC
    # -----------------------------------------------
    print(f"   Scanning market (Cash: ₹{pf['cash']:,.0f})...")
    
    if len(pf['holdings']) < MAX_POSITIONS:
        candidates = []
        for ticker in tickers:
            if ticker in pf['holdings']: continue
            
            today, _ = get_market_data(conn, ticker)
            if today is None: continue
            if pd.isna(today['SMA200']): continue
            
            # --- STRATEGY ---
            # Trend: Price > 200 SMA & 50 SMA
            # Momentum: ROC > 20
            # Value: RSI < 70 (Not overbought)
            if (today['close'] > today['SMA200'] and 
                today['close'] > today['SMA50'] and 
                today['ROC'] > MIN_MOMENTUM and 
                today['RSI'] < 70):
                
                candidates.append((ticker, today['ROC'], today))
        
        # Sort by Strongest Momentum
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        for ticker, roc, data in candidates:
            if len(pf['holdings']) >= MAX_POSITIONS: break
            if pf['cash'] < 10000: break 
            
            price = data['close']
            
            # Position Sizing
            target_amt = pf['equity'] * ALLOCATION_PCT
            qty = int(target_amt / price)
            cost = qty * price
            
            if qty > 0 and pf['cash'] >= cost:
                pf['cash'] -= cost
                initial_stop = price - (ATR_MULTIPLIER * data['ATR'])
                
                pf['holdings'][ticker] = {
                    "qty": qty,
                    "entry_price": price,
                    "stop_loss": initial_stop,
                    "highest_high": price,
                    "date_bought": today_date
                }
                logs.append(f"🟢 BUY  {ticker} | Price: {price:.2f} | Qty: {qty}")

    # 3. SAVE
    save_portfolio(pf)
    
    print(f"✅ BOT CYCLE COMPLETE. Net Worth: ₹{pf['equity']:,.2f}")
    for l in logs: print(l)

# Allow standalone execution
if __name__ == "__main__":
    run_bot()