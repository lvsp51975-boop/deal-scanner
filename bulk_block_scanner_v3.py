"""
Bulk & Block Deal Scanner v3 - FINAL CLEAN
Sources: NSE Selenium + NSE CSV + Trendlyne + Moneycontrol + scanx.trade
Mon-Sat always scan | Telegram + Email alerts
"""

import os, time, logging, smtplib, json, hashlib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('bbscanner')

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
EMAIL_FROM       = os.getenv('EMAIL_FROM', '')
EMAIL_PASSWORD   = os.getenv('EMAIL_PASSWORD', '')
EMAIL_TO         = os.getenv('EMAIL_TO', '')
REFRESH_MINUTES  = int(os.getenv('REFRESH_MINUTES', '30'))

TARGET_KEYWORDS = [
    'HDFC MF','SBI MF','SBI MUTUAL','ICICI PRU','AXIS MF','KOTAK MF','NIPPON MF',
    'DSP MF','MIRAE','FRANKLIN','ADITYA BIRLA','BIRLA SUN LIFE','ADITYA BIRLA SUN',
    'UTI MF','TATA MF','EDELWEISS','INVESCO','SUNDARAM MF','QUANTUM MF','CANARA MF',
    'LIC MF','HSBC MF','PGIM MF','BOI MF','UNION MF','HDFC MUTUAL',
    'PARAG PARIKH','PPFAS','PPFCF','MOTILAL OSWAL','MOFSL','MOMF','MOAMC','WHITEOAK',
    'QUANT MUTUAL','GROWW MF','NAVI MF','ZERODHA MF','MUTUAL FUND',
    'HDFC BANK','ICICI BANK','AXIS BANK','KOTAK BANK','STATE BANK','YES BANK',
    'INDUSIND','BANDHAN BANK','FEDERAL BANK','IDFC','RBL BANK',
    'CANARA BANK','UNION BANK','BANK OF BARODA','BANK OF INDIA','PNB',
    'LIC','LIFE INSURANCE','INSURANCE','BAJAJ ALLIANZ','SBI LIFE',
    'MAX LIFE','HDFC LIFE','KOTAK LIFE','TATA AIA','STAR HEALTH',
    'CARE HEALTH','NIVA BUPA','DIGIT INSURANCE','NEW INDIA','GIC',
    'MORGAN STANLEY','GOLDMAN SACHS','JPMORGAN','BLACKROCK','GQG',
    'TEMPLETON','SOCIETE GENERALE','NOMURA','MERRILL LYNCH',
]

ENTITY_TYPE = {
    'mf':   ['MUTUAL FUND','SBI MF','HDFC MF','ICICI PRU','AXIS MF','KOTAK MF','NIPPON MF',
             'DSP MF','MIRAE','FRANKLIN','ADITYA BIRLA','BIRLA SUN LIFE','UTI MF','TATA MF',
             'EDELWEISS','INVESCO','SUNDARAM MF','QUANTUM MF','CANARA MF','LIC MF','HSBC MF',
             'PGIM MF','BOI MF','UNION MF','HDFC MUTUAL','PPFAS','PPFCF','PARAG PARIKH',
             'MOTILAL OSWAL','MOFSL','MOMF','MOAMC','WHITEOAK','QUANT MUTUAL','SBI MUTUAL'],
    'bank': ['BANK','HDFC BANK','ICICI BANK','AXIS BANK','KOTAK BANK','STATE BANK',
             'YES BANK','INDUSIND','BANDHAN','FEDERAL BANK','IDFC','RBL BANK',
             'CANARA BANK','UNION BANK','BANK OF BARODA','BANK OF INDIA','PNB'],
    'ins':  ['LIC','LIFE INSURANCE','INSURANCE','BAJAJ ALLIANZ','SBI LIFE','MAX LIFE',
             'HDFC LIFE','KOTAK LIFE','TATA AIA','STAR HEALTH','CARE HEALTH',
             'NIVA BUPA','DIGIT','NEW INDIA','GIC'],
    'fii':  ['MORGAN STANLEY','GOLDMAN SACHS','JPMORGAN','BLACKROCK','GQG',
             'TEMPLETON','SOCIETE GENERALE','NOMURA','MERRILL LYNCH'],
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

def get_scan_dates():
    today = date.today()
    dates = []
    for i in range(6):
        d = today - timedelta(days=i)
        if d.weekday() != 6:
            dates.append(d)
    return dates

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
    opts.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def fetch_nse_selenium():
    deals = []
    try:
        from selenium.webdriver.common.by import By
        driver = get_driver()
        for scan_date in get_scan_dates():
            date_str = scan_date.strftime('%d-%m-%Y')
            for deal_type in ['bulk', 'block']:
                try:
                    driver.get('https://www.nseindia.com')
                    time.sleep(3)
                    url = f'https://www.nseindia.com/api/{deal_type}-deals?from={date_str}&to={date_str}'
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
                            'date':   date_str,
                            'source': 'NSE',
                        })
                except Exception as e:
                    log.warning(f'NSE {deal_type} {date_str} selenium failed: {e}')
        driver.quit()
    except Exception as e:
        log.warning(f'NSE Selenium error: {e}')
    return deals

