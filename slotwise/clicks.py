import base64
import hashlib
import hmac
import threading
from collections import defaultdict, deque


MAX_RECENT_KEYS = 4096


class ClickValidator:
    def __init__(self, secret, salt, clock, recent=None, rate_lock=None, max_recent_keys=MAX_RECENT_KEYS):
        self.secret = secret
        self.salt = salt
        self.clock = clock
        self.invalid = defaultdict(int)
        self.recent = recent if recent is not None else {}
        self.rate_lock = rate_lock or threading.Lock()
        self.max_recent_keys = max_recent_keys

    def token(self, impression_id):
        encoded = base64.urlsafe_b64encode(impression_id.encode()).rstrip(b'=').decode()
        signature = hmac.new(self.secret, impression_id.encode(), hashlib.sha256).hexdigest()
        return encoded + '.' + signature

    @staticmethod
    def impression_id(token):
        try:
            encoded, _ = token.split('.', 1)
            return base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode()
        except (ValueError, UnicodeError):
            return None

    def _rate_key(self, client_ip, publisher_id):
        clicker = hashlib.sha256(self.salt + client_ip.encode('utf-8', 'replace')).hexdigest()
        return clicker, publisher_id

    @staticmethod
    def _trim(recent, now):
        while recent and recent[0] <= now - 60:
            if hasattr(recent, 'popleft'):
                recent.popleft()
            else:
                del recent[0]

    def _existing_recent(self, key, now):
        recent = self.recent.get(key)
        if recent is None:
            return None
        self._trim(recent, now)
        if not recent:
            self.recent.pop(key, None)
            return None
        return recent

    def _prune_expired(self, now):
        for key, recent in list(self.recent.items()):
            self._trim(recent, now)
            if not recent:
                self.recent.pop(key, None)

    def _recent_for_claim(self, key, now):
        self._prune_expired(now)
        recent = self.recent.get(key)
        if recent is not None:
            return recent
        if len(self.recent) >= self.max_recent_keys:
            return None
        recent = deque()
        self.recent[key] = recent
        return recent

    def validate(self, token, impressions, client_ip):
        try:
            encoded, signature = token.split('.', 1)
            impression_id = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode()
        except (ValueError, UnicodeError):
            return self._bad('bad_sig')
        expected = hmac.new(self.secret, impression_id.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return self._bad('bad_sig')
        impression = impressions.get(impression_id)
        if not impression:
            return self._bad('unknown_impression')
        now = self.clock.now()
        if impression.expires_at < now:
            return self._bad('expired', impression)
        if impression.clicked:
            return self._bad('duplicate', impression)
        key = self._rate_key(client_ip, impression.publisher_id)
        with self.rate_lock:
            recent = self._existing_recent(key, now)
            if recent is not None and len(recent) >= 5:
                return self._bad('rate_limited', impression)
        return 'candidate', impression

    def claim_billable(self, impression, client_ip):
        now = self.clock.now()
        key = self._rate_key(client_ip, impression.publisher_id)
        with self.rate_lock:
            if impression.clicked:
                return self._bad('duplicate', impression)[0]
            recent = self._recent_for_claim(key, now)
            if recent is None or len(recent) >= 5:
                return self._bad('rate_limited', impression)[0]
            recent.append(now)
            impression.clicked = True
        return 'billable'

    def _bad(self, reason, impression=None):
        self.invalid[reason] += 1
        return reason, impression
