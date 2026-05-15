"""
Bulk & Block Deal Scanner v3
Sources: NSE Selenium + NSE CSV + Trendlyne Selenium + scanx.trade
Sends Telegram + Email alerts

Install:
  pip install requests beautifulsoup4 lxml selenium webdriver-manager
"""

import os, time, logging, smtplib, json, hashlib
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('bbscanner')

# ─── CONFIG ───────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
EMAIL_FROM       = os.getenv('EMAIL_FROM', '')
EMAIL_PASSWORD   = os.getenv('EMAIL_PASSWORD', '')
EMAIL_TO         = os.getenv('EMAIL_TO', '')
REFRESH_MINUTES  = int(os.getenv('REFRESH_MINUTES', '30'))
# ──────────────────────────────────────────────────────────────────────────

TARGET_KEYWORDS = [
    'HDFC MF','SBI MF','ICICI PRU','AXIS MF','KOTAK MF','NIPPON MF',
    'DSP MF','MIRAE','FRANKLIN','ADITYA BIRLA','UTI MF','TATA MF',
    'EDELWEISS','INVESCO','SUNDARAM MF','QUANTUM MF','CANARA MF',
    'LIC MF','HSBC MF','PGIM MF','BOI MF','UNION MF','HDFC MUTUAL',
    'HDFC BANK','ICICI BANK','AXIS BANK','KOTAK BANK','STATE BANK',
    'YES BANK','INDUSIND','BANDHAN BANK','FEDERAL BANK','IDFC','RBL BANK',
    'LIC','HDFC LIFE','ICICI LOMBARD','BAJAJ ALLIANZ','SBI LIFE',
    'MAX LIFE','KOTAK LIFE','TATA AIA','STAR HEALTH','CARE HEALTH',
    'NIVA BUPA','DIGIT INSURANCE','NEW INDIA',
    'MOTILAL OSWAL','MOFSL','PPFAS','PARAG PARIKH',
]

ENTITY_TYPE = {
    'mf':      ['HDFC MF','SBI MF','ICICI PRU','AXIS MF','KOTAK MF','NIPPON MF','DSP MF',
                'MIRAE','FRANKLIN','ADITYA BIRLA','UTI MF','HDFC MUTUAL','TATA MF','EDELWEISS',
                'INVESCO','SUNDARAM MF','QUANTUM MF','CANARA MF','LIC MF','HSBC MF','PGIM MF',
                'BOI MF','UNION MF'],
    'bank':    ['HDFC BANK','ICICI BANK','AXIS BANK','KOTAK BANK','STATE BANK','YES BANK',
                'INDUSIND','BANDHAN BANK','FEDERAL BANK','IDFC','RBL BANK'],
    'ins':     ['LIC','HDFC LIFE','ICICI LOMBARD','BAJAJ ALLIANZ','SBI LIFE','MAX LIFE',
                'KOTAK LIFE','TATA AIA','STAR HEALTH','CARE HEALTH','NIVA BUPA','DIGIT','NEW INDIA'],
    'motilal': ['MOTILAL OSWAL','MOFSL'],
    'ppfas':   ['PPFAS','PARAG PARIKH'],
}

seen_hashes = set()

def classify_entity(name):
    n = (name or '').upper()
    for etype, kws in ENTITY_TYPE.items():
        if any(k.upper() in n for k in kws):
            return etype
    return 'other'

def is_target(entity):
    e = (entity or '').upper()
    return any(k.upper() in e for k in TARGET_KEYWORDS)

def deal_hash(d):
    key = f"{d['stock']}|{d['entity']}|{d['action']}|{d['qty']}|{d['price']}"
    return hashlib.md5(key.encode()).hexdigest()

# ─── SELENIUM HELPER ──────────────────────────────────────────────────────

def get_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    opts.add_argument('--headless')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument('--window-size=1920,1080')
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)
    opts.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

# ─── SOURCE 1: NSE via Selenium ───────────────────────────────────────────

