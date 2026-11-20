"""Read-only public assets for the network trial, isolated from the survey."""
import base64
from pathlib import Path

ROOT = Path(__file__).parent
TRIAL = ROOT / "cf_trial_frontend"
STATIC = ROOT / "static"
ROUTES = {
    "/_cf-trial/": (TRIAL / "index.html", "text/html; charset=utf-8"),
    "/_cf-trial/index.html": (TRIAL / "index.html", "text/html; charset=utf-8"),
    "/_cf-trial/trial.js": (TRIAL / "trial.js", "text/javascript; charset=utf-8"),
    "/_cf-trial/trial.css": (TRIAL / "trial.css", "text/css; charset=utf-8"),
    "/_cf-trial/samples/survey.js": (STATIC / "survey.js", "text/javascript; charset=utf-8"),
    "/_cf-trial/samples/survey.css": (STATIC / "survey.css", "text/css; charset=utf-8"),
    "/_cf-trial/worker.mjs": (TRIAL / "worker.mjs", "text/plain; charset=utf-8"),
}
BASE_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow",
                "X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin"}


def serve(path, method):
    if path not in ROUTES:
        return {"statusCode": 404, "headers": BASE_HEADERS, "isBase64Encoded": False, "body": ""}
    if method not in ("GET", "HEAD"):
        return {"statusCode": 405, "headers": {**BASE_HEADERS, "Allow": "GET, HEAD"},
                "isBase64Encoded": False, "body": ""}
    file, mime = ROUTES[path]
    return {"statusCode": 200, "headers": {**BASE_HEADERS, "Content-Type": mime},
            "isBase64Encoded": method == "GET",
            "body": base64.b64encode(file.read_bytes()).decode("ascii") if method == "GET" else ""}
