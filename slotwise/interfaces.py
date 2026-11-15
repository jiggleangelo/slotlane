import time
from collections import deque
from typing import Protocol


class PaymentsGateway(Protocol):
    def charge(self, advertiser_id: str, amount_cents: int) -> str: ...
    def payout(self, publisher_id: str, amount_cents: int) -> str: ...


class Vault(Protocol):
    def put(self, value: str) -> str: ...


class Clock(Protocol):
    def now(self) -> float: ...


class FakePayments:
    def __init__(self, maximum_calls=2048):
        self.calls = deque(maxlen=maximum_calls)
        self._sequence = 0

    def charge(self, advertiser_id, amount_cents):
        self._sequence += 1
        ref = f'chg_{self._sequence}'
        self.calls.append(('charge', advertiser_id, amount_cents, ref))
        return ref

    def payout(self, publisher_id, amount_cents):
        self._sequence += 1
        ref = f'pay_{self._sequence}'
        self.calls.append(('payout', publisher_id, amount_cents, ref))
        return ref


class MemoryVault:
    def __init__(self):
        self.__values = {}

    def put(self, value):
        import secrets
        ref = 'vlt_' + secrets.token_hex(8)
        self.__values[ref] = value
        return ref


class SystemClock:
    def now(self):
        return time.time()


class FakeClock:
    def __init__(self, value=1_000_000.0):
        self.value = value

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds
