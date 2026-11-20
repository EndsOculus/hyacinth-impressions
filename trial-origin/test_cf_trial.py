"""Local offline smoke test: real OTS SDK row types with an in-memory store."""
import io
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

import cf_trial as trial
from tablestore import OTSServiceError, Row


class DemoStore:
    def __init__(self):
        self.state = {}
        self.race = False
        self.lost_ack = False

    def get_row(self, name, pk, *, columns_to_get, max_version):
        assert (name, pk) == ("survey", [("survey_id", "fixture-cf-trial-v1")])
        row = Row(pk, [(k, v, 1) for k, v in self.state.items() if k in columns_to_get]) if self.state else None
        return None, row, None

    def put_row(self, name, row, condition):
        assert not self.state and row.primary_key == trial.ROW_KEY
        self.state.update(row.attribute_columns)
        if self.lost_ack:
            raise TimeoutError()

    def update_row(self, name, row, condition):
        assert row.primary_key == trial.ROW_KEY
        assert condition.column_condition.column_name == "total"
        assert condition.column_condition.column_value == self.state["total"]
        if self.race:
            self.race = False
            self.state["total"] += 1
            self.state["other"] = self.state.get("other", 0) + 1
            raise OTSServiceError(409, "OTSConditionCheckFail", "lost race")
        self.state.update(row.attribute_columns["PUT"])


class Cases(unittest.TestCase):
    def setUp(self):
        self.store = DemoStore()
        self.attempt = str(uuid4())
        self.provider = {"success": True, "action": "cf_trial", "hostname": trial.HOST, "cdata": self.attempt}
        self.keys = []
        self.env = patch.dict(trial.os.environ, {"TURNSTILE_SECRET_KEY": "synthetic-unit-secret", "TURNSTILE_REGION": "world"})
        self.env.start()
        self.transport = patch.object(trial, "urlopen", self.verify).start()

    def tearDown(self):
        patch.stopall()

    def verify(self, request, timeout):
        data = json.loads(request.data)
        assert set(data) == {"response", "idempotency_key", "secret"} and timeout == 5
        self.keys.append(data["idempotency_key"])
        return io.BytesIO(json.dumps(self.provider).encode())

    def send(self, network="wifi", origin=trial.ORIGIN, method="POST", **extra):
        event = {"rawPath": trial.PATH, "requestContext": {"http": {"method": method}},
                 "headers": {"origin": origin, "content-type": "application/json"},
                 "body": json.dumps(dict(attempt=self.attempt, network=network, token="proof", **extra))}
        result = trial.handle_api(event, lambda: self.store)
        return result["statusCode"], json.loads(result["body"])

    def test_persist_retry_and_new_samples(self):
        status, body = self.send()
        self.assertEqual((status,body["duplicate"],body["attempt"]), (200,False,self.attempt))
        self.assertEqual(self.send()[1]["duplicate"], True)
        self.assertEqual(self.send("cellular")[0], 409)
        self.assertEqual(len(self.keys), 1)
        self.attempt = str(uuid4())
        self.provider["cdata"] = self.attempt
        self.store.race = True
        self.assertEqual(self.send("cellular")[0], 200)
        self.assertEqual((self.store.state["wifi"],self.store.state["cellular"],self.store.state["total"]), (1,1,3))
        self.assertEqual(len(self.keys), 2)
        self.assertNotIn("proof", json.dumps(self.store.state))

    def test_lost_ack(self):
        self.store.lost_ack = True
        self.assertEqual(self.send()[0], 503)
        self.assertTrue(self.send()[1]["duplicate"])
        self.assertEqual(self.store.state["total"], 1)

    def test_real_challenge_required(self):
        for key, bad in (("success", False), ("action","survey_submit"), ("hostname","vote.ends0culus.com"), ("cdata",str(uuid4()))):
            with patch.dict(self.provider, {key:bad, "error-codes":["invalid-input-response"]}):
                self.assertEqual(self.send()[0],403)
        self.assertFalse(self.store.state)
        self.assertEqual(len(set(self.keys)),1)
        with patch.object(trial,"urlopen",side_effect=TimeoutError):
            self.assertEqual(self.send()[0],503)
        self.assertEqual(self.send()[0],200)

    def test_two_origins_bind_token_and_receipt(self):
        for origin, wrong in ((trial.ORIGIN, trial.DIRECT_ORIGIN),(trial.DIRECT_ORIGIN, trial.ORIGIN)):
            self.attempt = str(uuid4())
            self.provider["cdata"] = self.attempt
            self.provider["hostname"] = wrong.removeprefix("https://")
            self.assertEqual(self.send(origin=origin)[0],403)
            self.provider["hostname"] = origin.removeprefix("https://")
            with patch.dict(self.provider, {"action":"survey_submit"}):
                self.assertEqual(self.send(origin=origin)[0],403)
            self.assertEqual(self.send(origin=origin)[0],200)
            self.assertTrue(self.send(origin=origin)[1]["duplicate"])
            self.assertEqual(self.send(origin=wrong)[0],409)
        self.assertEqual((self.store.state["total"],self.store.state["wifi"],self.store.state["direct_wifi"]),(2,2,1))

    def test_minimal_payload_and_exact_origin(self):
        self.assertEqual(self.send(origin="https://endsoculus.github.io")[0],403)
        self.assertEqual(self.send(origin="null")[0],403)
        self.assertEqual(self.send(method="GET")[0],405)
        self.assertEqual(self.send(network="mobile")[0],400)
        self.assertEqual(self.send(answers={"1":0})[0],400)
        self.store.state = {"total":trial.LIMIT}
        self.assertEqual(self.send()[0],429)
        self.assertFalse(self.keys)


if __name__ == "__main__":
    unittest.main()
