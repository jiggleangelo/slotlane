import hashlib
import html
import json
import os
import secrets
import sys
import threading
import time
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from .clicks import ClickValidator
from .demo_agent import organic_answer
from .service import AdNetwork, parse_money
from .taxonomy import CATEGORIES


BANNER = 'Demo operated by AI agents. Made-up data. Do not enter real personal data. Nothing is charged.'
CSS = 'body{font:16px system-ui;max-width:900px;margin:auto;padding:1rem}nav a{margin-right:1rem}.banner{background:#fff3b0;padding:12px;border:2px solid #8a6d00}.card,.sponsored{border:1px solid #aaa;padding:14px;margin:14px 0}.sponsored{border:3px solid #6941c6}input,select,textarea{display:block;margin:.3rem 0 1rem;padding:.5rem;min-width:24rem}button{padding:.6rem 1rem}.ok{background:#e5fae5;padding:10px}.bad{background:#ffe5e5;padding:10px}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:6px}code{overflow-wrap:anywhere}'
RESULTS = {'billable', 'duplicate', 'expired', 'bad_sig', 'unknown_impression', 'rate_limited', 'zero_balance', 'prefetch_ignored', 'unknown_campaign'}
MAX_CREATION_KEYS = 4096
DEFAULT_CONNECTION_LIMIT = 32


def esc(value):
    return html.escape(str(value), quote=True)


def money(cents):
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f'{sign}${cents // 100}.{cents % 100:02d}'


def layout(title, body):
    return f"<!doctype html><html><head><meta charset=utf-8><title>{esc(title)} · Slotwise</title><style>{CSS}</style></head><body><div class=banner>{BANNER}</div><h1>Slotwise</h1><nav><a href='/'>Walkthrough</a><a href='/advertiser'>Advertiser</a><a href='/agent'>Agent</a><a href='/publisher'>Publisher</a><a href='/ledger'>Ledger</a><a href='/rates'>Rates</a></nav><main><h2>{esc(title)}</h2>{body}</main></body></html>"


class SessionLimit(Exception):
    pass


