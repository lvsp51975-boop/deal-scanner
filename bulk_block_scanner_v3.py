"""
Deal Levels Calculator — Entry / SL / TP
Extends Bulk & Block Deal Scanner v3
Sends enriched Telegram + Email with levels
"""

import os, time, logging, smtplib, json, hashlib
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('deallevels')

# ─── CONFIG ───────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
EMAIL_FROM       = os.getenv('EMAIL_FROM', '')
EMAIL_PASSWORD   = os.getenv('EMAIL_PASSWORD', '')
EMAIL_TO         = os.getenv('EMAIL_TO', '')
REFRESH_MINUTES  = int(os.getenv('REFRESH_MINUTES', '30'))

# ─── LEVEL CONFIG ─────────────────────────────────────────────────────────
LEVELS = {
    'block': {
        'sl_pct':  0.985,   # 1.5% SL — block = high conviction
        'tp1_pct': 1.05,
        'tp2_pct': 1.10,
        'tp3_pct': 1.25,    # wider TP3 for block
    },
    'bulk': {
        'sl_pct':  0.970,   # 3% SL — bulk = less conviction
        'tp1_pct': 1.05,
        'tp2_pct': 1.10,
        'tp3_pct': 1.18,
    },
}
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
    'NIVA BUPA','DIGIT INSURANCE','Sbi Mutual Fund','ABSLMF','NEW INDIA',
    'MOTILAL OSWAL','MOFSL','PPFAS','PARAG PARIKH',
]

ENTITY_TYPE = {
    'mf':      ['HDFC MF','SBI MF','ICICI PRU','AXIS MF','KOTAK MF','NIPPON MF','DSP MF',
                'MIRAE','FRANKLIN','ADITYA BIRLA','UTI MF','HDFC MUTUAL','TATA MF','EDELWEISS',
                'INVESCO','SUNDARAM MF','QUANTUM MF','CANARA MF','LIC MF','HSBC MF','PGIM MF',
                'BOI MF','Sbi Mutual Fund','ABSLMF','UNION MF'],
    'bank':    ['HDFC BANK','ICICI BANK','AXIS BANK','KOTAK BANK','STATE BANK','YES BANK',
                'INDUSIND','BANDHAN BANK','FEDERAL BANK','IDFC','RBL BANK'],
    'ins':     ['LIC','HDFC LIFE','ICICI LOMBARD','BAJAJ ALLIANZ','SBI LIFE','MAX LIFE',
                'KOTAK LIFE','TATA AIA','STAR HEALTH','CARE HEALTH','NIVA BUPA','DIGIT','NEW INDIA'],
    'motilal': ['MOTILAL OSWAL','MOFSL'],
    'ppfas':   ['PPFAS','PARAG PARIKH'],
}

seen_hashes = set()


# ─── HELPERS ──────────────────────────────────────────────────────────────

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


# ─── LEVEL CALCULATOR ─────────────────────────────────────────────────────

def calc_levels(deal: dict) -> dict:
    """
    Returns entry / SL / TP1 / TP2 / TP3 for a deal.

    Rules:
      - BUY deal  → standard long levels (SL below, TPs above)
      - SELL deal → flip: SL above entry, TPs below (institutional distribution)
      - Block deal → tighter SL (1.5%), higher TP3 (1.25x)
      - Bulk deal  → wider SL (3%),   lower TP3 (1.18x)
    """
    price  = deal['price']
    dtype  = deal.get('dtype', 'bulk').lower()
    action = deal.get('action', 'BUY').upper()

    cfg = LEVELS.get(dtype, LEVELS['bulk'])
    sl_pct  = cfg['sl_pct']
    tp1_pct = cfg['tp1_pct']
    tp2_pct = cfg['tp2_pct']
    tp3_pct = cfg['tp3_pct']

    entry = price

    if action == 'BUY':
        sl  = round(entry * sl_pct, 2)
        tp1 = round(entry * tp1_pct, 2)
        tp2 = round(entry * tp2_pct, 2)
        tp3 = round(entry * tp3_pct, 2)
        sl_pct_disp  = round((1 - sl_pct) * 100, 1)
        tp1_pct_disp = round((tp1_pct - 1) * 100, 1)
        tp2_pct_disp = round((tp2_pct - 1) * 100, 1)
        tp3_pct_disp = round((tp3_pct - 1) * 100, 1)
    else:
        # SELL → institutional distribution → fade the move
        sl  = round(entry / sl_pct,  2)   # SL above entry
        tp1 = round(entry / tp1_pct, 2)   # TP below entry
        tp2 = round(entry / tp2_pct, 2)
        tp3 = round(entry / tp3_pct, 2)
        sl_pct_disp  = round((1 - sl_pct) * 100, 1)
        tp1_pct_disp = round((tp1_pct - 1) * 100, 1)
        tp2_pct_disp = round((tp2_pct - 1) * 100, 1)
        tp3_pct_disp = round((tp3_pct - 1) * 100, 1)

    rr1 = round(abs(tp1 - entry) / abs(entry - sl), 2) if entry != sl else 0
    rr3 = round(abs(tp3 - entry) / abs(entry - sl), 2) if entry != sl else 0

    return {
        'entry': entry,
        'sl':    sl,
        'tp1':   tp1,
        'tp2':   tp2,
        'tp3':   tp3,
        'sl_pct':  sl_pct_disp,
        'tp1_pct': tp1_pct_disp,
        'tp2_pct': tp2_pct_disp,
        'tp3_pct': tp3_pct_disp,
        'rr1':   rr1,   # risk:reward at TP1
        'rr3':   rr3,   # risk:reward at TP3
    }


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
    opts.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


