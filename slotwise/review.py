import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

PATTERNS = [
    r'\bignore\s+(?:all|the|any|previous|prior|above)',
    r'\bdisregard\b.{0,30}\b(?:above|previous|prior|instructions?)\b',
    r'\bsystem\s*:', r'\bassistant\s*:', r'\byou\s+must\b', r'\binstructions?\b',
    r'\bdo\s+not\s+tell\b', r'\bas\s+an\s+ai\b', r'\btool\s+call\b', r'\bcall\s+the\b',
]
DECEPTIVE = [r'\bofficial\b', r'\brecommended\s+by\s+(?:openai|anthropic|claude|chatgpt)\b', r'(?<!\w)#1(?!\d)', r'\bguaranteed\b', r'\bfree\s+money\b']
ZERO_WIDTH = {'\u200b', '\u200c', '\u200d', '\u2060', '\ufeff'}
MATCH_LIMIT = 2000


@dataclass(frozen=True)
class Finding:
    rule_id: str
    message: str
    fix: str
    match: str


RULES = (
    ('LEN-TITLE', 'The title is missing or longer than 60 characters.', 'Add a title of at most 60 characters.'),
    ('LEN-DESC', 'The description is missing or longer than 140 characters.', 'Add a description of at most 140 characters.'),
    ('LEN-URL', 'The URL is missing or longer than 200 characters.', 'Use a complete destination URL of at most 200 characters.'),
    ('URL-SCHEME', 'The destination is not an absolute HTTPS URL.', 'Use a URL beginning with https://.'),
    ('URL-CREDENTIALS', 'The URL contains embedded credentials.', 'Remove the username and password from the URL.'),
    ('URL-FRAGMENT', 'The URL contains a fragment.', 'Remove the #fragment from the destination.'),
    ('URL-HOST', 'The host is missing, malformed, local, an IP address, or an internationalized hostname.', 'Use a public ASCII domain name.'),
    ('URL-SPACE', 'The URL contains whitespace.', 'Remove spaces and line breaks from the URL.'),
    ('URL-CONTROL', 'The URL contains control or invisible characters.', 'Retype the URL using ordinary visible characters.'),
    ('TXT-CONTROL', 'The copy contains control or invisible formatting characters.', 'Remove invisible and control characters.'),
    ('TXT-MARKUP', 'The copy contains HTML, Markdown, or code markup.', 'Use plain text only.'),
    ('TXT-LINK', 'The title or description contains a link-like value.', 'Put the destination only in the URL field.'),
    ('INJ-01', 'The copy asks an agent to ignore or disregard prior context.', 'Describe the product benefit without directing the agent.'),
    ('INJ-02', 'The copy impersonates a system or assistant message.', 'Remove role labels such as system: or assistant:.'),
    ('INJ-03', 'The copy gives commands to the agent or invokes instructions.', 'Rewrite it as ordinary advertising copy, not an instruction.'),
    ('INJ-04', 'The copy refers to hidden agent behavior or tool calls.', 'Describe user-visible product capabilities only.'),
    ('DEC-01', 'The copy makes an unsupported official or platform-endorsement claim.', 'Remove the endorsement claim or state a verifiable relationship precisely.'),
    ('DEC-02', 'The copy makes an absolute ranking or guarantee claim.', 'Use a specific, supportable product benefit instead.'),
    ('DEC-03', 'The copy promises free money.', 'Remove the financial inducement.'),
)
RULE_INDEX = {rule_id: (message, fix) for rule_id, message, fix in RULES}


def _normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value) if c not in ZERO_WIDTH)


