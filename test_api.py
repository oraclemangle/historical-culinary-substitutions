"""
Smoke + edge-case tests for the Old Recipe Intelligence API.

Run with the API server up:
  uvicorn api:app --port 8000 &
  python test_api.py
"""
import os
import sys
import requests

BASE     = "http://127.0.0.1:8000/v1"
HEADERS  = {"X-API-Key": os.getenv("TEST_API_KEY", "")}
BAD_KEY  = {"X-API-Key": "not-a-real-key"}

PASSED = FAILED = 0


def ok(label: str):
    global PASSED
    PASSED += 1
    print(f"  PASS  {label}")


def fail(label: str, detail: str = ""):
    global FAILED
    FAILED += 1
    print(f"  FAIL  {label}{f'  ({detail})' if detail else ''}")


def post(endpoint, question, key_header=None, top_k=None):
    if key_header is None:
        key_header = HEADERS
    body = {"question": question}
    if top_k is not None:
        body["top_k"] = top_k
    return requests.post(f"{BASE}/{endpoint}", json=body, headers=key_header, timeout=60)


def get(path, key_header=None):
    if key_header is None:
        key_header = HEADERS
    return requests.get(f"{BASE}/{path}", headers=key_header, timeout=15)


def test_health():
    print("\n── Health ────────────────────────────────────────────────────")
    r = requests.get(f"{BASE}/health", timeout=10)
    if r.status_code != 200:
        fail("health returns 200", str(r.status_code))
        sys.exit(1)
    h = r.json()
    ok(f"health ok — {h['records']:,} records, {h['books']} books")
    if "endpoints" in h and len(h["endpoints"]) >= 4:
        ok("health lists endpoints")
    else:
        fail("health lists endpoints")


def test_auth():
    print("\n── Auth ──────────────────────────────────────────────────────")
    r = post("substitute", "test", key_header=BAD_KEY)
    if r.status_code == 401:
        ok("bad key → 401")
    else:
        fail("bad key → 401", str(r.status_code))

    r = requests.post(f"{BASE}/substitute", json={"question": "test"}, timeout=10)
    if r.status_code == 401:
        ok("no key → 401")
    else:
        fail("no key → 401", str(r.status_code))


def test_validation():
    print("\n── Input validation ──────────────────────────────────────────")
    r = post("substitute", "")
    if r.status_code == 400:
        ok("empty question → 400")
    else:
        fail("empty question → 400", str(r.status_code))

    r = post("substitute", "   ")
    if r.status_code == 400:
        ok("whitespace-only question → 400")
    else:
        fail("whitespace-only question → 400", str(r.status_code))


def test_substitute():
    print("\n── /v1/substitute ────────────────────────────────────────────")
    cases = [
        "What can replace buttermilk in a 1900s biscuit recipe?",
        "What substitutes for lard in Victorian pastry?",
        "What replaces suet in an old pudding?",
    ]
    for q in cases:
        r = post("substitute", q)
        if r.status_code != 200:
            fail(q[:55], f"status {r.status_code}")
            continue
        d = r.json()
        if d.get("answer") and d.get("sources") is not None and d.get("latency_ms") is not None:
            ok(f"{q[:55]}  ({d['latency_ms']}ms, {len(d['sources'])} sources)")
        else:
            fail(q[:55], "missing fields in response")


def test_modernise():
    print("\n── /v1/modernise ─────────────────────────────────────────────")
    q = "Take 1 gill of cream and the yolks of 3 eggs. Beat well and heat gently until thick."
    r = post("modernise", q)
    if r.status_code == 200 and r.json().get("answer"):
        ok(f"modernise recipe  ({r.json()['latency_ms']}ms)")
    else:
        fail("modernise recipe", str(r.status_code))


def test_convert():
    print("\n── /v1/convert ───────────────────────────────────────────────")
    cases = [
        "How much is a gill of liquid in modern measurements?",
        "What is a wine-glass of brandy in ml?",
        "Convert 1 drachm to grams",
    ]
    for q in cases:
        r = post("convert", q)
        if r.status_code == 200 and r.json().get("answer"):
            ok(f"{q[:55]}  ({r.json()['latency_ms']}ms)")
        else:
            fail(q[:55], str(r.status_code))


def test_explain():
    print("\n── /v1/explain ───────────────────────────────────────────────")
    cases = [
        "What does 'lard the meat' mean in old recipes?",
        "What is a salamander in Victorian cooking?",
        "What does 'scald the milk' mean?",
    ]
    for q in cases:
        r = post("explain", q)
        if r.status_code == 200 and r.json().get("answer"):
            ok(f"{q[:55]}  ({r.json()['latency_ms']}ms)")
        else:
            fail(q[:55], str(r.status_code))


