"""Package only additive trial routes on top of the specified live function ZIP."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("live", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--relay", type=Path, default=Path(__file__).resolve().parent.parent / "network-trial")
args = parser.parse_args()
here = Path(__file__).resolve().parent
assert args.live.resolve() != args.output.resolve()
anchor = '    path = req.get("rawPath", http.get("path"))\n'
addon = '''    if isinstance(path, str) and path.startswith("/_cf-trial/"):
        if path == "/_cf-trial/api":
            from cf_trial import handle_api
            return handle_api(req, store_client)
        from cf_trial_assets import serve
        return serve(path, method)
'''
files = {"cf_trial.py": here / "cf_trial.py", "cf_trial_assets.py": here / "cf_trial_assets.py",
         "cf_trial_frontend/worker.mjs": args.relay / "worker.mjs"}
for file in ("index.html", "trial.css", "trial.js"):
    files["cf_trial_frontend/" + file] = here / "frontend" / file

with ZipFile(args.live) as old, ZipFile(args.output, "w", ZIP_DEFLATED) as new:
    assert set(old.namelist()).isdisjoint(files)
    for info in old.infolist():
        data = old.read(info)
        if info.filename == "index.py":
            src = data.decode()
            assert src.count(anchor) == 1 and addon not in src
            data = src.replace(anchor, anchor + addon).encode()
            compile(data, "index.py", "exec")
        new.writestr(info, data)
    for archive_path, local_file in files.items():
        new.writestr(archive_path, local_file.read_bytes())

with ZipFile(args.output) as new, ZipFile(args.live) as old:
    assert new.testzip() is None
    deltas = {name for name in old.namelist() if new.getinfo(name).CRC != old.getinfo(name).CRC}
    assert deltas == {"index.py"}
    assert new.read("index.py").decode().replace(anchor + addon, anchor) == old.read("index.py").decode()
print("Additive trial files verified:", ", ".join(files))