# ─── SOURCES (unchanged from v3) ──────────────────────────────────────────

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
            except Exception as e:
                log.warning(f'NSE {deal_type} selenium failed: {e}')
        driver.quit()
    except Exception as e:
        log.warning(f'NSE Selenium error: {e}')
    return deals


def fetch_nse_csv():
    deals = []
    try:
        today = date.today()
        date_str = today.strftime('%d%m%Y')
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.nseindia.com/'}
        for dtype in ['bulk', 'block']:
            url = f'https://archives.nseindia.com/corporate/{dtype}_deals_{date_str}.csv'
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
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
        for table in soup.find_all('table'):
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue
            headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th', 'td'])]
            sym_idx    = next((i for i, h in enumerate(headers) if h in ('stock','symbol','scrip')), 0)
            client_idx = next((i for i, h in enumerate(headers) if 'client' in h or h == 'name'), 1)
            type_idx   = next((i for i, h in enumerate(headers) if 'deal type' in h or h == 'type'), 3)
            bs_idx     = next((i for i, h in enumerate(headers) if h == 'action'), 4)
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
                    qty   = int(cols[qty_idx].replace(',','').replace('-','0')) if qty_idx < len(cols) else 0
                    price = float(cols[price_idx].replace(',','').replace('₹','').replace('-','0')) if price_idx < len(cols) else 0.0
                except:
                    qty, price = 0, 0.0
                dtype  = 'block' if 'block' in (cols[type_idx] if type_idx < len(cols) else '').lower() else 'bulk'
                bs_col = cols[bs_idx] if bs_idx < len(cols) else ''
                action = 'BUY' if 'B' in bs_col.upper() and 'S' not in bs_col.upper() else 'SELL'
                deals.append({
                    'stock': cols[sym_idx] if sym_idx < len(cols) else '',
                    'entity': entity, 'etype': classify_entity(entity),
                    'dtype': dtype, 'action': action, 'qty': qty, 'price': price,
                    'date': str(date.today()), 'source': 'Trendlyne',
                })
        driver.quit()
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
                driver.execute_script('window.scrollTo(0, 600)')
                time.sleep(2)
                soup = BeautifulSoup(driver.page_source, 'lxml')
                for table in soup.find_all('table'):
                    rows = table.find_all('tr')
                    if len(rows) < 2:
                        continue
                    headers = [th.get_text(strip=True).lower() for th in rows[0].find_all(['th','td'])]
                    if not any('symbol' in h or 'scrip' in h or 'stock' in h for h in headers):
                        continue
                    sym_idx    = next((i for i, h in enumerate(headers) if 'symbol' in h or 'scrip' in h or 'stock' in h), 0)
                    client_idx = next((i for i, h in enumerate(headers) if 'client' in h or 'name' in h), 1)
                    bs_idx     = next((i for i, h in enumerate(headers) if 'buy' in h or 'sell' in h or 'b/s' in h), 2)
                    qty_idx    = next((i for i, h in enumerate(headers) if 'qty' in h or 'quant' in h), 3)
                    price_idx  = next((i for i, h in enumerate(headers) if 'price' in h or 'rate' in h), 4)
                    for row in rows[1:]:
                        cols = [td.get_text(strip=True) for td in row.find_all('td')]
                        if len(cols) < 3:
                            continue
                        entity = cols[client_idx] if client_idx < len(cols) else ''
                        if not is_target(entity):
                            continue
                        try:
                            qty   = int(cols[qty_idx].replace(',','').replace('-','0')) if qty_idx < len(cols) else 0
                            price = float(cols[price_idx].replace(',','').replace('₹','').replace('-','0')) if price_idx < len(cols) else 0.0
                        except:
                            qty, price = 0, 0.0
                        bs_col = cols[bs_idx] if bs_idx < len(cols) else ''
                        action = 'BUY' if 'B' in bs_col.upper() and 'SELL' not in bs_col.upper() else 'SELL'
                        deals.append({
                            'stock': cols[sym_idx] if sym_idx < len(cols) else '',
                            'entity': entity, 'etype': classify_entity(entity),
                            'dtype': deal_type, 'action': action, 'qty': qty, 'price': price,
                            'date': str(date.today()), 'source': 'Moneycontrol',
                        })
            except Exception as e:
                log.warning(f'Moneycontrol {deal_type} failed: {e}')
        driver.quit()
    except Exception as e:
        log.warning(f'Moneycontrol error: {e}')
    return deals


