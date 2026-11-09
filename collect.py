#!/usr/bin/env python3
"""Collects Hindu, Jain and Sikh news headlines and writes news.json for the V-SH app.
Free sources only: the GDELT news search (no key needed) and, optionally, RSS feeds you add below.
Only a headline, a short line, the source name and the link are saved: the story itself stays on the publisher's site.
If every source fails, the old news.json is left alone, so the app keeps showing the last good list."""
import json, os, re, sys, time, html, datetime, urllib.request, urllib.parse
import xml.etree.ElementTree as ET

OUT = os.environ.get("NEWS_OUT", "news.json")
KEEP_DAYS = 7          # older stories are dropped
MAX_PER_FAITH = 25     # the app shows at most 60 in all
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"

# What to ask GDELT for, per faith. Edit freely.
QUERIES = {
    "hindu": '(temple OR mandir OR "Hindu festival" OR Diwali OR "Ram Mandir" OR Kumbh OR Navratri OR pilgrimage OR "Char Dham" OR "Hindu priest")',
    "jain":  '(Jain OR Jainism OR Paryushan OR Mahavir OR "Jain temple" OR "Jain muni")',
    "sikh":  '(Sikh OR Gurdwara OR "Golden Temple" OR "Guru Nanak" OR Gurpurab OR Vaisakhi OR "Harmandir Sahib")',
}
# A headline must contain one of these words, so loosely related stories are left out.
MUST_HAVE = {
    "hindu": ["hindu", "temple", "mandir", "diwali", "navratri", "kumbh", "pilgrim", "ram ", "shiva", "krishna", "ganesh", "durga", "dham", "puja", "pooja", "yatra", "festival", "priest", "ayodhya", "kashi", "tirupati", "vaishno"],
    "jain":  ["jain", "mahavir", "paryushan", "muni", "tirthankar", "shatrunjaya"],
    "sikh":  ["sikh", "gurdwara", "gurudwara", "golden temple", "guru nanak", "gurpurab", "vaisakhi", "harmandir", "akal takht", "sgpc", "guru "],
}
# Headlines with these words are skipped (violence, crime, hate): the app is a calm family and heritage app.
BLOCK_WORDS = ["murder", "killed", "kills", "rape", "riot", "lynch", "stabbed", "shot dead", "terror", "bomb", "blast", "massacre", "suicide", "arrested", "arrest", "assault", "porn", "sex", "hate", "slur", "communal", "clash", "violence", "dead", "dies", "death toll", "stampede"]
BLOCK_DOMAINS = []     # add publisher domains you do not want, e.g. "example.com"

# Optional RSS feeds you choose (address, faith, source name). Empty to start; every feed must be https://
RSS_FEEDS = [
    # ("https://example.org/feed.xml", "hindu", "Example Times"),
]

def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vsh-news-collector/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(6 + 6 * i)    # GDELT asks for one request per 5 seconds
    print("failed:", url[:90], last, file=sys.stderr)
    return None

def iso(seendate):
    # GDELT gives 20261109T101500Z
    try:
        return datetime.datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")

def clean_title(t):
    t = html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()
    t = re.sub(r"\s+", " ", t)
    return t

def ok_story(faith, title, url):
    low = " " + title.lower() + " "
    if len(title) < 20 or len(title) > 200: return False
    if not re.match(r"^https://[^\s]+$", url): return False
    if any(d and d in url.lower().split("/")[2] for d in BLOCK_DOMAINS): return False
    if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in BLOCK_WORDS): return False
    if not any(w in low for w in MUST_HAVE[faith]): return False
    if title.isupper(): return False
    return True

def from_gdelt(faith, raw=None):
    if raw is None:
        q = urllib.parse.urlencode({"query": QUERIES[faith] + " sourcelang:english", "mode": "ArtList", "format": "json",
                                    "maxrecords": "75", "timespan": "3d", "sort": "DateDesc"})
        raw = get(GDELT + "?" + q)
        time.sleep(6)
    if not raw: return None
    try:
        arts = json.loads(raw).get("articles", [])
    except Exception as e:
        print("bad GDELT answer for", faith, e, file=sys.stderr); return None
    out = []
    for a in arts:
        t, u = clean_title(a.get("title")), (a.get("url") or "").strip()
        if ok_story(faith, t, u):
            out.append({"faith": faith, "title": t, "summary": "", "source": (a.get("domain") or "").replace("www.", "")[:60], "url": u, "ts": iso(a.get("seendate", ""))})
    return out

def from_rss(url, faith, source, raw=None):
    raw = raw or get(url)
    if not raw: return None
    out = []
    try:
        root = ET.fromstring(raw)
    except Exception as e:
        print("bad RSS", url, e, file=sys.stderr); return None
    for it in root.iter("item"):
        t = clean_title(it.findtext("title")); u = (it.findtext("link") or "").strip()
        s = clean_title(it.findtext("description"))[:200]
        try: ts = datetime.datetime(*time.strptime(it.findtext("pubDate")[:25], "%a, %d %b %Y %H:%M:%S")[:6]).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception: ts = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
        if ok_story(faith, t, u):
            out.append({"faith": faith, "title": t, "summary": s, "source": source[:60], "url": u, "ts": ts})
    return out

def main():
    old = []
    try: old = json.load(open(OUT, encoding="utf8")).get("items", [])
    except Exception: pass
    new, any_ok = [], False
    test = os.environ.get("NEWS_TEST_GDELT")       # a folder of pretend answers (gdelt_<faith>.json), used only for testing
    for faith in QUERIES:
        raw = open(os.path.join(test, "gdelt_%s.json" % faith), "rb").read() if test else None
        r = from_gdelt(faith, raw)
        if r is not None: any_ok = True; new += r
    for url, faith, source in RSS_FEEDS:
        r = from_rss(url, faith, source)
        if r is not None: any_ok = True; new += r
    if not any_ok:
        print("No source answered: keeping the old news.json."); return
    cutoff = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen, items = set(), []
    for x in sorted(new + old, key=lambda x: x.get("ts", ""), reverse=True):
        key = x["url"]; tkey = (x["faith"], re.sub(r"\W+", "", x["title"].lower())[:60])
        if key in seen or tkey in seen or x.get("ts", "") < cutoff: continue
        seen.add(key); seen.add(tkey); items.append(x)
    counts, final = {}, []
    for x in items:
        if counts.get(x["faith"], 0) >= MAX_PER_FAITH: continue
        counts[x["faith"]] = counts.get(x["faith"], 0) + 1; final.append(x)
    final = final[:60]
    if not final:
        print("Nothing usable found: keeping the old news.json."); return
    json.dump({"updated": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ"), "items": final}, open(OUT, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print("wrote", len(final), "stories:", counts)

if __name__ == "__main__":
    main()
