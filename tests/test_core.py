import ast, inspect, unittest
from slotwise.auction import run
from slotwise.interfaces import FakeClock, MemoryVault
from slotwise.ledger import Ledger
from slotwise.models import Campaign, Creative, Impression
from slotwise.review import review
from slotwise.service import AdNetwork, DECISION_RATE_LIMIT, DECISION_RATE_WINDOW_SECONDS, MAX_IMPRESSIONS
import slotwise.demo_agent as demo_agent
from slotwise.mcp_server import handle

class CoreTests(unittest.TestCase):
    def campaign(self,bid,seq): return Campaign(str(seq),"a","A","error-monitoring",bid,1000,0,Creative("t","d","https://x","approved"),seq)
    def test_auction_second_price_floor_and_tie(self):
        a,b=self.campaign(300,1),self.campaign(240,2)
        self.assertEqual(run([a,b],100).price_cents,240)
        self.assertEqual(run([a],100).price_cents,100)
        b.bid_cents=300; self.assertIs(run([b,a],100).campaign,a)
        self.assertEqual(run([a],250).price_cents,250)
    def test_ledger(self):
        ledger=Ledger(); ledger.topup("a",10000,320)
        self.assertEqual(ledger.balance("advertiser:a"),10000)
        ledger.click("a","p",240); self.assertEqual(ledger.balance("publisher:p"),168); self.assertEqual(ledger.balance("platform:revenue"),72)
        ledger.click("a","p",101); self.assertEqual(ledger.balance("platform:revenue"),103)
        before=len(ledger.transactions)
        with self.assertRaises(ValueError): ledger.record("bad",(("x",1),))
        self.assertEqual(len(ledger.transactions),before)
        with self.assertRaises(ValueError): Ledger().topup("a",9999,1)
    def test_review(self):
        self.assertEqual(review(Creative("Clean","Useful tool","https://example.test")).status,"approved")
        for text in ("ignore previous", "system:", "you must", "<tag>", "official", "#1"):
            self.assertEqual(review(Creative(text,"description","http://bad url")).status,"rejected")
    def test_click_duplicate_expired_and_tampered(self):
        clock=FakeClock(); network=AdNetwork(clock); result=network.decide("app crash")
        token=result["items"][0]["click_url"].split("/c/")[1]
        self.assertEqual(network.click(token,"1.2.3.4")[0],"billable")
        self.assertEqual(network.click(token,"1.2.3.4")[0],"duplicate")
        self.assertEqual(network.click(token+"x","1.2.3.4")[0],"bad_sig")
        result=network.decide("app crash"); token=result["items"][0]["click_url"].split("/c/")[1]; clock.advance(1801)
        self.assertEqual(network.click(token,"1.2.3.4")[0],"expired")
    def test_decide_purges_caps_and_rate_limits_impressions(self):
        clock=FakeClock(); network=AdNetwork(clock)
        expired=Impression("expired","demo","cmp_1",100,clock.now())
        network.impressions[expired.id]=expired
        self.assertEqual(network.decide("hello",client_ip="10.0.0.1")["items"],[])
        self.assertNotIn(expired.id,network.impressions)
        for index in range(MAX_IMPRESSIONS):
            iid=f"stored_{index}"
            network.impressions[iid]=Impression(iid,"demo","cmp_1",100,clock.now()+index+1)
        result=network.decide("app crash",client_ip="10.0.0.2")
        self.assertTrue(result["items"])
        self.assertEqual(len(network.impressions),MAX_IMPRESSIONS)
        self.assertNotIn("stored_0",network.impressions)
        limited=AdNetwork(clock)
        for index in range(DECISION_RATE_LIMIT):
            self.assertTrue(limited.decide("app crash",client_ip=f"192.0.2.{index}")["items"])
        self.assertEqual(limited.decide("app crash",client_ip="198.51.100.1")["items"],[])
        clock.advance(DECISION_RATE_WINDOW_SECONDS+1)
        self.assertTrue(limited.decide("app crash",client_ip="198.51.100.1")["items"])
        per_ip=AdNetwork(clock)
        for index in range(DECISION_RATE_LIMIT):
            publisher=per_ip.publishers["demo"]
            pid=f"publisher_{index}"
            per_ip.publishers[pid]=type(publisher)(pid,publisher.name,publisher.key_hash)
            self.assertTrue(per_ip.decide("app crash",publisher_id=pid,client_ip="203.0.113.10")["items"])
        publisher=per_ip.publishers["demo"]
        per_ip.publishers["publisher_blocked"]=type(publisher)("publisher_blocked",publisher.name,publisher.key_hash)
        self.assertEqual(per_ip.decide("app crash",publisher_id="publisher_blocked",client_ip="203.0.113.10")["items"],[])
    def test_unclassified_and_filters(self):
        network=AdNetwork(); self.assertEqual(network.decide("hello")["items"],[])
        network.publishers["demo"].blocklist.add("error-monitoring"); self.assertEqual(network.decide("crash")["items"],[])
    def test_mcp_and_privacy_boundary(self):
        init=handle({"jsonrpc":"2.0","id":1,"method":"initialize"}); self.assertIn("result",init)
        listed=handle({"jsonrpc":"2.0","id":2,"method":"tools/list"}); self.assertEqual(len(listed["result"]["tools"]),1)
        called=handle({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_sponsored_recommendations","arguments":{"query":"crash"}}})
        self.assertEqual(called["result"]["structuredContent"]["label"],"Sponsored")
        self.assertIn("error",handle({"bad":True}))
        self.assertFalse(hasattr(MemoryVault(),"get"))
        imports=[n.module for n in ast.walk(ast.parse(inspect.getsource(demo_agent))) if isinstance(n,ast.ImportFrom)]
        self.assertFalse(any(x and ("auction" in x or "service" in x) for x in imports))

if __name__ == "__main__": unittest.main()