def fetch_nse_selenium():
    deals = []
    try:
        from selenium.webdriver.common.by import By
        driver = get_driver()
        today = date.today().strftime('%d-%m-%Y')

        for deal_type in ['bulk', 'block']:
            try:
                driver.get('https://www.nseindia.com')
                time.sleep(3)
                url = f'https://www.nseindia.com/api/{deal_type}-deals?from={today}&to={today}'
                driver.get(url)
                time.sleep(2)
                body = driver.find_element(By.TAG_NAME, 'body').text
                data = json.loads(body)
                for row in data.get('data', []):
                    entity = row.get('clientName', '')
                    if not is_target(entity):
                        continue
                    deals.append({
                        'stock':  row.get('symbol', ''),
                        'entity': entity,
                        'etype':  classify_entity(entity),
                        'dtype':  deal_type,
                        'action': 'BUY' if 'B' in row.get('buySell', '').upper() else 'SELL',
                        'qty':    int(row.get('quantityTraded', row.get('quantity', 0))),
                        'price':  float(row.get('tradePrice', 0)),
                        'date':   today,
                        'source': 'NSE',
                    })
                log.info(f'NSE {deal_type} (Selenium): {len([d for d in deals if d["dtype"]==deal_type])} target deals')
            except Exception as e:
                log.warning(f'NSE {deal_type} selenium failed: {e}')
        driver.quit()
    except ImportError:
        log.warning('Selenium not installed')
    except Exception as e:
        log.warning(f'NSE Selenium error: {e}')
    return deals

# ─── SOURCE 2: NSE CSV Archive ────────────────────────────────────────────

def fetch_nse_csv():
    deals = []
    try:
        today = date.today()
        date_str = today.strftime('%d%m%Y')
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://www.nseindia.com/',
        }
        for dtype in ['bulk', 'block']:
            url = f'https://archives.nseindia.com/corporate/{dtype}_deals_{date_str}.csv'
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                log.warning(f'CSV {dtype}: {r.status_code}')
                continue
            lines = r.text.strip().split('\n')
            for line in lines[1:]:
                cols = [c.strip().strip('"') for c in line.split(',')]
                if len(cols) < 6:
                    continue
                entity = cols[3] if len(cols) > 3 else ''
                if not is_target(entity):
                    continue
                deals.append({
                    'stock':  cols[1] if len(cols) > 1 else '',
                    'entity': entity,
                    'etype':  classify_entity(entity),
                    'dtype':  dtype,
                    'action': 'BUY' if 'B' in cols[4].upper() else 'SELL',
                    'qty':    int(cols[5].replace(',', '')) if len(cols) > 5 else 0,
                    'price':  float(cols[6].replace(',', '')) if len(cols) > 6 else 0,
                    'date':   today.strftime('%d-%m-%Y'),
                    'source': 'NSE CSV',
                })
        log.info(f'NSE CSV: {len(deals)} target deals')
    except Exception as e:
        log.warning(f'NSE CSV error: {e}')
    return deals

# ─── SOURCE 3: Trendlyne via Selenium ─────────────────────────────────────