def test_crossref():
    print("\n── /v1/crossref ──────────────────────────────────────────────")
    for ingredient in ["butter", "lard", "eggs"]:
        r = get(f"crossref/{ingredient}")
        if r.status_code == 200:
            d = r.json()
            subs = len(d.get("substitutes", []))
            ok(f"crossref/{ingredient} → {subs} substitutes")
        elif r.status_code == 503:
            print(f"  SKIP  crossref/{ingredient} (index not built yet)")
        else:
            fail(f"crossref/{ingredient}", str(r.status_code))

    r = get("crossref/xyzzy_fake_ingredient_12345")
    if r.status_code == 404:
        ok("crossref unknown → 404")
    else:
        fail("crossref unknown → 404", str(r.status_code))


def test_stats():
    print("\n── /v1/stats ─────────────────────────────────────────────────")
    r = get("stats")
    if r.status_code == 200:
        d = r.json()
        ok(f"stats ok — {d.get('total_ingredients', '?')} ingredients")
    elif r.status_code == 503:
        print("  SKIP  stats (crossref not built yet)")
    else:
        fail("stats", str(r.status_code))


def test_top_k():
    print("\n── top_k parameter ───────────────────────────────────────────")
    for k in [1, 3, 10]:
        r = post("substitute", "substitute for butter", top_k=k)
        if r.status_code == 200:
            sources = r.json().get("sources", [])
            ok(f"top_k={k} → {len(sources)} sources")
        else:
            fail(f"top_k={k}", str(r.status_code))


def test_response_schema():
    print("\n── Response schema ───────────────────────────────────────────")
    r = post("substitute", "substitute for cream")
    if r.status_code != 200:
        fail("response schema check", str(r.status_code))
        return
    d = r.json()
    for field in ("answer", "sources", "query_type", "latency_ms"):
        if field in d:
            ok(f"field '{field}' present")
        else:
            fail(f"field '{field}' present")

    if d.get("sources"):
        src = d["sources"][0]
        for field in ("ingredient", "substitute", "book", "year"):
            if field in src:
                ok(f"source field '{field}' present")
            else:
                fail(f"source field '{field}' present")


def main():
    print("Old Recipe Intelligence API — Test Suite")
    print("=" * 60)

    test_health()
    test_auth()
    test_validation()
    test_substitute()
    test_modernise()
    test_convert()
    test_explain()
    test_crossref()
    test_stats()
    test_top_k()
    test_response_schema()
    test_confidence()
    test_batch()

    print(f"\n{'='*60}")
    print(f"Results: {PASSED} passed, {FAILED} failed")
    sys.exit(0 if FAILED == 0 else 1)


if __name__ == "__main__":
    main()


def test_batch():
    print("\n── /v1/substitute/batch ──────────────────────────────────────")
    r = requests.post(
        f"{BASE}/substitute/batch",
        json={"ingredients": ["lard", "buttermilk", "suet"]},
        headers=HEADERS,
        timeout=120,
    )
    if r.status_code != 200:
        fail("batch returns 200", str(r.status_code))
        return
    d = r.json()
    if "results" in d and "total_ms" in d:
        ok(f"batch schema ok — {len(d['results'])} results, {d['total_ms']}ms total")
    else:
        fail("batch schema", "missing results or total_ms")

    for item in d.get("results", []):
        for field in ("ingredient", "answer", "sources", "confidence", "latency_ms"):
            if field not in item:
                fail(f"batch item missing '{field}'")
                return
    ok("batch item schema complete")

    # Error: too many ingredients
    r = requests.post(
        f"{BASE}/substitute/batch",
        json={"ingredients": [f"ing{i}" for i in range(21)]},
        headers=HEADERS, timeout=10,
    )
    if r.status_code == 400:
        ok("batch > 20 ingredients → 400")
    else:
        fail("batch > 20 ingredients → 400", str(r.status_code))


def test_confidence():
    print("\n── confidence field ──────────────────────────────────────────")
    r = post("substitute", "substitute for butter")
    if r.status_code == 200:
        d = r.json()
        if "confidence" in d and isinstance(d["confidence"], (int, float)):
            ok(f"confidence present: {d['confidence']}")
        else:
            fail("confidence field present and numeric")
    else:
        fail("confidence check", str(r.status_code))