def fetch_nse_csv():
    deals = []
    try:
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.nseindia.com/'}
        for scan_date in get_scan_dates():
            date_str = scan_date.strftime('%d%m%Y')
            for dtype in ['bulk', 'block']:
                url = f'https://archives.nseindia.com/corporate/{dtype}_deals_{date_str}.csv'
                try:
                    r = requests.get(url, headers=headers, timeout=15)
                    if r.status_code != 200:
                        log.warning(f'CSV {dtype} {date_str}: {r.status_code}')
                        continue
                    for line in r.text.strip().split('\n')[1:]:
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
                            'date':   scan_date.strftime('%d-%m-%Y'),
                            'source': 'NSE CSV',
                        })
                except Exception as e:
                    log.warning(f'NSE CSV {dtype} {date_str}: {e}')
    except Exception as e:
        log.warning(f'NSE CSV error: {e}')
    return deals

def fetch_trendlyne():
    deals = []
    try:
        from selenium.webdriver.common.by import By
        driver = get_driver()
        driver.get('https://trendlyne.com/portfolio/bulk-block-deals/')
        time.sleep(5)
        driver.execute_script('window.scrollTo(0, 500)')
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, 'lxml')
        tables = soup.find_all('table')
        log.info(f'Trendlyne: {len(tables)} tables found')
        for table in tables:
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th','td'])]
            sym_idx    = next((i for i,h in enumerate(headers) if h in ('stock','symbol','scrip')), 0)
            client_idx = next((i for i,h in enumerate(headers) if 'client' in h or h == 'name'), 1)
            type_idx   = next((i for i,h in enumerate(headers) if 'deal type' in h or h == 'type'), 3)
            bs_idx     = next((i for i,h in enumerate(headers) if h == 'action' or ('buy' in h and 'sell' not in h)), 4)
            price_idx  = next((i for i,h in enumerate(headers) if 'price' in h or 'avg' in h), 6)
            qty_idx    = next((i for i,h in enumerate(headers) if 'quantity' in h or 'qty' in h), 7)
            for row in rows[1:]:
                cols = [td.get_text(strip=True) for td in row.find_all('td')]
                if len(cols) < 4:
                    continue
                entity = cols[client_idx] if client_idx < len(cols) else ''
                if not is_target(entity):
                    continue
                try:
                    qty   = int(cols[qty_idx].replace(',','').replace('-','0')) if qty_idx < len(cols) else 0
                    price = float(cols[price_idx].replace(',','').replace('-','0')) if price_idx < len(cols) else 0.0
                except:
                    qty, price = 0, 0.0
                dtype  = 'block' if 'block' in (cols[type_idx] if type_idx < len(cols) else '').lower() else 'bulk'
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
        driver.quit()
        log.info(f'Trendlyne: {len(deals)} target deals')
    except Exception as e:
        log.warning(f'Trendlyne error: {e}')
    return deals

def fetch_moneycontrol():
    deals = []
    try:
        from selenium.webdriver.common.by import By
        driver = get_driver()
        driver.get('https://www.moneycontrol.com')
        time.sleep(2)
        for deal_type, url in [
            ('bulk',  'https://www.moneycontrol.com/stocks/marketinfo/bulk_deals/index.php'),
            ('block', 'https://www.moneycontrol.com/stocks/marketinfo/block_deals/index.php'),
        ]:
            try:
                driver.get(url)
                time.sleep(3)
                soup = BeautifulSoup(driver.page_source, 'lxml')
                for table in soup.find_all('table'):
                    rows = table.find_all('tr')
                    if len(rows) < 2:
                        continue
                    headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th','td'])]
                    if not any('symbol' in h or 'scrip' in h or 'stock' in h for h in headers):
                        continue
                    sym_idx    = next((i for i,h in enumerate(headers) if 'symbol' in h or 'scrip' in h or 'stock' in h), 0)
                    client_idx = next((i for i,h in enumerate(headers) if 'client' in h or 'name' in h), 1)
                    bs_idx     = next((i for i,h in enumerate(headers) if 'buy' in h or 'sell' in h or 'b/s' in h), 2)
                    qty_idx    = next((i for i,h in enumerate(headers) if 'qty' in h or 'quant' in h), 3)
                    price_idx  = next((i for i,h in enumerate(headers) if 'price' in h or 'rate' in h), 4)
                    for row in rows[1:]:
                        cols = [td.get_text(strip=True) for td in row.find_all('td')]
                        if len(cols) < 3:
                            continue
                        entity = cols[client_idx] if client_idx < len(cols) else ''
                        if not is_target(entity):
                            continue
                        try:
                            qty   = int(cols[qty_idx].replace(',','').replace('-','0')) if qty_idx < len(cols) else 0
                            price = float(cols[price_idx].replace(',','').replace('-','0')) if price_idx < len(cols) else 0.0
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
                log.warning(f'Moneycontrol {deal_type} failed: {e}')
        driver.quit()
        log.info(f'Moneycontrol: {len(deals)} target deals')
    except Exception as e:
        log.warning(f'Moneycontrol error: {e}')
    return deals

