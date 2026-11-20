"""Synthetic mobile-network trial. No official ballot data or visitor addresses."""
import base64
import hmac
import json
import os
import re
from urllib.request import Request, urlopen
from uuid import UUID

HOST = "cf-test.ends0culus.com"
ORIGIN = "https://" + HOST
DIRECT_ORIGIN = "https://vote.ends0culus.com"
ALLOWED_ORIGINS = (ORIGIN, DIRECT_ORIGIN)
PATH = "/_cf-trial/api"
ACTION = "cf_trial"
NETWORKS = ("wifi", "cellular", "other")
ROW_KEY = [("survey_id", "fixture-cf-trial-v1")]
LIMIT = 256
UUID4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
VERIFY_HOSTS = {"world": "challenges.cloudflare.com", "china": "challenges.cloudflare-cn.com"}


class TrialError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


def siteverify(attempt, token, origin):
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    host = VERIFY_HOSTS.get(os.environ.get("TURNSTILE_REGION", "world").strip().lower())
    if not secret or not host:
        raise TrialError(503, "verification-unavailable")
    digest = hmac.digest(secret.encode(), f"cf-trial-siteverify:{origin}:{attempt}:{token}".encode(), "sha256")
    params = {"secret": secret, "response": token, "idempotency_key": str(UUID(bytes=digest[:16], version=4))}
    request = Request(f"https://{host}/turnstile/v0/siteverify", data=json.dumps(params).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read(16385))
    except (OSError, ValueError, RecursionError):
        raise TrialError(503, "verification-unavailable")
    if not isinstance(result, dict):
        raise TrialError(503, "verification-unavailable")
    if result.get("success") is not True:
        errors = result.get("error-codes")
        if not isinstance(errors, list) or any(code in ("internal-error", "invalid-input-secret", "missing-input-secret") for code in errors):
            raise TrialError(503, "verification-unavailable")
        raise TrialError(403, "verification-rejected")
    if result.get("hostname") != origin.removeprefix("https://") or result.get("action") != ACTION or result.get("cdata") != attempt:
        raise TrialError(403, "verification-rejected")


def snapshot(client, marker, network):
    cols = ["total", network, "direct_" + network, marker]
    _, row, more = client.get_row("survey", ROW_KEY, columns_to_get=cols, max_version=1)
    if more:
        raise RuntimeError("Incomplete trial row")
    return {k: v for k, v, _ in row.attribute_columns} if row else {}


def commit(client, current, marker, network, origin, sample):
    from tablestore import Condition, RowExistenceExpectation as Exists, SingleColumnCondition, ComparatorType, Row, OTSServiceError
    updates = [("total", current.get("total", 0) + 1), (network, current.get(network, 0) + 1), (marker, sample)]
    if origin == DIRECT_ORIGIN:
        counter = "direct_" + network
        updates.append((counter, current.get(counter, 0) + 1))
    try:
        if not current:
            client.put_row("survey", Row(ROW_KEY, updates), Condition(Exists.EXPECT_NOT_EXIST))
        else:
            version = SingleColumnCondition("total", current["total"], ComparatorType.EQUAL, pass_if_missing=False)
            client.update_row("survey", Row(ROW_KEY, {"PUT": updates}), Condition(Exists.EXPECT_EXIST, version))
        return True
    except OTSServiceError as err:
        if err.get_error_code() == "OTSConditionCheckFail":
            return False
        raise


def accept(client, attempt, network, token, origin):
    marker = "s_" + attempt.replace("-", "")
    # The initial proxy fixture stored plain network labels; preserve those receipts.
    sample = "direct:" + network if origin == DIRECT_ORIGIN else network
    for write_attempt in range(4):
        state = snapshot(client, marker, network)
        if marker in state:
            if state[marker] != sample:
                raise TrialError(409, "attempt-conflict")
            return True
        if state.get("total", 0) >= LIMIT:
            raise TrialError(429, "trial-full")
        if write_attempt == 0:
            siteverify(attempt, token, origin)
        if commit(client, state, marker, network, origin, sample):
            return False
    raise TrialError(503, "storage-busy")


def handle_api(req, store_client):
    def reply(status, payload):
        return {"statusCode": status, "headers": {"Content-Type": "application/json; charset=utf-8",
                "Cache-Control": "no-store", "Vary": "Origin"}, "isBase64Encoded": False,
                "body": json.dumps(payload, separators=(",", ":"))}

    try:
        http = req.get("requestContext", {}).get("http", {})
        if req.get("rawPath", http.get("path")) != PATH:
            raise TrialError(404, "not-found")
        headers = {k.lower(): v for k, v in (req.get("headers") or {}).items()}
        origin = headers.get("origin")
        if origin not in ALLOWED_ORIGINS:
            raise TrialError(403, "origin-denied")
        if http.get("method") != "POST":
            raise TrialError(405, "method-denied")
        if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise TrialError(415, "invalid-media-type")
        body = req.get("body")
        if not isinstance(body, str) or len(body) > 6000:
            raise TrialError(400, "invalid-payload")
        try:
            raw = base64.b64decode(body, validate=True) if req.get("isBase64Encoded") else body.encode()
            if len(raw) > 4096:
                raise TrialError(413, "payload-too-large")
            data = json.loads(raw)
        except (ValueError, TypeError, RecursionError):
            raise TrialError(400, "invalid-payload")
        if not isinstance(data, dict) or set(data) != {"attempt", "network", "token"}:
            raise TrialError(400, "invalid-payload")
        attempt, network, token = data["attempt"], data["network"], data["token"]
        if not isinstance(attempt, str) or not UUID4.fullmatch(attempt) or network not in NETWORKS or not isinstance(token,str) or not 1 <= len(token) <= 2048:
            raise TrialError(400, "invalid-payload")
        duplicate = accept(store_client(), attempt, network, token, origin)
        return reply(200, {"ok": True, "attempt": attempt, "duplicate": duplicate})
    except TrialError as err:
        return reply(err.status, {"ok": False, "error": err.code})
    except Exception:
        return reply(503, {"ok": False, "error": "storage-unavailable"})
