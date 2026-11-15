from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Transaction:
    kind: str
    entries: tuple[tuple[str, int], ...]
    ref: str = ''


class Ledger:
    def __init__(self, maximum_transactions=2048):
        if maximum_transactions < 1:
            raise ValueError('maximum_transactions must be positive')
        self.transactions = deque(maxlen=maximum_transactions)
        self._balances = defaultdict(int)

    def record(self, kind, entries, ref=''):
        entries = tuple(entries)
        if sum(delta for _, delta in entries) != 0:
            raise ValueError('unbalanced transaction')
        tx = Transaction(kind, entries, ref)
        for account, delta in entries:
            self._balances[account] += delta
            if self._balances[account] == 0:
                del self._balances[account]
        self.transactions.append(tx)
        return tx

    def balance(self, account):
        return self._balances.get(account, 0)

    def topup(self, advertiser_id, amount, fee, ref=''):
        if amount < 10_000:
            raise ValueError('minimum top-up is 10000 cents')
        return self.record('topup', (
            ('external:card', -(amount + fee)),
            (f'advertiser:{advertiser_id}', amount),
            ('processor:fees', fee),
        ), ref)

    def click(self, advertiser_id, publisher_id, amount):
        publisher = amount * 70 // 100
        return self.record('click', (
            (f'advertiser:{advertiser_id}', -amount),
            (f'publisher:{publisher_id}', publisher),
            ('platform:revenue', amount - publisher),
        ))

    def payout(self, publisher_id, amount, ref=''):
        return self.record('payout', (
            (f'publisher:{publisher_id}', -amount),
            ('external:bank', amount),
        ), ref)