class Sessions:
    def __init__(self, maximum=200, ttl=3600, per_ip_limit=20, creation_window=3600, clock=time.monotonic, maximum_creation_keys=MAX_CREATION_KEYS):
        self.maximum = maximum
        self.ttl = ttl
        self.per_ip_limit = per_ip_limit
        self.creation_window = creation_window
        self.clock = clock
        self.maximum_creation_keys = maximum_creation_keys
        self.items = OrderedDict()
        self.creations = {}
        self.click_recent = {}
        self.click_rate_lock = threading.Lock()
        self.lock = threading.RLock()
        self._creation_salt = secrets.token_bytes(32)

    def _client_key(self, client_ip):
        value = client_ip if isinstance(client_ip, str) else ''
        return hashlib.sha256(self._creation_salt + value.encode('utf-8', 'replace')).hexdigest()

    def _purge(self, now):
        expired = [sid for sid, (_, touched, _) in self.items.items() if touched <= now - self.ttl]
        for sid in expired:
            self.items.pop(sid, None)

    def _trim_creations(self, now):
        cutoff = now - self.creation_window
        for key, recent in list(self.creations.items()):
            while recent and recent[0] <= cutoff:
                recent.popleft()
            if not recent:
                del self.creations[key]

    def get(self, sid=None, client_ip='local'):
        now = self.clock()
        with self.lock:
            self._purge(now)
            if sid and sid in self.items:
                network, _, owner = self.items[sid]
                self.items[sid] = (network, now, owner)
                self.items.move_to_end(sid)
                return sid, network
            self._trim_creations(now)
            owner = self._client_key(client_ip)
            recent = self.creations.get(owner)
            if recent is None:
                if len(self.creations) >= self.maximum_creation_keys:
                    raise SessionLimit
                recent = deque()
                self.creations[owner] = recent
            if len(recent) >= self.per_ip_limit:
                raise SessionLimit
            recent.append(now)
            sid = secrets.token_urlsafe(24)
            network = AdNetwork(shared_recent=self.click_recent, shared_rate_lock=self.click_rate_lock)
            self.items[sid] = (network, now, owner)
            while len(self.items) > self.maximum:
                self.items.popitem(last=False)
            return sid, network

    def reset(self, sid):
        now = self.clock()
        with self.lock:
            old = self.items.get(sid)
            owner = old[2] if old else self._client_key('local')
            network = AdNetwork(shared_recent=self.click_recent, shared_rate_lock=self.click_rate_lock)
            self.items[sid] = (network, now, owner)
            self.items.move_to_end(sid)
            return network

    def publisher_for_key(self, key):
        now = self.clock()
        with self.lock:
            self._purge(now)
            for sid, (network, _, owner) in list(self.items.items()):
                publisher = network.publisher_for_key(key)
                if publisher:
                    self.items[sid] = (network, now, owner)
                    self.items.move_to_end(sid)
                    return network, publisher
        return None, None

    def network_for_click(self, token):
        impression_id = ClickValidator.impression_id(token)
        if not impression_id:
            return None
        now = self.clock()
        with self.lock:
            self._purge(now)
            for sid, (network, _, owner) in list(self.items.items()):
                if impression_id in network.impressions:
                    self.items[sid] = (network, now, owner)
                    self.items.move_to_end(sid)
                    return network
        return None


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, connection_limit=DEFAULT_CONNECTION_LIMIT):
        if connection_limit < 1:
            raise ValueError('connection_limit must be positive')
        self.connection_limit = connection_limit
        self._connection_slots = threading.BoundedSemaphore(connection_limit)
        super().__init__(server_address, handler_class)

    def process_request(self, request, client_address):
        if not self._connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()

    def handle_error(self, request, client_address):
        print('Slotwise request handler error', file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    sessions = Sessions()
    server_version = 'Slotwise'
    timeout = 10

    def log_message(self, format, *args):
        pass

    def client_ip(self):
        if getattr(self.server, 'trust_proxy', False):
            forwarded = self.headers.get('X-Forwarded-For', '').split(',', 1)[0].strip()
            if forwarded:
                return forwarded
        return self.client_address[0]

    def session(self):
        cookies = {}
        for part in self.headers.get('Cookie', '').split(';'):
            if '=' in part:
                key, value = part.strip().split('=', 1)
                cookies[key] = value
        self._sid, self.network = self.sessions.get(cookies.get('sid'), self.client_ip())

    def is_https(self):
        if getattr(self.server, 'trust_proxy', False) and self.headers.get('X-Forwarded-Proto', '').casefold() == 'https':
            return True
        return urlsplit(self.server.public_base_url).scheme == 'https'

    def cookie_value(self):
        secure = '; Secure' if self.is_https() else ''
        return f'sid={self._sid}; Path=/; HttpOnly; SameSite=Lax{secure}'

    def send_headers(self, status=200, content_type='text/html; charset=utf-8', length=None, cookie=True):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        if cookie and hasattr(self, '_sid'):
            self.send_header('Set-Cookie', self.cookie_value())
        if length is not None:
            self.send_header('Content-Length', str(length))
        self.end_headers()

    def send_bytes(self, data, status=200, content_type='text/html; charset=utf-8', cookie=True):
        if isinstance(data, str):
            data = data.encode()
        self.send_headers(status, content_type, len(data), cookie)
        if self.command != 'HEAD':
            self.wfile.write(data)

    def redirect(self, location, status=303, cookie=True):
        self.send_response(status)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        if cookie and hasattr(self, '_sid'):
            self.send_header('Set-Cookie', self.cookie_value())
        self.end_headers()

    def valid_host(self):
        return self.headers.get('Host', '') in self.server.allowed_hosts

    def csrf_field(self):
        return f"<input type=hidden name=csrf value='{esc(self.network.csrf_token)}'>"

    def csrf_ok(self, form):
        origin = self.headers.get('Origin')
        if origin and origin.rstrip('/') != self.server.public_base_url.rstrip('/'):
            return False
        supplied = form.get('csrf', [''])[0]
        if supplied and secrets.compare_digest(supplied, self.network.csrf_token):
            return True
        browser_request = bool(origin or self.headers.get('Sec-Fetch-Site'))
        return not browser_request

    def read_body(self, cookie=True):
        raw = self.headers.get('Content-Length')
        if raw is None:
            self.send_bytes(layout('Length required', '<p>Content-Length is required.</p>'), 411, cookie=cookie)
            return None
        try:
            length = int(raw)
        except ValueError:
            self.send_bytes(layout('Bad request', '<p>Invalid Content-Length.</p>'), 400, cookie=cookie)
            return None
        if length < 0:
            self.send_bytes(layout('Bad request', '<p>Invalid Content-Length.</p>'), 400, cookie=cookie)
            return None
        if length > 65536:
            self.send_bytes(layout('Too large', '<p>Request bodies are limited to 64 KB.</p>'), 413, cookie=cookie)
            return None
        return self.rfile.read(length)

    def do_HEAD(self):
        try:
            path = urlsplit(self.path).path
            if path.startswith('/c/'):
                return self.send_bytes('', 204, 'text/plain', cookie=False)
            if path == '/healthz':
                return self.send_bytes('', 200, 'text/plain', cookie=False)
            return self.send_bytes('', 405, 'text/plain', cookie=False)
        except Exception:
            self.send_bytes('Internal server error', 500, 'text/plain', cookie=False)

    def do_GET(self):
        try:
            self._do_GET()
        except SessionLimit:
            self.send_bytes(layout('Too many sessions', '<p>Please retry later.</p>'), 429, cookie=False)
        except Exception:
            self.send_bytes(layout('Internal error', '<p>The request could not be completed.</p>'), 500, cookie=False)

    def _do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == '/healthz':
            return self.send_bytes('ok', content_type='text/plain', cookie=False)
        if not self.valid_host():
            return self.send_bytes('Bad Host', 400, 'text/plain', cookie=False)
        if path == '/api/v1/rates':
            return self.send_bytes(json.dumps(self.rates()), content_type='application/json', cookie=False)
        if path.startswith('/c/'):
            if self.headers.get('Purpose', '').casefold() == 'prefetch' or self.headers.get('Sec-Purpose', '').casefold() == 'prefetch' or self.headers.get('Sec-Fetch-Mode', 'navigate').casefold() != 'navigate':
                return self.redirect('/landing?ad=unknown&result=prefetch_ignored', 302, cookie=False)
            token = path[3:]
            network = self.sessions.network_for_click(token)
            result, campaign = network.click(token, self.client_ip()) if network else ('unknown_impression', None)
            target = '/landing?ad=' + quote(campaign.id if campaign else 'unknown') + '&result=' + quote(result)
            return self.redirect(target, 302, cookie=False)
        self.session()
        if path == '/':
            body = "<p>Try the complete flow in under three minutes.</p><ol><li><a href='/advertiser'>Top up and create an ad</a></li><li><a href='/agent'>Ask the coding agent and click the winner</a></li><li><a href='/publisher'>Inspect earnings and request a payout</a></li></ol>" + f"<form method=post action='/demo/reset'>{self.csrf_field()}<button>Reset my demo</button></form>"
        elif path == '/advertiser':
            body = self.advertiser()
        elif path == '/agent':
            body = self.agent()
        elif path == '/publisher':
            body = self.publisher()
        elif path == '/ledger':
            body = self.ledger_page()
        elif path == '/rates':
            body = '<dl>' + ''.join(f'<dt>{esc(k)}</dt><dd>{esc(v)}</dd>' for k, v in self.rates().items()) + '</dl>'
        elif path == '/landing':
            result = query.get('result', ['unknown'])[0]
            if result not in RESULTS:
                result = 'unknown'
            ad = query.get('ad', ['unknown'])[0]
            if not ad.startswith('cmp_'):
                ad = 'unknown'
            body = f'<p class=ok>Click result: {esc(result)}.</p><p>Campaign: {esc(ad)}.</p><p>In production this would open the reviewed advertiser URL. This demo never navigates off-site.</p>'
        else:
            return self.send_bytes(layout('Not found', '<p>Page not found.</p>'), 404)
        self.send_bytes(layout(path.strip('/').title() or 'Walkthrough', body))

    def do_POST(self):
        try:
            self._do_POST()
        except SessionLimit:
            self.send_bytes(layout('Too many sessions', '<p>Please retry later.</p>'), 429, cookie=False)
        except Exception:
            self.send_bytes(layout('Internal error', '<p>The request could not be completed.</p>'), 500, cookie=False)

    def _do_POST(self):
        path = urlsplit(self.path).path
        if not self.valid_host():
            return self.send_bytes('Bad Host', 400, 'text/plain', cookie=False)
        if path == '/api/v1/decide':
            body = self.read_body(cookie=False)
            if body is None:
                return
            try:
                data = json.loads(body)
            except (ValueError, TypeError, json.JSONDecodeError):
                return self.send_bytes(json.dumps({'error': 'invalid JSON'}), 400, 'application/json', cookie=False)
            if not isinstance(data, dict) or not isinstance(data.get('query'), str):
                return self.send_bytes(json.dumps({'error': 'invalid request'}), 400, 'application/json', cookie=False)
            if len(data['query']) > 500:
                return self.send_bytes(json.dumps({'error': 'query too large'}), 413, 'application/json', cookie=False)
            network, publisher = self.sessions.publisher_for_key(self.headers.get('X-Publisher-Key', ''))
            if not publisher:
                return self.send_bytes(json.dumps({'error': 'unauthorized'}), 401, 'application/json', cookie=False)
            result = network.decide(data['query'], publisher.id, self.server.public_base_url, self.client_ip())
            return self.send_bytes(json.dumps(result), content_type='application/json', cookie=False)
        self.session()
        body = self.read_body()
        if body is None:
            return
        try:
            form = parse_qs(body.decode('utf-8'), keep_blank_values=True, strict_parsing=False)
        except UnicodeDecodeError:
            return self.send_bytes(layout('Bad request', '<p>Invalid form data.</p>'), 400)
        if not self.csrf_ok(form):
            return self.send_bytes(layout('Forbidden', '<p>The form token or request origin was invalid.</p>'), 403)
        if path == '/demo/reset':
            self.network = self.sessions.reset(self._sid)
            return self.redirect('/')
        if path == '/advertiser/topup':
            try:
                self.network.topup(10_000)
            except ValueError:
                self.network.last_message = 'Top-up could not be completed.'
            return self.redirect('/advertiser')
        if path == '/advertiser/campaigns':
            try:
                self.network.create_campaign(
                    form.get('category', [''])[0],
                    parse_money(form.get('bid', [''])[0]),
                    parse_money(form.get('budget', [''])[0]),
                    form.get('title', [''])[0],
                    form.get('description', [''])[0],
                    form.get('url', [''])[0],
                )
            except ValueError:
                self.network.last_message = 'Campaign could not be created. Check the category, amounts, creative fields, and demo limits.'
            return self.redirect('/advertiser')
        if path == '/agent/ask':
            query = form.get('query', [''])[0]
            if len(query) > 500:
                return self.send_bytes(layout('Too large', '<p>Queries are limited to 500 characters.</p>'), 413)
            return self.send_bytes(layout('Agent', self.agent(query)))
        if path == '/publisher/payout':
            try:
                self.network.payout()
            except ValueError:
                self.network.last_message = 'Payout is unavailable until the $1.00 threshold is reached.'
            return self.redirect('/publisher')
        return self.send_bytes(layout('Not found', '<p>Page not found.</p>'), 404)

    @staticmethod
    def rates():
        return {
            'floor_cents': 100,
            'minimum_topup_cents': 10000,
            'payment_fee': '290 bps + 30 cents, charged on top; rounded half-up',
            'publisher_share_percent': 70,
            'auction': 'one-slot second-price CPC',
            'clicks': 'signed, expire after 30 minutes, one billable click per impression, fewer than 5 billable clicks/minute/publisher; charge min(price,balance)',
        }

    def advertiser(self):
        message = f'<p class=ok>{esc(self.network.last_message)}</p>' if self.network.last_message else ''
        options = ''.join(f"<option value='{esc(category)}'>{esc(category)}</option>" for category in CATEGORIES)
        campaigns = ''.join(
            f'<tr><td>{esc(c.id)}</td><td>{esc(c.category)}</td><td>{money(c.bid_cents)}</td><td>{money(c.spent_cents)} / {money(c.budget_cents)}</td><td>{esc(c.creative.status)}</td><td>{esc(c.status)}</td></tr>'
            for c in self.network.campaigns.values() if c.advertiser_id == 'you'
        )
        return message + f"<p>Balance: <strong>{money(self.network.advertiser_balance())}</strong></p><form method=post action='/advertiser/topup'>{self.csrf_field()}<button>Fake top-up $100</button></form><h3>Create campaign</h3><form method=post action='/advertiser/campaigns'>{self.csrf_field()}<label>Category<select name=category>{options}</select></label><label>Bid in dollars<input name=bid value='1.00' required></label><label>Budget in dollars<input name=budget value='10.00' required></label><label>Title<input name=title maxlength=60 required></label><label>Description<textarea name=description maxlength=140 required></textarea></label><label>HTTPS destination URL<input name=url value='https://advertiser.example' maxlength=200 required></label><button>Create campaign</button></form><h3>Your campaigns</h3><table><tr><th>ID</th><th>Category</th><th>Bid</th><th>Spend / budget</th><th>Review</th><th>Delivery</th></tr>{campaigns}</table>"

    def agent(self, query=''):
        result_html = ''
        if query:
            answer, organic = organic_answer(query)
            decision = self.network.decide(query, host=self.server.public_base_url, client_ip=self.client_ip())
            organic_html = '<ul>' + ''.join(f'<li>{esc(item)}</li>' for item in organic) + '</ul>'
            sponsored = '<p>No eligible sponsored placement.</p>'
            if decision['items']:
                item = decision['items'][0]
                impression = self.network.impressions[item['impression_id']]
                sponsored = f"<div class=sponsored><strong>Sponsored</strong><p>{esc(decision['disclosure'])}</p><h3>{esc(item['title'])}</h3><p>{esc(item['description'])}</p><p>Advertiser: {esc(item['advertiser'])}</p><a href='{esc(item['click_url'])}'>Visit sponsor</a><p>You won at {money(impression.price_cents)}.</p></div>"
            result_html = f'<div class=card><p><strong>Question:</strong> {esc(query)}</p><p>{esc(answer)}</p>{organic_html}</div>{sponsored}'
        return f"<form method=post action='/agent/ask'>{self.csrf_field()}<label>Ask about a developer tool<input name=query maxlength=500 required></label><button>Ask</button></form>{result_html}"

    def publisher(self):
        key = self.network.issue_publisher_key_once()
        key_html = f'<div class=ok><p>Your publisher API key is shown once. Save it now:</p><code>{esc(key)}</code></div>' if key else '<p>The publisher API key was already shown. Reset the demo to issue a new one.</p>'
        invalid = ''.join(f'<tr><td>{esc(reason)}</td><td>{count}</td></tr>' for reason, count in sorted(self.network.clicks.invalid.items())) or '<tr><td colspan=2>None</td></tr>'
        return key_html + f"<p>Publisher balance: <strong>{money(self.network.publisher_balance())}</strong></p><p>Valid clicks: {self.network.stats['valid_clicks']}; advertiser spend: {money(self.network.stats['spend'])}</p><form method=post action='/publisher/payout'>{self.csrf_field()}<button>Request fake payout</button></form><h3>Invalid click counters</h3><table><tr><th>Reason</th><th>Count</th></tr>{invalid}</table>"

    def ledger_page(self):
        rows = []
        for transaction in self.network.ledger.transactions:
            for account, amount in transaction.entries:
                rows.append(f'<tr><td>{esc(transaction.kind)}</td><td>{esc(account)}</td><td>{amount}</td><td>{money(amount)}</td><td>{esc(transaction.ref)}</td></tr>')
        total = sum(amount for transaction in self.network.ledger.transactions for _, amount in transaction.entries)
        return f"<p>Ledger invariant total: {total} cents.</p><table><tr><th>Kind</th><th>Account</th><th>Cents</th><th>Amount</th><th>Reference</th></tr>{''.join(rows)}</table>"


def make_server(host='127.0.0.1', port=8080, connection_limit=DEFAULT_CONNECTION_LIMIT):
    server = QuietThreadingHTTPServer((host, port), Handler, connection_limit)
    configured = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
    if configured:
        parsed = urlsplit(configured)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path not in ('', '/'):
            server.server_close()
            raise ValueError('PUBLIC_BASE_URL must be an http(s) origin')
        public_base_url = configured
    else:
        public_host = '127.0.0.1' if host in ('', '0.0.0.0', '::') else host
        public_base_url = f'http://{public_host}:{server.server_address[1]}'
    server.public_base_url = public_base_url
    server.allowed_hosts = {urlsplit(public_base_url).netloc, f'127.0.0.1:{server.server_address[1]}', f'localhost:{server.server_address[1]}'}
    server.trust_proxy = os.environ.get('TRUST_PROXY_HEADERS', '').casefold() in ('1', 'true', 'yes')
    return server
