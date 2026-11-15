from .models import AuctionResult

def run(candidates, floor_cents):
    eligible = sorted(candidates, key=lambda c: (-c.bid_cents, c.created_seq))
    if not eligible: return None
    price = max(floor_cents, eligible[1].bid_cents if len(eligible) > 1 else floor_cents)
    return AuctionResult(eligible[0], price)
