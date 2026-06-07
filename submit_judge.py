"""submit_judge.py — 自动提交 solver.py 到 hackathon.mykeeta.com 并获取评测结果。

Usage:
    python submit_judge.py                        # 提交当前 solver.py
    python submit_judge.py --code solver_v8.py    # 提交指定文件
    python submit_judge.py --login-only           # 仅测试登录
    python submit_judge.py --result JOB_ID        # 查询已有 job 结果

Credentials from agent/judge_credentials.json (不提交 git).
"""
import sys, os, json, time, ssl, urllib.request, urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(BASE_DIR, "agent", "judge_credentials.json")
TOKEN_FILE = os.path.join(BASE_DIR, "agent", ".judge_token")


def load_credentials():
    with open(CRED_FILE, "r", encoding="utf-8") as f:
        creds = json.load(f)
    return creds["base_url"], creds["team"], creds["email"]


def _make_ssl_context():
    """Create a permissive SSL context for servers with imperfect TLS."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # Also allow older TLS versions for compatibility
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _request_with_retry(method, base, path, body=None, max_retries=5):
    """HTTP request with retry on transient SSL/server errors."""
    last_error = None
    for attempt in range(max_retries):
        try:
            data = json.dumps(body).encode("utf-8") if body is not None else None
            req = urllib.request.Request(f"{base}{path}", data=data, method=method)
            if method == "POST":
                req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=30, context=_make_ssl_context()) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            # Don't retry client errors (4xx) except 429
            if e.code != 429 and 400 <= e.code < 500:
                raise
            last_error = e
        except (urllib.error.URLError, ssl.SSLError, OSError) as e:
            last_error = e
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)  # Exponential backoff: 1, 2, 4, 8s
    raise last_error


def api_get(base, path):
    """GET request, returns JSON."""
    return _request_with_retry("GET", base, path)


def api_post(base, path, body):
    """POST request with JSON body, returns JSON."""
    return _request_with_retry("POST", base, path, body=body)


def login(base, team, email):
    """Login and return token. Saves to token file."""
    print(f"Logging in as '{team}' ({email})...")
    resp = api_post(base, "/login", {"team": team, "email": email})
    if resp.get("error"):
        print(f"  ERROR: {resp.get('message', resp['error'])}")
        return None
    token = resp["token"]
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    print(f"  OK. Token: {token[:16]}... (saved)")
    return token


def get_token(base, team, email):
    """Get token from file or login fresh."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token = f.read().strip()
        if token:
            print(f"Using cached token: {token[:16]}...")
            return token
    return login(base, team, email)


def submit_code(base, token, code):
    """Submit code for judging. Returns job_id and daily_remaining."""
    print(f"Submitting code ({len(code)} chars)...")
    resp = api_post(base, "/judge", {"code": code, "token": token})

    if resp.get("error") == "unauthorized":
        print("  Token expired, re-login needed")
        return None, None
    if resp.get("error") == "today_limit_exceeded":
        print(f"  DAILY LIMIT EXCEEDED: {resp.get('message', '')}")
        return None, None
    if resp.get("error"):
        print(f"  ERROR: {resp.get('message', resp['error'])}")
        return None, None

    job_id = resp["job_id"]
    remaining = resp.get("daily_remaining", "?")
    print(f"  OK. Job: {job_id[:16]}... | Daily remaining: {remaining}")
    return job_id, remaining


def poll_result(base, job_id, max_wait=180):
    """Poll for judge result. Returns result dict or None on timeout."""
    print(f"Polling result for job {job_id[:16]}...")
    deadline = time.time() + max_wait
    dots = 0
    while time.time() < deadline:
        time.sleep(2)
        r = api_get(base, f"/result/{job_id}")
        status = r.get("status", "?")
        if status not in ("queued", "running"):
            return r
        dots = (dots + 1) % 4
        elapsed = int(time.time() - (deadline - max_wait))
        print(f"\r  Waiting for result{'.' * (dots + 1):<4} [{elapsed}s]", end="", flush=True)
    print("\n  TIMEOUT")
    return {"status": "timeout", "message": f"Waited {max_wait}s"}


def format_result(r):
    """Pretty-print judge result."""
    print()
    if r.get("status") != "ok":
        print(f"[{r.get('status', '?').upper()}] {r.get('message', 'Unknown error')}")
        return

    print("=" * 70)
    print(f"  Avg Penalty:  {r['avg_score']:.2f}")
    print(f"  Completed:    {r['success_count']} / {r['case_count']}")
    print("=" * 70)
    for c in r.get("case_results", []):
        name = (c.get("case_file", "?")).replace(".txt", "")
        if c.get("status") != "ok":
            penalty = c.get("penalty_score", c.get("total_tasks", 0) * 100)
            print(f"  {name:<28} FAIL  penalty={penalty:.0f}")
        else:
            score = c.get("score", c.get("total_score", 0))
            assigned = c.get("assigned", c.get("assigned_count", "?"))
            total = c.get("total_tasks", "?")
            ms = c.get("elapsed_ms", "?")
            pct = int(assigned / total * 100) if total else 0
            print(f"  {name:<28} {score:>8.2f}  {assigned}/{total}({pct}%)  {ms}ms")
    print("=" * 70)

    # Save result to file
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(BASE_DIR, "evaluations", f"online_result_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)
    print(f"Result saved to {out_path}")


def main():
    base, team, email = load_credentials()

    # Handle special flags
    args = sys.argv[1:]
    if "--login-only" in args:
        token = login(base, team, email)
        return 0 if token else 1

    if "--result" in args:
        idx = args.index("--result")
        job_id = args[idx + 1]
        r = poll_result(base, job_id)
        format_result(r)
        return 0

    # Normal flow: submit and poll
    token = get_token(base, team, email)
    if not token:
        return 1

    # Read solver code
    code_path = "solver.py"
    for i, a in enumerate(args):
        if a == "--code" and i + 1 < len(args):
            code_path = args[i + 1]
    if not os.path.isabs(code_path):
        code_path = os.path.join(BASE_DIR, code_path)
    with open(code_path, "r", encoding="utf-8") as f:
        code = f.read()
    print(f"Read code from {code_path}")

    # Submit
    job_id, remaining = submit_code(base, token, code)
    if not job_id:
        return 1

    # Poll
    r = poll_result(base, job_id)
    format_result(r)

    return 0 if r.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