def fetch_scanx():
    deals = []
    try:
        session = requests.Session()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'application/json',
        }
        r = session.get('https://scanx.trade/api/bulk-block-deals', headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            raw = data.get('data', data.get('deals', data if isinstance(data, list) else []))
            for row in (raw if isinstance(raw, list) else []):
                entity = row.get('clientName', row.get('entity', row.get('client', '')))
                if not is_target(entity):
                    continue
                deals.append({
                    'stock':  row.get('symbol', row.get('stock', '')),
                    'entity': entity, 'etype': classify_entity(entity),
                    'dtype':  'block' if 'block' in str(row.get('dealType','')).lower() else 'bulk',
                    'action': 'BUY' if 'B' in str(row.get('buySell', row.get('action',''))).upper() else 'SELL',
                    'qty':    int(row.get('quantity', row.get('qty', 0))),
                    'price':  float(row.get('tradePrice', row.get('price', 0))),
                    'date':   str(row.get('date', date.today())),
                    'source': 'scanx',
                })
    except Exception as e:
        log.warning(f'scanx error: {e}')
    return deals


# ─── ALERTS ───────────────────────────────────────────────────────────────

def send_telegram(deals_with_levels):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    icons = {'mf': '🏦', 'bank': '🏛', 'ins': '🛡', 'motilal': '📈', 'ppfas': '🟣'}
    lines = [f"📊 *Block/Bulk Deal Alert* — {date.today().strftime('%d %b %Y')}\n"]

    for item in deals_with_levels:
        d  = item['deal']
        lv = item['levels']
        icon = icons.get(d['etype'], '💼')
        act  = '🟢 BUY' if d['action'] == 'BUY' else '🔴 SELL'
        val  = d['qty'] * d['price'] / 1e7
        src  = d.get('source', '')

        lines.append(
            f"{icon} *{d['stock']}* [{d['dtype'].upper()}]\n"
            f"  {act} | {d['entity']}\n"
            f"  Deal: ₹{d['price']:,.2f} × {d['qty']//1000}K = ₹{val:.1f} Cr\n"
            f"  ┌ Entry : ₹{lv['entry']:,.2f}\n"
            f"  ├ SL    : ₹{lv['sl']:,.2f}  (-{lv['sl_pct']}%)\n"
            f"  ├ TP1   : ₹{lv['tp1']:,.2f}  (+{lv['tp1_pct']}%)  R:R {lv['rr1']}\n"
            f"  ├ TP2   : ₹{lv['tp2']:,.2f}  (+{lv['tp2_pct']}%)\n"
            f"  └ TP3   : ₹{lv['tp3']:,.2f}  (+{lv['tp3_pct']}%)  R:R {lv['rr3']}\n"
            f"  _src: {src}_\n"
        )

    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': '\n'.join(lines), 'parse_mode': 'Markdown'},
            timeout=10
        ).raise_for_status()
        log.info(f'Telegram: {len(deals_with_levels)} deals sent')
    except Exception as e:
        log.error(f'Telegram failed: {e}')


