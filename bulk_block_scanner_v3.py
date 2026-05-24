"""
scanx.trade Weekly Block/Bulk Deal Scanner
Scrapes https://scanx.trade/insight/bulk-block-deals
Filters: MF, Bank, Insurance, Financial Institutions
Date range: Current week Monday to today
Output: Console table + scanx_deals_this_week.csv
"""

import time, csv, sys
from datetime import date, timedelta, datetime

# ─── TARGETS ──────────────────────────────────────────────────────────────
MF_KEYWORDS = [
    'MUTUAL FUND','ASSET MANAGEMENT','AMC',
    'SBI MF','HDFC MF','ICICI PRU','AXIS MF','KOTAK MF','NIPPON MF',
    'DSP MF','MIRAE','FRANKLIN','ADITYA BIRLA','BIRLA SUN LIFE',
    'UTI MF','TATA MF','EDELWEISS','INVESCO','SUNDARAM','QUANTUM MF',
    'CANARA MF','LIC MF','HSBC MF','PGIM MF','BOI MF','UNION MF',
    'PARAG PARIKH','PPFAS','PPFCF','MOTILAL OSWAL','MOFSL','MOMF','MOAMC','WHITEOAK',
    'QUANT MUTUAL','GROWW MF','NAVI MF','ZERODHA MF',
]

BANK_KEYWORDS = [
    'BANK','HDFC BANK','ICICI BANK','AXIS BANK','KOTAK BANK',
    'STATE BANK','SBI','YES BANK','INDUSIND','BANDHAN',
    'FEDERAL BANK','IDFC','RBL BANK','CANARA BANK','UNION BANK',
    'BANK OF BARODA','BANK OF INDIA','PNB','PUNJAB NATIONAL',
]

FI_KEYWORDS = [
    'LIC','LIFE INSURANCE','INSURANCE','BAJAJ ALLIANZ','SBI LIFE',
    'MAX LIFE','HDFC LIFE','KOTAK LIFE','TATA AIA','STAR HEALTH',
    'CARE HEALTH','NIVA BUPA','DIGIT INSURANCE','NEW INDIA',
    'GIC','GENERAL INSURANCE','NPS','PENSION','PROVIDENT',
    'MORGAN STANLEY','GOLDMAN SACHS','JPMORGAN','BLACKROCK',
    'VANGUARD','FIDELITY','GQG','SMALLCAP WORLD','EMERGING MARKETS',
    'SOCIETE GENERALE','DEUTSCHE BANK','BARCLAYS','CITIBANK',
    'MERRILL LYNCH','CREDIT SUISSE','UBS','NOMURA',
    'FII','FPI','ODI','P-NOTE',
    'KOTAK','IIFL','MOTILAL','MOFSL',
]

ALL_KEYWORDS = MF_KEYWORDS + BANK_KEYWORDS + FI_KEYWORDS

def is_target(name):
    n = (name or '').upper()
    return any(k.upper() in n for k in ALL_KEYWORDS)

def classify(name):
    n = (name or '').upper()
    if any(k.upper() in n for k in MF_KEYWORDS):   return 'MF'
    if any(k.upper() in n for k in BANK_KEYWORDS):  return 'BANK'
    if any(k.upper() in n for k in FI_KEYWORDS):    return 'FI/FII'
    return 'OTHER'

# ─── DATE RANGE: Mon–today ────────────────────────────────────────────────
def get_week_range():
    today = date.today()
    monday = today - timedelta(days=today.weekday())  # this week's Monday
    return monday, today