def fetch_scanx():
    deals = []
    try:
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
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
                        'dtype':  'block' if 'block' in str(row.get('dealType','')).lower() else 'bulk',
                        'action': 'BUY' if 'B' in str(row.get('buySell', row.get('action',''))).upper() else 'SELL',
                        'qty':    int(row.get('quantity', row.get('qty', 0))),
                        'price':  float(row.get('tradePrice', row.get('price', 0))),
                        'date':   str(row.get('date', date.today())),
                        'source': 'scanx',
                    })
            except:
                pass
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

# ─── TELEGRAM - NO PARSE_MODE, NO SPECIAL CHARS ───────────────────────────
def send_telegram(deals):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning('Telegram: NOT SET')
        return
    icons = {'mf':'[MF]','bank':'[BANK]','ins':'[INS]','fii':'[FII]'}
    lines = [f"Block/Bulk Deal Alert - {date.today().strftime('%d %b %Y')}"]
    lines.append(f"Total: {len(deals)} new deals")
    lines.append("")
    for d in deals:
        icon = icons.get(d['etype'], '[OTHER]')
        act  = 'BUY' if d['action'] == 'BUY' else 'SELL'
        val  = d['qty'] * d['price'] / 1e7
        lines.append(
            f"{icon} {d['stock']} [{d['dtype'].upper()}] {d.get('date','')}\n"
            f"  {act} | {d['entity']}\n"
            f"  Price: {d['price']:,.2f} | Qty: {d['qty']//1000}K | Val: {val:.1f}Cr\n"
            f"  src: {d.get('source','')}\n"
        )
    msg = '\n'.join(lines)
    chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
    try:
        for chunk in chunks:
            r = requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
                json={'chat_id': TELEGRAM_CHAT_ID, 'text': chunk},
                timeout=10
            )
            if r.status_code == 200:
                log.info(f'Telegram: sent OK')
            else:
                log.error(f'Telegram failed: {r.status_code} {r.text}')
    except Exception as e:
        log.error(f'Telegram error: {e}')

def send_email(deals):
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        return
    today = date.today().strftime('%d %b %Y')
    rows = ''
    for d in deals:
        val = d['qty'] * d['price'] / 1e7
        c   = '#2ecc71' if d['action'] == 'BUY' else '#e74c3c'
        rows += (
            f"<tr><td>{d.get('date','')}</td><td>{d['stock']}</td><td>{d['entity']}</td>"
            f"<td>{d['dtype'].upper()}</td>"
            f"<td style='color:{c};font-weight:bold'>{d['action']}</td>"
            f"<td>{d['price']:,.2f}</td><td>{d['qty']//1000}K</td>"
            f"<td>{val:.2f} Cr</td><td>{d.get('source','')}</td></tr>"
        )
    html = f"""<html><body style='font-family:Arial'>
    <h2>Block/Bulk Deal Alert - {today}</h2>
    <p>{len(deals)} new deals - MF / Bank / Insurance / FII</p>
    <table border='1' cellpadding='6' style='border-collapse:collapse;font-size:13px'>
    <tr style='background:#f0f0f0'><th>Date</th><th>Stock</th><th>Entity</th><th>Type</th>
    <th>Action</th><th>Price</th><th>Qty</th><th>Value</th><th>Source</th></tr>
    {rows}</table>
    </body></html>"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'New Block/Bulk Deals - {today}'
        msg['From']    = EMAIL_FROM
        msg['To']      = EMAIL_TO
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(EMAIL_FROM, EMAIL_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info(f'Email sent to {EMAIL_TO}')
    except Exception as e:
        log.error(f'Email failed: {e}')

def scan_once():
    log.info('=== Scanning: NSE + Trendlyne + Moneycontrol + scanx ===')
    all_deals = (
        fetch_nse_selenium() +
        fetch_nse_csv()      +
        fetch_trendlyne()    +
        fetch_moneycontrol() +
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
            log.info(f"  [{d['dtype'].upper()}] {d['action']} {d['stock']} | {d['entity']} | {d['price']:.2f} | {val:.2f}Cr | {d.get('date')} | {d.get('source')}")
        send_telegram(new_deals)
        send_email(new_deals)
    else:
        log.info('No new deals this cycle')

def main():
    log.info('Block/Bulk Deal Scanner v3 started')
    log.info(f'Sources: NSE + NSE CSV + Trendlyne + Moneycontrol + scanx.trade')
    log.info(f'Mode: Mon-Sat always scan | Telegram: {"OK" if TELEGRAM_TOKEN else "NOT SET"} | Email: {"OK" if EMAIL_FROM else "NOT SET"}')
    while True:
        try:
            now = datetime.now()
            if now.weekday() == 6:
                log.info('Sunday - skipping. Will resume Monday.')
            else:
                log.info(f'Scanning... ({now.strftime("%a %H:%M")})')
                scan_once()
        except Exception as e:
            log.error(f'Scan error: {e}')
        log.info(f'Sleeping {REFRESH_MINUTES} min...')
        time.sleep(REFRESH_MINUTES * 60)

if __name__ == '__main__':
    main()