def send_email(deals_with_levels):
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        return
    today = date.today().strftime('%d %b %Y')
    rows = ''
    for item in deals_with_levels:
        d  = item['deal']
        lv = item['levels']
        val = d['qty'] * d['price'] / 1e7
        c   = '#2ecc71' if d['action'] == 'BUY' else '#e74c3c'
        rows += (
            f"<tr>"
            f"<td><b>{d['stock']}</b></td>"
            f"<td>{d['entity']}</td>"
            f"<td>{d['dtype'].upper()}</td>"
            f"<td style='color:{c};font-weight:bold'>{d['action']}</td>"
            f"<td>₹{d['price']:,.2f}</td>"
            f"<td>{d['qty']//1000}K</td>"
            f"<td>₹{val:.2f} Cr</td>"
            # levels
            f"<td style='color:#555'>₹{lv['entry']:,.2f}</td>"
            f"<td style='color:#e74c3c'>₹{lv['sl']:,.2f}<br><small>-{lv['sl_pct']}%</small></td>"
            f"<td style='color:#27ae60'>₹{lv['tp1']:,.2f}<br><small>+{lv['tp1_pct']}%</small></td>"
            f"<td style='color:#27ae60'>₹{lv['tp2']:,.2f}<br><small>+{lv['tp2_pct']}%</small></td>"
            f"<td style='color:#1abc9c'>₹{lv['tp3']:,.2f}<br><small>+{lv['tp3_pct']}%</small></td>"
            f"<td style='color:#888;font-size:11px'>R:R {lv['rr1']} / {lv['rr3']}</td>"
            f"<td style='color:#aaa;font-size:11px'>{d.get('source','')}</td>"
            f"</tr>"
        )
    html = f"""<html><body style='font-family:Arial;font-size:13px'>
    <h2>📊 Block/Bulk Deal Alert — {today}</h2>
    <p>{len(deals_with_levels)} new deal(s) — MF / Bank / Insurance / Motilal / PPFAS</p>
    <p style='color:#888;font-size:12px'>
      ⚠️ Levels = institutional deal price as entry. Not financial advice.
    </p>
    <table border='1' cellpadding='6' style='border-collapse:collapse;font-size:12px'>
    <tr style='background:#f0f0f0'>
      <th>Stock</th><th>Entity</th><th>Type</th><th>Action</th>
      <th>Deal Price</th><th>Qty</th><th>Value</th>
      <th>Entry</th><th>SL</th><th>TP1</th><th>TP2</th><th>TP3</th>
      <th>R:R (1/3)</th><th>Source</th>
    </tr>
    {rows}
    </table>
    <br>
    <table border='1' cellpadding='5' style='border-collapse:collapse;font-size:11px;color:#555;background:#fafafa'>
    <tr><th colspan='2'>Level Logic</th></tr>
    <tr><td>Entry</td><td>= institutional deal price</td></tr>
    <tr><td>Block SL</td><td>1.5% below entry (high conviction)</td></tr>
    <tr><td>Bulk SL</td><td>3.0% below entry</td></tr>
    <tr><td>TP1</td><td>+5% | TP2 +10% | Block TP3 +25% | Bulk TP3 +18%</td></tr>
    <tr><td>SELL deals</td><td>SL above, TPs below (fade distribution)</td></tr>
    </table>
    <p style='color:#aaa;font-size:11px'>Sources: NSE · NSE CSV · Trendlyne · Moneycontrol · scanx.trade</p>
    </body></html>"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'🔔 {len(deals_with_levels)} New Deals + Levels — {today}'
        msg['From']    = EMAIL_FROM
        msg['To']      = EMAIL_TO
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
            s.login(EMAIL_FROM, EMAIL_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info(f'Email sent to {EMAIL_TO}')
    except Exception as e:
        log.error(f'Email failed: {e}')


# ─── MAIN LOOP ────────────────────────────────────────────────────────────

def scan_once():
    log.info('=== Scanning: NSE + NSE CSV + Trendlyne + Moneycontrol + scanx ===')
    all_deals = (
        fetch_nse_selenium()  +
        fetch_nse_csv()       +
        fetch_trendlyne()     +
        fetch_moneycontrol()  +
        fetch_scanx()
    )

    # deduplicate
    unique = {}
    for d in all_deals:
        h = deal_hash(d)
        if h not in unique:
            unique[h] = d

    # filter new
    new_deals = []
    for h, d in unique.items():
        if h not in seen_hashes:
            seen_hashes.add(h)
            new_deals.append(d)

    if not new_deals:
        log.info('No new deals this cycle')
        return

    # calc levels
    deals_with_levels = []
    for d in new_deals:
        lv = calc_levels(d)
        deals_with_levels.append({'deal': d, 'levels': lv})
        val = d['qty'] * d['price'] / 1e7
        log.info(
            f"[{d['dtype'].upper()}] {d['action']} {d['stock']} | {d['entity']}"
            f" | Deal ₹{d['price']:.2f} | Val ₹{val:.2f}Cr"
            f" | Entry ₹{lv['entry']:.2f} SL ₹{lv['sl']:.2f} TP1 ₹{lv['tp1']:.2f}"
            f" TP2 ₹{lv['tp2']:.2f} TP3 ₹{lv['tp3']:.2f}"
            f" | R:R {lv['rr1']} / {lv['rr3']} | {d.get('source')}"
        )

    log.info(f'{len(new_deals)} NEW deals found!')
    send_telegram(deals_with_levels)
    send_email(deals_with_levels)


def main():
    log.info('Deal Levels Scanner started')
    log.info(f'Refresh: {REFRESH_MINUTES}min | Telegram: {"OK" if TELEGRAM_TOKEN else "NOT SET"} | Email: {"OK" if EMAIL_FROM else "NOT SET"}')

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
        log.info(f'Sleeping {REFRESH_MINUTES}min...')
        time.sleep(REFRESH_MINUTES * 60)


if __name__ == '__main__':
    main()
