"""Keeps the anonymous (temporary) Vercel deployment alive by redeploying it every 45 minutes.

    python scripts/vercel_keepalive.py            # loop forever (leave it running during the demo)
    python scripts/vercel_keepalive.py --once

Permanent fix: `npx vercel login` once, then `npx vercel --prod` from build/vercel. Logged-in deployments
never expire and the cron in frontend/vercel.json keeps the backend warm.
"""
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "vercel"
LAMBDA = "https://kcjwxwjdaefxakn7l6nrtntqnu0ronmo.lambda-url.ap-south-1.on.aws"


def deploy():
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(ROOT / "frontend", OUT)
    (OUT / "vercel.json").unlink(missing_ok=True)          # anonymous deployments cannot define cron jobs
    shutil.rmtree(OUT / "api", ignore_errors=True)
    (OUT / "config.js").write_text(f'window.API_BASE = "{LAMBDA}";\n', encoding="utf-8")
    r = subprocess.run("npx --yes vercel deploy --temporary --yes", cwd=OUT, shell=True, text=True, capture_output=True)
    m = re.search(r"https://\S+\.tmp\.now", r.stdout + r.stderr)
    print(time.strftime("%H:%M"), "redeployed", m.group(0) if m else (r.stderr or r.stdout)[-200:], flush=True)


if __name__ == "__main__":
    while True:
        deploy()
        if "--once" in sys.argv:
            break
        time.sleep(45 * 60)