def _unsafe_hostname(hostname):
    if not hostname:
        return True
    name = hostname.rstrip('.').casefold()
    if name == 'localhost' or name.endswith(('.localhost', '.local', '.internal')):
        return True
    if name.startswith('xn--') or '.xn--' in name:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        address = None
    if address is not None or len(name) > 253 or '.' not in name:
        return True
    labels = name.split('.')
    return any(not label or len(label) > 63 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', label) for label in labels)


def _finding(rule_id, match=''):
    message, fix = RULE_INDEX[rule_id]
    return Finding(rule_id, message, fix, match[:160])


def review_detailed(creative):
    title = creative.title if isinstance(creative.title, str) else ''
    description = creative.description if isinstance(creative.description, str) else ''
    url = creative.url if isinstance(creative.url, str) else ''
    findings = []
    if not title or len(title) > 60:
        findings.append(_finding('LEN-TITLE', title[:80]))
    if not description or len(description) > 140:
        findings.append(_finding('LEN-DESC', description[:80]))
    if not url or len(url) > 200:
        findings.append(_finding('LEN-URL', url[:80]))
    checked_url = url[:MATCH_LIMIT]
    try:
        parsed = urlsplit(checked_url)
    except ValueError:
        parsed = None
    if not parsed or parsed.scheme.casefold() != 'https' or not parsed.netloc:
        findings.append(_finding('URL-SCHEME', checked_url))
    if parsed and (parsed.username is not None or parsed.password is not None):
        findings.append(_finding('URL-CREDENTIALS', parsed.netloc))
    if parsed and parsed.fragment:
        findings.append(_finding('URL-FRAGMENT', parsed.fragment))
    if parsed and (len(parsed.netloc) > 253 or _unsafe_hostname(parsed.hostname)):
        findings.append(_finding('URL-HOST', parsed.hostname or parsed.netloc))
    space = next((c for c in checked_url if c.isspace()), '')
    if space:
        findings.append(_finding('URL-SPACE', repr(space)))
    control = next((c for c in checked_url if unicodedata.category(c) == 'Cc' or c in ZERO_WIDTH), '')
    if control:
        findings.append(_finding('URL-CONTROL', repr(control)))
    raw_text = title[:MATCH_LIMIT] + ' ' + description[:MATCH_LIMIT]
    text = _normalized(raw_text)
    bad_control = next((c for c in raw_text if unicodedata.category(c) in ('Cc', 'Cf')), '')
    if bad_control:
        findings.append(_finding('TXT-CONTROL', repr(bad_control)))
    markup = re.search(r'</?[A-Za-z][^>\n]{0,200}>|`|\[[^\]\n]{0,200}\]\(', text)
    if markup:
        findings.append(_finding('TXT-MARKUP', markup.group(0)))
    link = re.search(r'https?://|://|www\.', text, re.I)
    if link:
        findings.append(_finding('TXT-LINK', link.group(0)))
    injection_rules = (
        ('INJ-01', r'\b(?:ignore|disregard)\s+(?:(?:all|the)\s+)?(?:previous|prior|above)\s+(?:instructions?|context|messages?|rules?|prompt)\b'),
        ('INJ-02', r'\b(?:system|assistant)\s*:'),
        ('INJ-03', r'\b(?:you\s+must|do\s+not\s+tell)\b|\b(?:ignore|follow|new|override|system|disregard)\b.{0,30}\binstructions?\b'),
        ('INJ-04', r'\b(?:as\s+an\s+ai|tool\s+call|call\s+the\s+(?:tool|function))\b'),
    )
    for rule_id, pattern in injection_rules:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            findings.append(_finding(rule_id, match.group(0)))
    deceptive_rules = (
        ('DEC-01', r'\bofficial\s+(?:openai|anthropic|claude|chatgpt)\b|\b(?:openai|anthropic|claude|chatgpt)\s+official\b|\brecommended\s+by\s+(?:openai|anthropic|claude|chatgpt)\b'),
        ('DEC-02', r'(?<!\w)#1(?!\d)|\bguaranteed\b'),
        ('DEC-03', r'\bfree\s+money\b'),
    )
    for rule_id, pattern in deceptive_rules:
        match = re.search(pattern, text, re.I)
        if match:
            findings.append(_finding(rule_id, match.group(0)))
    return findings


def review(creative):
    """Legacy review used by demo.py; its original messages and matching stay intact."""
    reasons = []
    for name, value, limit in (('title', creative.title, 60), ('description', creative.description, 140)):
        if not value:
            reasons.append(f'{name} is empty')
        elif len(value) > limit:
            reasons.append(f'{name} exceeds {limit} characters')
    url = creative.url
    if not url:
        reasons.append('url is empty')
    elif len(url) > 200:
        reasons.append('url exceeds 200 characters')
    try:
        parsed = urlsplit(url)
    except ValueError:
        parsed = None
    if not parsed or parsed.scheme.casefold() != 'https' or not parsed.netloc:
        reasons.append('url must use https://')
    if parsed and (parsed.username is not None or parsed.password is not None):
        reasons.append('url must not contain credentials')
    if parsed and (parsed.fragment or len(parsed.netloc) > 253):
        reasons.append('url must not contain a fragment or oversized host')
    if parsed and _unsafe_hostname(parsed.hostname):
        reasons.append('url host is not allowed')
    if any(c.isspace() for c in url):
        reasons.append('url must not contain whitespace')
    if any(unicodedata.category(c) == 'Cc' or c in ZERO_WIDTH for c in url):
        reasons.append('url must not contain control characters')
    raw_text = creative.title + ' ' + creative.description
    text = _normalized(raw_text)
    if any(unicodedata.category(c) in ('Cc', 'Cf') for c in raw_text):
        reasons.append('text must not contain control characters')
    if any(mark in text for mark in ('<', '>', '`', '[', '](')):
        reasons.append('text must not contain markup')
    if re.search(r'\bhttps?\b|www\.', text, re.I):
        reasons.append('text must not contain links')
    for pattern in PATTERNS:
        if re.search(pattern, text, re.I | re.S):
            reasons.append(f'prompt-injection pattern: {pattern}')
    for pattern in DECEPTIVE:
        if re.search(pattern, text, re.I):
            reasons.append(f'deceptive claim: {pattern}')
    creative.reasons = reasons
    creative.status = 'rejected' if reasons else 'approved'
    return creative
