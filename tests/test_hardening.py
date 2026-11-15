import json
import os
import unittest
from unittest.mock import patch

import demo
from slotwise.clicks import ClickValidator
from slotwise.interfaces import FakeClock
from slotwise.ledger import Ledger
from slotwise.models import Impression
from slotwise.service import (
    AdNetwork,
    MAX_ADVERTISER_BALANCE_CENTS,
    MAX_LEDGER_TRANSACTIONS,
    MAX_TOPUPS,
    MAX_USER_CAMPAIGNS,
)
from slotwise.web import Handler, SessionLimit, Sessions, make_server


class StateBoundTests(unittest.TestCase):
    def test_ledger_caches_balances_and_bounds_history(self):
        ledger = Ledger(maximum_transactions=2)
        ledger.record('one', (('a', 5), ('b', -5)))
        ledger.record('two', (('a', 7), ('b', -7)))
        ledger.record('three', (('a', 11), ('b', -11)))
        self.assertEqual(len(ledger.transactions), 2)
        self.assertEqual(ledger.balance('a'), 23)

    def test_campaigns_and_topups_are_bounded(self):
        network = AdNetwork()
        for index in range(MAX_USER_CAMPAIGNS):
            network.create_campaign('auth', 100, 100, f'Campaign {index}', 'Useful authentication tool', 'https://example.test')
        with self.assertRaises(ValueError):
            network.create_campaign('auth', 100, 100, 'One too many', 'Useful authentication tool', 'https://example.test')
        for _ in range(MAX_TOPUPS):
            network.topup(10_000)
        with self.assertRaises(ValueError):
            network.topup(10_000)
        self.assertLessEqual(network.advertiser_balance(), MAX_ADVERTISER_BALANCE_CENTS)
        self.assertLessEqual(len(network.ledger.transactions), MAX_LEDGER_TRANSACTIONS)

    def test_standalone_click_limiter_uses_deques_and_removes_stale_keys(self):
        clock = FakeClock()
        validator = ClickValidator(b'secret', b'salt', clock)
        first = Impression('one', 'publisher', 'campaign', 100, clock.now() + 1000)
        self.assertEqual(validator.claim_billable(first, '192.0.2.1'), 'billable')
        first_key = validator._rate_key('192.0.2.1', 'publisher')
        clock.advance(61)
        second = Impression('two', 'publisher', 'campaign', 100, clock.now() + 1000)
        self.assertEqual(validator.claim_billable(second, '192.0.2.2'), 'billable')
        self.assertNotIn(first_key, validator.recent)


class SessionHardeningTests(unittest.TestCase):
    def test_creation_keys_are_salted_bounded_and_expired_entries_deleted(self):
        now = [1000]
        sessions = Sessions(maximum=2, creation_window=10, maximum_creation_keys=2, clock=lambda: now[0])
        sessions.get(client_ip='192.0.2.1')
        self.assertNotIn('192.0.2.1', sessions.creations)
        self.assertTrue(all(owner != '192.0.2.1' for _, _, owner in sessions.items.values()))
        sessions.get(client_ip='192.0.2.2')
        with self.assertRaises(SessionLimit):
            sessions.get(client_ip='192.0.2.3')
        now[0] += 11
        sessions.get(client_ip='192.0.2.3')
        self.assertEqual(len(sessions.creations), 1)

    def test_handler_timeout_and_server_connection_cap(self):
        self.assertEqual(Handler.timeout, 10)
        server = make_server('127.0.0.1', 0, connection_limit=3)
        try:
            self.assertEqual(server.connection_limit, 3)
        finally:
            server.server_close()

    def test_demo_refuses_wildcard_bind_without_public_url(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(demo, 'make_server') as factory:
            with self.assertRaises(SystemExit):
                demo.main()
            factory.assert_not_called()

    def test_decision_callers_forward_client_ip(self):
        source = open('slotwise/web.py', encoding='utf-8').read()
        self.assertIn("self.server.public_base_url, self.client_ip())", source)
        self.assertIn("client_ip=self.client_ip()", source)


if __name__ == '__main__':
    unittest.main()