def fetch_trendlyne():
    deals = []
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        driver = get_driver()
        log.info('Trendlyne: opening browser...')

        driver.get('https://trendlyne.com/portfolio/bulk-block-deals/')
        time.sleep(5)  # Wait for JS to load table

        # Scroll down to load lazy content
        driver.execute_script('window.scrollTo(0, 500)')
        time.sleep(2)

        soup = BeautifulSoup(driver.page_source, 'lxml')

        # Try to find the data table
        tables = soup.find_all('table')
        log.info(f'Trendlyne: {len(tables)} tables found')

        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th', 'td'])]
            log.info(f'Trendlyne table headers: {headers}')

            # Confirmed headers from logs:
            # stock, client name, exchange, deal type, action, date, avg. price, quantity, intraday, percentage traded %
            sym_idx    = next((i for i, h in enumerate(headers) if h == 'stock' or h == 'symbol' or h == 'scrip'), 0)
            client_idx = next((i for i, h in enumerate(headers) if 'client' in h or h == 'name'), 1)
            type_idx   = next((i for i, h in enumerate(headers) if 'deal type' in h or h == 'type'), 3)
            bs_idx     = next((i for i, h in enumerate(headers) if h == 'action' or ('buy' in h and 'sell' not in h)), 4)
            price_idx  = next((i for i, h in enumerate(headers) if 'price' in h or 'avg' in h), 6)
            qty_idx    = next((i for i, h in enumerate(headers) if 'quantity' in h or 'qty' in h), 7)

            for row in rows[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all('td')]
                if len(cols) < 4:
                    continue
                entity = cols[client_idx] if client_idx < len(cols) else ''
                if not is_target(entity):
                    continue
                try:
                    qty   = int(cols[qty_idx].replace(',', '').replace('-', '0')) if qty_idx < len(cols) else 0
                    price = float(cols[price_idx].replace(',', '').replace('₹', '').replace('-', '0')) if price_idx < len(cols) else 0.0
                except:
                    qty, price = 0, 0.0

                dtype = 'block' if 'block' in (cols[type_idx] if type_idx < len(cols) else '').lower() else 'bulk'
                bs_col = cols[bs_idx] if bs_idx < len(cols) else ''
                action = 'BUY' if 'B' in bs_col.upper() and 'S' not in bs_col.upper() else 'SELL'

                deals.append({
                    'stock':  cols[sym_idx] if sym_idx < len(cols) else '',
                    'entity': entity,
                    'etype':  classify_entity(entity),
                    'dtype':  dtype,
                    'action': action,
                    'qty':    qty,
                    'price':  price,
                    'date':   str(date.today()),
                    'source': 'Trendlyne',
                })

        # Also try Trendlyne JSON API with browser cookies
        if not deals:
            cookies = {c['name']: c['value'] for c in driver.get_cookies()}
            driver.quit()
            session = requests.Session()
            session.cookies.update(cookies)
            api_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': 'https://trendlyne.com/portfolio/bulk-block-deals/',
            }
            for api_url in [
                'https://trendlyne.com/bulk-deals/bulk-deals-list/?format=json',
                'https://trendlyne.com/portfolio/bulk-block-deals/?format=json',
                'https://trendlyne.com/api/bulk-block-deals/',
            ]:
                try:
                    r = session.get(api_url, headers=api_headers, timeout=10)
                    if r.status_code == 200:
                        data = r.json()
                        raw = data.get('results', data.get('data', data if isinstance(data, list) else []))
                        for row in (raw if isinstance(raw, list) else []):
                            entity = row.get('client_name', row.get('clientName', row.get('entity', '')))
                            if not is_target(entity):
                                continue
                            deals.append({
                                'stock':  row.get('symbol', row.get('scrip', '')),
                                'entity': entity,
                                'etype':  classify_entity(entity),
                                'dtype':  'block' if 'block' in str(row.get('deal_type', '')).lower() else 'bulk',
                                'action': 'BUY' if 'B' in str(row.get('buy_sell', row.get('buySell', ''))).upper() else 'SELL',
                                'qty':    int(str(row.get('quantity', row.get('qty', 0))).replace(',', '') or 0),
                                'price':  float(str(row.get('price', row.get('trade_price', 0))).replace(',', '') or 0),
                                'date':   str(row.get('date', date.today())),
                                'source': 'Trendlyne API',
                            })
                        if deals:
                            log.info(f'Trendlyne API hit: {api_url}')
                            break
                except Exception as e:
                    log.warning(f'Trendlyne API {api_url}: {e}')
        else:
            driver.quit()

        log.info(f'Trendlyne: {len(deals)} target deals')
    except ImportError:
        log.warning('Selenium not installed')
    except Exception as e:
        log.warning(f'Trendlyne error: {e}')
    return deals

# ─── SOURCE 4: Scanx.trade ────────────────────────────────────────────────