# ─── FETCH via Selenium ───────────────────────────────────────────────────
def fetch_scanx_selenium():
    deals = []
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
        from bs4 import BeautifulSoup

        print("[*] Starting Chrome headless...")
        opts = Options()
        opts.add_argument('--headless')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--disable-blink-features=AutomationControlled')
        opts.add_argument('--window-size=1920,1080')
        opts.add_experimental_option('excludeSwitches', ['enable-automation'])
        opts.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36')

        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

        url = 'https://scanx.trade/insight/bulk-block-deals'
        print(f"[*] Loading {url}")
        driver.get(url)
        time.sleep(5)

        # Scroll to load all rows (lazy loading)
        print("[*] Scrolling to load all data...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(20):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # Try clicking "Show More" or "Load All" buttons
        for btn_text in ['Show All', 'Load More', 'View All', 'Show More']:
            try:
                btns = driver.find_elements(By.XPATH, f"//button[contains(text(),'{btn_text}')]")
                for btn in btns:
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2)
                    print(f"[*] Clicked '{btn_text}' button")
            except:
                pass

        # Scroll again after clicking
        for _ in range(10):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        page_source = driver.page_source
        driver.quit()

        # Parse
        soup = BeautifulSoup(page_source, 'lxml')
        tables = soup.find_all('table')
        print(f"[*] Found {len(tables)} tables")

        monday, today = get_week_range()
        print(f"[*] Filtering: {monday.strftime('%d %b %Y')} to {today.strftime('%d %b %Y')}")

        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue

            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th','td'])]
            print(f"[*] Table headers: {headers}")

            # Find column indexes
            stock_idx  = next((i for i,h in enumerate(headers) if 'stock' in h or 'scrip' in h or 'symbol' in h), 0)
            date_idx   = next((i for i,h in enumerate(headers) if 'date' in h), 1)
            client_idx = next((i for i,h in enumerate(headers) if 'client' in h or 'name' in h or 'buyer' in h or 'seller' in h), 2)
            action_idx = next((i for i,h in enumerate(headers) if 'action' in h or 'buy' in h or 'sell' in h or 'b/s' in h), 3)
            qty_idx    = next((i for i,h in enumerate(headers) if 'qty' in h or 'quant' in h), 4)
            price_idx  = next((i for i,h in enumerate(headers) if 'price' in h or 'avg' in h), 5)
            value_idx  = next((i for i,h in enumerate(headers) if 'value' in h or 'cr' in h or 'amount' in h), 6)

            for row in rows[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all('td')]
                if len(cols) < 4:
                    continue

                client = cols[client_idx] if client_idx < len(cols) else ''
                if not is_target(client):
                    continue

                # Parse date
                raw_date = cols[date_idx] if date_idx < len(cols) else ''
                deal_date = None
                for fmt in ['%d %b %Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y']:
                    try:
                        deal_date = datetime.strptime(raw_date.strip(), fmt).date()
                        break
                    except:
                        pass

                # Filter: only this week (Monday to today)
                if deal_date and (deal_date < monday or deal_date > today):
                    continue

                stock_raw = cols[stock_idx] if stock_idx < len(cols) else ''
                # Remove 'Block'/'Bulk' tag from stock name
                stock = stock_raw.replace('Block','').replace('Bulk','').strip()
                dtype = 'BLOCK' if 'Block' in stock_raw else 'BULK'

                action = cols[action_idx] if action_idx < len(cols) else ''
                qty    = cols[qty_idx] if qty_idx < len(cols) else ''
                price  = cols[price_idx] if price_idx < len(cols) else ''
                value  = cols[value_idx] if value_idx < len(cols) else ''

                deals.append({
                    'date':   raw_date,
                    'stock':  stock,
                    'type':   dtype,
                    'client': client,
                    'cat':    classify(client),
                    'action': action.upper(),
                    'qty':    qty,
                    'price':  price,
                    'value':  value,
                })

        print(f"[*] Total matching deals: {len(deals)}")
        return deals

    except ImportError as e:
        print(f"[!] Missing package: {e}")
        print("    Run: pip install selenium webdriver-manager beautifulsoup4 lxml")
        return []
    except Exception as e:
        print(f"[!] Selenium error: {e}")
        import traceback; traceback.print_exc()
        return []

# ─── REQUESTS FALLBACK ────────────────────────────────────────────────────
def fetch_scanx_requests():
    """Fallback: requests + BS4 (may get partial data, site is JS-heavy)"""
    deals = []
    try:
        import requests
        from bs4 import BeautifulSoup

        print("[*] Trying requests fallback...")
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.9',
            'Referer': 'https://scanx.trade/',
        }

        # Try API endpoints
        api_endpoints = [
            'https://scanx.trade/api/bulk-block-deals',
            'https://scanx.trade/api/v1/bulk-block-deals',
            'https://api.scanx.trade/bulk-block-deals',
        ]

        monday, today = get_week_range()

        for ep in api_endpoints:
            try:
                r = session.get(ep, headers={**headers, 'Accept':'application/json'}, timeout=10)
                if r.status_code == 200:
                    try:
                        data = r.json()
                        raw = data.get('data', data.get('deals', data if isinstance(data, list) else []))
                        for row in (raw if isinstance(raw, list) else []):
                            client = row.get('clientName', row.get('client', row.get('entity', '')))
                            if not is_target(client):
                                continue
                            deals.append({
                                'date':   str(row.get('date', today)),
                                'stock':  row.get('symbol', row.get('stock', '')),
                                'type':   'BLOCK' if 'block' in str(row.get('dealType','')).lower() else 'BULK',
                                'client': client,
                                'cat':    classify(client),
                                'action': str(row.get('buySell', row.get('action',''))).upper(),
                                'qty':    str(row.get('quantity', row.get('qty', ''))),
                                'price':  str(row.get('tradePrice', row.get('price', ''))),
                                'value':  str(row.get('value', row.get('dealValue', ''))),
                            })
                        if deals:
                            print(f"[*] API hit: {ep} → {len(deals)} deals")
                            break
                    except:
                        pass
            except:
                pass

        # HTML fallback
        if not deals:
            r = session.get('https://scanx.trade/insight/bulk-block-deals', headers=headers, timeout=20)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'lxml')
                for table in soup.find_all('table'):
                    for row in table.find_all('tr')[1:]:
                        cols = [td.get_text(strip=True) for td in row.find_all('td')]
                        if len(cols) < 4:
                            continue
                        client = next((c for c in cols if is_target(c)), '')
                        if not client:
                            continue
                        deals.append({
                            'date':   cols[1] if len(cols) > 1 else str(today),
                            'stock':  cols[0].replace('Block','').replace('Bulk','').strip(),
                            'type':   'BLOCK' if 'Block' in cols[0] else 'BULK',
                            'client': client,
                            'cat':    classify(client),
                            'action': cols[3].upper() if len(cols) > 3 else '',
                            'qty':    cols[4] if len(cols) > 4 else '',
                            'price':  cols[5] if len(cols) > 5 else '',
                            'value':  cols[6] if len(cols) > 6 else '',
                        })

    except Exception as e:
        print(f"[!] Requests fallback error: {e}")

    return deals

