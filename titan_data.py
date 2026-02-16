import yfinance as yf
import sqlite3
import pandas as pd
import datetime
import time

# --- CONFIGURATION ---
DB_NAME = "market_data.db"

# THE NIFTY 50 UNIVERSE (Mapped by Sector)
# This ensures we are diversified by design, not accident.
ASSETS = {
    # --- BANKS (The Engine) ---
    "HDFCBANK.NS": "Financials", "ICICIBANK.NS": "Financials", "SBIN.NS": "Financials", 
    "AXISBANK.NS": "Financials", "KOTAKBANK.NS": "Financials", "INDUSINDBK.NS": "Financials",
    
    # --- IT (The Exporters) ---
    "TCS.NS": "Technology", "INFY.NS": "Technology", "HCLTECH.NS": "Technology",
    "WIPRO.NS": "Technology", "TECHM.NS": "Technology", "LTIM.NS": "Technology",
    
    # --- OIL & ENERGY (The Powerhouse) ---
    "RELIANCE.NS": "Energy", "ONGC.NS": "Energy", "NTPC.NS": "Utilities",
    "POWERGRID.NS": "Utilities", "BPCL.NS": "Energy", "COALINDIA.NS": "Energy",
    
    # --- AUTO (Cyclicals) ---
    "MARUTI.NS": "Auto", "M&M.NS": "Auto",
    "BAJAJ-AUTO.NS": "Auto", "HEROMOTOCO.NS": "Auto", "EICHERMOT.NS": "Auto",
    
    # --- FMCG (Defensives) ---
    "ITC.NS": "FMCG", "HINDUNILVR.NS": "FMCG", "NESTLEIND.NS": "FMCG",
    "BRITANNIA.NS": "FMCG", "TATACONSUM.NS": "FMCG",
    
    # --- METALS & COMMODITIES ---
    "TATASTEEL.NS": "Metals", "HINDALCO.NS": "Metals", "JSWSTEEL.NS": "Metals",
    
    # --- PHARMA (Healthcare) ---
    "SUNPHARMA.NS": "Healthcare", "DRREDDY.NS": "Healthcare", 
    "CIPLA.NS": "Healthcare", "APOLLOHOSP.NS": "Healthcare",
    
    # --- OTHERS (Cement, Infra, Telecom) ---
    "ULTRACEMCO.NS": "Cement", "GRASIM.NS": "Cement",
    "LT.NS": "Construction", "BHARTIARTL.NS": "Telecom",
    "TITAN.NS": "Consumer", "ASIANPAINT.NS": "Consumer",
    "ADANIENT.NS": "Conglomerate", "ADANIPORTS.NS": "Infrastructure"
}

def init_db():
    """
    Initialize DB with a schema that supports Sector analysis.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Note the new column: 'sector'
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_prices (
            ticker TEXT,
            sector TEXT,
            date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, date)
        )
    ''')
    conn.commit()
    conn.close()
    print("[SYSTEM] Database Schema Ready (With Sectors).")

def get_last_date(ticker):
    """
    Checks the DB to see when we last updated this specific stock.
    Returns: 'YYYY-MM-DD' or None
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM daily_prices WHERE ticker = ?", (ticker,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def update_market_data():
    print(f"--- STARTING ETL PIPELINE ({len(ASSETS)} ASSETS) ---")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    for ticker, sector in ASSETS.items():
        try:
            # 1. Determine Start Date (Smart Update)
            last_date = get_last_date(ticker)
            
            if last_date:
                # If we have data, start from the next day
                start_dt = (datetime.datetime.strptime(last_date, "%Y-%m-%d") + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
                # If start_date is in the future (today is weekend), skip
                if start_dt > datetime.date.today().strftime("%Y-%m-%d"):
                    print(f"[{ticker}] Up to date.")
                    continue
            else:
                # If new stock, get full history (10 Years)
                start_dt = "2015-01-01"

            print(f"[{ticker}] Downloading from {start_dt}...")
            
            # 2. Extract (Download)
            df = yf.download(ticker, start=start_dt, auto_adjust=True, progress=False)
            
            if df.empty:
                print(f"   >> Warning: No data found.")
                continue

            # 3. Transform (Clean)
            # Fix MultiIndex columns
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            df = df.reset_index()
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
            
            # Remove Zero Volume Days (Market Holidays / Glitches)
            # Math breaks if Volume is 0 (e.g. VWAP calculations)
            df = df[df['Volume'] > 0]

            # 4. Load (Insert to DB)
            new_rows = 0
            for _, row in df.iterrows():
                cursor.execute('''
                    INSERT OR IGNORE INTO daily_prices 
                    (ticker, sector, date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ticker, 
                    sector, 
                    row['Date'], 
                    float(row['Open']), 
                    float(row['High']), 
                    float(row['Low']), 
                    float(row['Close']), 
                    int(row['Volume'])
                ))
                new_rows += 1
            
            conn.commit() # Commit after each stock to save progress
            print(f"   >> Success: Added {new_rows} rows.")
            
        except Exception as e:
            print(f"[ERROR] Failed {ticker}: {e}")

    conn.close()
    print("--- ETL PIPELINE COMPLETE ---")

if __name__ == "__main__":
    init_db()
    update_market_data()