def fetch_scanx():
    deals = []
    try:
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
            'Accept-Language': 'en-IN,en;q=0.9',
            'Referer': 'https://scanx.trade/',
        }
        session.get('https://scanx.trade/', headers=headers, timeout=10)
        time.sleep(1)

        r = session.get('https://scanx.trade/api/bulk-block-deals',
                        headers={**headers, 'Accept': 'application/json'}, timeout=15)
        if r.status_code == 200:
            try:
                data = r.json()
                raw = data.get('data', data.get('deals', data if isinstance(data, list) else []))
                for row in (raw if isinstance(raw, list) else []):
                    entity = row.get('clientName', row.get('entity', row.get('client', '')))
                    if not is_target(entity):
                        continue
                    deals.append({
                        'stock':  row.get('symbol', row.get('stock', '')),
                        'entity': entity,
                        'etype':  classify_entity(entity),
                        'dtype':  'block' if 'block' in str(row.get('dealType', '')).lower() else 'bulk',
                        'action': 'BUY' if 'B' in str(row.get('buySell', row.get('action', ''))).upper() else 'SELL',
                        'qty':    int(row.get('quantity', row.get('qty', 0))),
                        'price':  float(row.get('tradePrice', row.get('price', 0))),
                        'date':   str(row.get('date', date.today())),
                        'source': 'scanx',
                    })
            except Exception:
                pass

        # HTML fallback
        if not deals:
            r2 = session.get('https://scanx.trade/insight/bulk-block-deals', headers=headers, timeout=20)
            if r2.status_code == 200:
                soup = BeautifulSoup(r2.text, 'lxml')
                for table in soup.find_all('table'):
                    for row in table.find_all('tr')[1:]:
                        cols = [td.get_text(strip=True) for td in row.find_all('td')]
                        if len(cols) < 5:
                            continue
                        entity = next((c for c in cols if is_target(c)), '')
                        if not entity:
                            continue
                        deals.append({
                            'stock':  cols[0],
                            'entity': entity,
                            'etype':  classify_entity(entity),
                            'dtype':  'bulk',
                            'action': 'BUY',
                            'qty':    0,
                            'price':  0,
                            'date':   str(date.today()),
                            'source': 'scanx-html',
                        })

        log.info(f'scanx: {len(deals)} target deals')
    except Exception as e:
        log.warning(f'scanx error: {e}')
    return deals

# ─── ALERTS ───────────────────────────────────────────────────────────────

def send_telegram(deals):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    icons = {'mf': '🏦', 'bank': '🏛', 'ins': '🛡', 'motilal': '📈', 'ppfas': '🟣'}
    lines = [f"📊 *Block/Bulk Deal Alert* — {date.today().strftime('%d %b %Y')}\n"]
    for d in deals:
        icon = icons.get(d['etype'], '💼')
        act  = '🟢 BUY' if d['action'] == 'BUY' else '🔴 SELL'
        val  = d['qty'] * d['price'] / 1e7
        src  = d.get('source', '')
        lines.append(
            f"{icon} *{d['stock']}* [{d['dtype'].upper()}]\n"
            f"  {act} | {d['entity']}\n"
            f"  ₹{d['price']:,.2f} × {d['qty']//1000}K = ₹{val:.1f} Cr\n"
            f"  _src: {src}_\n"
        )
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': '\n'.join(lines), 'parse_mode': 'Markdown'},
            timeout=10
        ).raise_for_status()
        log.info(f'Telegram: {len(deals)} deals sent')
    except Exception as e:
        log.error(f'Telegram failed: {e}')

def send_email(deals):
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        return
    today = date.today().strftime('%d %b %Y')
    rows = ''
    for d in deals:
        val = d['qty'] * d['price'] / 1e7
        c   = '#2ecc71' if d['action'] == 'BUY' else '#e74c3c'
        rows += (
            f"<tr><td>{d['stock']}</td><td>{d['entity']}</td>"
            f"<td>{d['dtype'].upper()}</td>"
            f"<td style='color:{c};font-weight:bold'>{d['action']}</td>"
            f"<td>₹{d['price']:,.2f}</td><td>{d['qty']//1000}K</td>"
            f"<td>₹{val:.2f} Cr</td><td style='color:#888;font-size:11px'>{d.get('source','')}</td></tr>"
        )
    html = f"""<html><body style='font-family:Arial'>
    <h2>📊 Block/Bulk Deal Alert — {today}</h2>
    <p>{len(deals)} new deal(s) — MF / Bank / Insurance / Motilal / PPFAS</p>
    <table border='1' cellpadding='6' style='border-collapse:collapse;font-size:13px'>
    <tr style='background:#f0f0f0'><th>Stock</th><th>Entity</th><th>Type</th>
    <th>Action</th><th>Price</th><th>Qty</th><th>Value</th><th>Source</th></tr>
    {rows}</table>
    <p style='color:#aaa;font-size:11px'>Sources: NSE · Trendlyne · scanx.trade</p>
    </body></html>"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'🔔 {len(deals)} New Block/Bulk Deals — {today}'
        msg['From']    = EMAIL_FROM
        msg['To']      = EMAIL_TO
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(EMAIL_FROM, EMAIL_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info(f'Email sent to {EMAIL_TO}')
    except Exception as e:
        log.error(f'Email failed: {e}')

# ─── MAIN ─────────────────────────────────────────────────────────────────

# ─── SOURCE 5: Moneycontrol via Selenium ──────────────────────────────────

def fetch_moneycontrol():
    deals = []
    try:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        driver = get_driver()
        log.info('Moneycontrol: opening browser...')

        # Prime session once
        driver.get('https://www.moneycontrol.com')
        time.sleep(2)

        for deal_type, url in [
            ('bulk',  'https://www.moneycontrol.com/stocks/marketinfo/bulk_deals/index.php'),
            ('block', 'https://www.moneycontrol.com/stocks/marketinfo/block_deals/index.php'),
        ]:
            try:
                driver.set_page_load_timeout(30)
                driver.get(url)
                time.sleep(3)

                # Scroll to load lazy content
                driver.execute_script('window.scrollTo(0, 600)')
                time.sleep(2)

                soup = BeautifulSoup(driver.page_source, 'lxml')
                tables = soup.find_all('table')
                log.info(f'Moneycontrol {deal_type}: {len(tables)} tables found')
                log.info(f'MC {deal_type} all table headers: {[th.get_text(strip=True).lower() for t in tables[:3] for th in t.find_all("tr")[:1] for th in th.find_all(["th","td"])]}')

                for table in tables:
                    rows = table.find_all('tr')
                    if len(rows) < 2:
                        continue
                    headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th', 'td'])]
                    # Need at least symbol + client columns
                    if not any('symbol' in h or 'scrip' in h or 'stock' in h for h in headers):
                        continue

                    # MC headers: symbol/scrip, company, client name, buy/sell, qty, avg price
                    sym_idx    = next((i for i, h in enumerate(headers) if h in ('symbol','scrip') or 'symbol' in h), 0)
                    client_idx = next((i for i, h in enumerate(headers) if 'client' in h), 2)
                    if client_idx == 2 and len(headers) > 2 and 'client' not in headers[2]:
                        client_idx = next((i for i, h in enumerate(headers) if 'name' in h or 'client' in h or 'entity' in h), 1)
                    bs_idx     = next((i for i, h in enumerate(headers) if 'buy' in h or 'sell' in h or 'b/s' in h or 'tran' in h), 3)
                    qty_idx    = next((i for i, h in enumerate(headers) if 'qty' in h or 'quant' in h or 'share' in h or 'volume' in h), 4)
                    price_idx  = next((i for i, h in enumerate(headers) if 'price' in h or 'rate' in h or 'avg' in h), 5)

                    for row in rows[1:]:
                        cols = [td.get_text(strip=True) for td in row.find_all('td')]
                        if len(cols) < 3:
                            continue
                        entity = cols[client_idx] if client_idx < len(cols) else ''
                        if not is_target(entity):
                            continue
                        try:
                            qty   = int(cols[qty_idx].replace(',', '').replace('-', '0')) if qty_idx < len(cols) else 0
                            price = float(cols[price_idx].replace(',', '').replace('₹', '').replace('-', '0')) if price_idx < len(cols) else 0.0
                        except:
                            qty, price = 0, 0.0

                        bs_col = cols[bs_idx] if bs_idx < len(cols) else ''
                        action = 'BUY' if 'B' in bs_col.upper() and 'SELL' not in bs_col.upper() else 'SELL'

                        deals.append({
                            'stock':  cols[sym_idx] if sym_idx < len(cols) else '',
                            'entity': entity,
                            'etype':  classify_entity(entity),
                            'dtype':  deal_type,
                            'action': action,
                            'qty':    qty,
                            'price':  price,
                            'date':   str(date.today()),
                            'source': 'Moneycontrol',
                        })

            except Exception as e:
                log.warning(f'Moneycontrol {deal_type} parse failed: {e}')

        driver.quit()
        log.info(f'Moneycontrol: {len(deals)} target deals')
    except ImportError:
        log.warning('Selenium not installed')
    except Exception as e:
        log.warning(f'Moneycontrol error: {e}')
    return deals


def scan_once():
    log.info('=== Scanning: NSE + Trendlyne + Moneycontrol + scanx ===')
    all_deals = (
        fetch_nse_selenium()  +
        fetch_nse_csv()       +
        fetch_trendlyne()     +
        fetch_moneycontrol()  +
        fetch_scanx()
    )

    unique = {}
    for d in all_deals:
        h = deal_hash(d)
        if h not in unique:
            unique[h] = d

    new_deals = []
    for h, d in unique.items():
        if h not in seen_hashes:
            seen_hashes.add(h)
            new_deals.append(d)

    if new_deals:
        log.info(f'{len(new_deals)} NEW deals found!')
        for d in new_deals:
            val = d['qty'] * d['price'] / 1e7
            log.info(f"  [{d['dtype'].upper()}] {d['action']} {d['stock']} | {d['entity']} | ₹{d['price']:.2f} | ₹{val:.2f}Cr | {d.get('source')}")
        send_telegram(new_deals)
        send_email(new_deals)
    else:
        log.info('No new deals this cycle')

def main():
    log.info('Block/Bulk Deal Scanner v3 started')
    log.info(f'Sources: NSE + NSE CSV + Trendlyne + Moneycontrol + scanx.trade')
    log.info(f'Telegram: {"OK" if TELEGRAM_TOKEN else "NOT SET"} | Email: {"OK" if EMAIL_FROM else "NOT SET"}')

    # GitHub Actions mode: single scan, no loop
    # Local mode (REFRESH_MINUTES set): loop with sleep
    github_mode = os.getenv('GITHUB_ACTIONS', 'false') == 'true'

    if github_mode:
        # Single scan — GitHub cron handles scheduling
        log.info('Mode: GitHub Actions (single scan)')
        now = datetime.now()
        is_market = (now.weekday() < 5) and (9 <= now.hour < 16 or (now.hour == 16 and now.minute <= 30))
        if is_market:
            scan_once()
        else:
            log.info(f'Market closed ({now.strftime("%a %H:%M IST")}), skipping')
    else:
        # Local PC mode: loop every 30 min
        log.info(f'Mode: Local PC (refresh every {REFRESH_MINUTES} min)')
        while True:
            try:
                now = datetime.now()
                is_market = (now.weekday() < 5) and (9 <= now.hour < 16 or (now.hour == 16 and now.minute <= 30))
                if is_market:
                    scan_once()
                else:
                    log.info(f'Market closed ({now.strftime("%a %H:%M")}), skipping')
            except Exception as e:
                log.error(f'Scan error: {e}')
            log.info(f'Sleeping {REFRESH_MINUTES} min...')
            time.sleep(REFRESH_MINUTES * 60)

if __name__ == '__main__':
    main()