# ─── DISPLAY ──────────────────────────────────────────────────────────────
def print_table(deals):
    monday, today = get_week_range()
    print(f"\n{'='*90}")
    print(f"  BLOCK/BULK DEALS — MF | BANK | FI/FII")
    print(f"  Week: {monday.strftime('%d %b %Y')} (Mon) → {today.strftime('%d %b %Y')}")
    print(f"  Total: {len(deals)} deals found")
    print(f"{'='*90}")

    if not deals:
        print("  No matching deals found.")
        print("  Possible reasons:")
        print("    1. Chrome/Selenium not installed")
        print("    2. Site blocked headless browser")
        print("    3. No MF/Bank/FI deals this week yet")
        return

    # Sort by date desc, then value desc
    def sort_key(d):
        try:
            v = float(d['value'].replace(',','').replace('₹','').replace('Cr','').strip() or '0')
        except:
            v = 0
        return (d['date'], -v)

    deals_sorted = sorted(deals, key=sort_key, reverse=True)

    # Group by category
    for cat in ['MF', 'BANK', 'FI/FII']:
        cat_deals = [d for d in deals_sorted if d['cat'] == cat]
        if not cat_deals:
            continue
        label = {'MF':'🏦 MUTUAL FUNDS', 'BANK':'🏛 BANKS', 'FI/FII':'🌐 FI / FII / INSURANCE'}[cat]
        print(f"\n  {label} ({len(cat_deals)} deals)")
        print(f"  {'-'*86}")
        print(f"  {'Date':<14} {'Stock':<22} {'T':<6} {'Action':<6} {'Client':<30} {'Qty':<12} {'Value(Cr)'}")
        print(f"  {'-'*86}")
        for d in cat_deals:
            act = '🟢 BUY' if 'BUY' in d['action'] else '🔴 SEL'
            qty = d['qty'][:11] if d['qty'] else '-'
            val = d['value'][:10] if d['value'] else '-'
            client_short = d['client'][:29]
            stock_short  = d['stock'][:21]
            print(f"  {d['date']:<14} {stock_short:<22} {d['type']:<6} {act:<6} {client_short:<30} {qty:<12} {val}")

    print(f"\n{'='*90}\n")

# ─── SAVE CSV ─────────────────────────────────────────────────────────────
def save_csv(deals, filename='scanx_deals_this_week.csv'):
    if not deals:
        return
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['date','stock','type','client','cat','action','qty','price','value'])
        w.writeheader()
        w.writerows(deals)
    print(f"[*] Saved: {filename} ({len(deals)} rows)")

# ─── MAIN ─────────────────────────────────────────────────────────────────
def main():
    print("\n" + "="*60)
    print("  scanx.trade Block/Bulk Scanner — This Week")
    print("  Filter: MF | Bank | FI/FII")
    print("="*60)

    # Try Selenium first, fallback to requests
    deals = fetch_scanx_selenium()

    if not deals:
        print("[*] Selenium returned 0 — trying requests fallback...")
        deals = fetch_scanx_requests()

    print_table(deals)
    save_csv(deals)

    if not deals:
        print("[!] No deals found. If Chrome is not installed:")
        print("    pip install selenium webdriver-manager beautifulsoup4 lxml")
        print("    Also make sure Chrome browser is installed on this PC.")

if __name__ == '__main__':
    main()
