from dataclasses import dataclass, field

@dataclass
class Advertiser:
    id: str
    name: str
    contact_ref: str | None = None

@dataclass
class Creative:
    title: str
    description: str
    url: str
    status: str = "pending"
    reasons: list[str] = field(default_factory=list)

@dataclass
class Campaign:
    id: str
    advertiser_id: str
    advertiser_name: str
    category: str
    bid_cents: int
    budget_cents: int
    spent_cents: int
    creative: Creative
    created_seq: int
    status: str = "active"

@dataclass
class Publisher:
    id: str
    name: str
    key_hash: str
    blocklist: set[str] = field(default_factory=set)
    min_bid_cents: int = 100

@dataclass
class Impression:
    id: str
    publisher_id: str
    campaign_id: str
    price_cents: int
    expires_at: float
    clicked: bool = False

@dataclass
class AuctionResult:
    campaign: Campaign
    price_cents: int
