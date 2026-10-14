# -*- coding: utf-8 -*-
r"""run_local.py — phần thu chạy ở MÁY ANH HOÀNG qua Chrome 9230 (FB / SimilarWeb / Etsy chặn IP cloud).

Ba phần (mặc định chạy cả ba, theo thứ tự ads → etsy → traffic):
  1. ads      Meta Ad Library: số "~N results" ở đầu trang + phần thẻ đã tải sẵn (cuộn ≤ 2 lần), mọi shop Shopify.
              → data/raw/<ngày>/ads.json
  2. etsy     trang shop Etsy (CHỈ trang shop: sales, review, rating, admirers, số listing), dùng
              doc_shop_info của ..\4-SPY\spy_etsy.py (import, không sửa). → data/raw/<ngày>/etsy.json
  3. traffic  SimilarWeb, TỐI ĐA 3 shop/ngày (giới hạn miễn phí của SimilarWeb, KHÔNG lách):
              shop chưa tra / tra lâu nhất trước, cùng hạng thì shop nhiều ads trước. → data/traffic.json
Mỗi phần mở 1 tab mới qua cdp.Tab của 4-SPY, đọc xong LUÔN đóng; không đụng tab khác.

    python collect/run_local.py                         # cả ba phần
    python collect/run_local.py --ads-only --limit 5
    python collect/run_local.py --etsy-only --limit 3
    python collect/run_local.py --traffic-only --traffic-max 2
    python collect/run_local.py --ads-only --only wondroot.com,woodemon.com
    python collect/run_local.py --no-traffic            # ads + etsy
    python collect/run_local.py --reparse-traffic <file.txt> <domain>   # đọc lại text SimilarWeb đã lưu (không tốn lượt)
Mã thoát: 0 nếu có ít nhất 1 phần ghi được dữ liệu, 1 nếu không, 2 nếu Chrome 9230 chưa bật.
"""
import argparse
import datetime as dt
import re
import sys
import time
import types
import urllib.parse
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (HERE, ROOT, TRAFFIC_FILE, active_shops, load_json, load_raw, log, norm_domain,  # noqa: E402
                    now_utc, parse_k, save_json, save_raw, today_vn, utf8_stdout)

LOG_DIR = HERE / "logs"
SW_DAILY_LIMIT = 3

# ====================================================================== 1. FB Ad Library

FB_URL = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=ALL&q={q}"
          "&search_type=keyword_unordered&media_type=all")
FB_SRC = "Meta Ad Library (web, country=ALL): số ~N results + thẻ đã tải (không cuộn hết)"

# Thẻ ad (giống collect/run_ads.py cũ, bỏ ảnh): mỗi thẻ có "Library ID: <số>"
JS_ADS = r"""
(() => {
  const out = [];
  const labels = Array.from(document.querySelectorAll('span,div'))
      .filter(e => e.childElementCount === 0 && /^Library ID:?\s*\d+/.test(e.textContent.trim()));
  for (const el of labels) {
    const id = (el.textContent.match(/\d{6,}/) || [''])[0];
    let card = el, p = el.parentElement;
    while (p) {
      const n = (p.textContent.match(/Library ID/g) || []).length;
      if (n > 1) break;
      card = p; p = p.parentElement;
    }
    const links = Array.from(card.querySelectorAll('a[href]')).map(a => a.href).filter(h => h.startsWith('http'));
    out.push({id, links, text: card.innerText.slice(0, 3000)});
  }
  const head = document.body ? document.body.innerText.slice(0, 6000) : '';
  return {cards: out, head, url: location.href};
})()
"""
RE_RESULTS = re.compile(r"(~?)\s*(\d[\d,.]*\s*[KkMm]?)\s+results?\b")
RE_NO_ADS = re.compile(r"No ads match|No results", re.I)
RE_BLOCK_FB = re.compile(r"log in to continue|you must log in|temporarily blocked|"
                         r"confirm you.re human|security check", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
RE_START1 = re.compile(r"Started running on\s+(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})")
RE_START2 = re.compile(r"Started running on\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})")
NOISE = re.compile(r"^(​|Active|Inactive|Platforms|Open Drop-down|See ad details|See summary details|Sponsored|"
                   r"This ad has multiple versions|Library ID.*|Started running on.*|\d+ ads? use(s)? this creative and text|"
                   r"Shop Now|Learn More|Sign Up|Order Now|Buy Now|See Details|Book Now|Get Offer|Send Message|"
                   r"Contact Us|Download|Watch More|Apply Now|Get Quote|Subscribe|Low impression count|\d+:\d+ / \d+:\d+)$", re.I)


def parse_start(text):
    for rx, order in ((RE_START1, "dmy"), (RE_START2, "mdy")):
        m = rx.search(text or "")
        if m:
            a, b, y = m.groups()
            day, mon = (a, b) if order == "dmy" else (b, a)
            mo = MONTHS.get(mon.lower()[:3])
            try:
                return dt.date(int(y), mo, int(day)).isoformat() if mo else None
            except ValueError:
                return None
    return None


def parse_card(c, unwrap):
    t = c.get("text") or ""
    lines = [x.strip() for x in t.split("\n")]
    page_name, body = "", []
    if "Sponsored" in lines:
        i = lines.index("Sponsored")
        page_name = next((x for x in reversed(lines[:i]) if x and not NOISE.match(x)), "")
        body = [x for x in lines[i + 1:] if not NOISE.match(x)]
    else:
        body = [x for x in lines if x and not NOISE.match(x)]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(body).strip())
    links = [unwrap(x) for x in c.get("links") or []]
    links = [x for x in links if not re.search(r"facebook\.com|fb\.me|instagram\.com|metastatus|meta\.com", x)]
    return {"page": page_name, "text": text, "links": links, "start": parse_start(t)}


def pick_landing(links, domain):
    good = [x for x in links if domain in (urllib.parse.urlsplit(x).hostname or "")]
    prod = [x for x in good if "/products/" in x]
    best = (prod or good or [""])[0]
    return best.split("?")[0] if "/products/" in best else best


class FbBlocked(RuntimeError):
    pass


def fb_one(tab, domain, date, scroll, unwrap):
    """Trả record ads cho 1 domain. Ném FbBlocked nếu FB đòi login / chặn."""
    t0 = time.time()
    url = FB_URL.format(q=urllib.parse.quote(domain))
    tab.goto(url, wait=2.5)
    r, n_results, approx, no_ads = {}, None, False, False
    for _ in range(14):   # chờ tối đa ~14 s cho số "results" + thẻ đầu tiên
        r = tab.eval(JS_ADS, timeout=60) or {}
        head = r.get("head") or ""
        if "/login" in (r.get("url") or "") or RE_BLOCK_FB.search(head[:3000]):
            raise FbBlocked(f"FB đòi login / chặn ở {r.get('url')}")
        m = RE_RESULTS.search(head)
        if m:
            approx, n_results = bool(m.group(1)), parse_k(m.group(2))
            if r.get("cards") or n_results == 0:
                break
        elif RE_NO_ADS.search(head):
            no_ads, n_results = True, 0
            break
        time.sleep(1)
    # cuộn ≤ 2 lần nếu FB còn thẻ chưa tải (không cuộn hết)
    for _ in range(scroll if (n_results or 0) > len(r.get("cards") or []) else 0):
        tab.eval("window.scrollTo(0, document.documentElement.scrollHeight - 1200);"
                 "window.dispatchEvent(new Event('scroll'));"
                 "[document.documentElement.scrollHeight, window.scrollY]")
        time.sleep(0.5)
        tab.eval("window.scrollTo(0, document.documentElement.scrollHeight);window.dispatchEvent(new Event('scroll'));"
                 "[document.documentElement.scrollHeight, window.scrollY]")
        time.sleep(2.5)
        r = tab.eval(JS_ADS, timeout=60) or r
    cards, seen = [], set()
    for c in r.get("cards") or []:
        if c.get("id") and c["id"] not in seen:
            seen.add(c["id"])
            cards.append(c)
    matched = []
    for c in cards:
        a = parse_card(c, unwrap)
        doms = {norm_domain(x) for x in a["links"]}
        if any(d == domain or d.endswith("." + domain) for d in doms if d) or domain in a["text"].lower():
            a["id"] = c["id"]
            a["landing"] = pick_landing(a["links"], domain)
            matched.append(a)
    d0 = dt.date.fromisoformat(date)
    starts = sorted(a["start"] for a in matched if a["start"])
    new7 = sum(1 for s in starts if (d0 - dt.date.fromisoformat(s)).days <= 7)
    pages = Counter(a["page"] for a in matched if a["page"]).most_common(3)
    # 3 mẫu: nội dung khác nhau, ad mới chạy trước
    samples, texts = [], set()
    for a in sorted(matched, key=lambda a: a["start"] or "", reverse=True):
        key = a["text"][:120]
        if key in texts:
            continue
        texts.add(key)
        samples.append({"id": a["id"], "start": a["start"], "page": a["page"], "text": a["text"][:300],
                        "landing": a["landing"]})
        if len(samples) >= 3:
            break
    n_cards = len(cards)
    ratio = round(len(matched) / n_cards, 3) if n_cards else None
    if n_results == 0:
        est = 0
    elif n_results is not None and ratio is not None:
        est = round(n_results * ratio)
    else:
        est = None
    rec = {"status": "ok" if n_results is not None else "loi", "n_results": n_results, "approx": approx,
           "n_cards": n_cards, "n_match": len(matched), "match_ratio": ratio, "ads_est": est, "new_7d": new7,
           "oldest_start": starts[0] if starts else None,
           "oldest_days": (d0 - dt.date.fromisoformat(starts[0])).days if starts else None,
           "pages": [[p, n] for p, n in pages], "samples": samples, "url": url, "at": now_utc(),
           "src": FB_SRC, "secs": round(time.time() - t0, 1)}
    if no_ads:
        rec["no_ads"] = True
    return rec


def run_ads(cdp, discover, shops, date, a):
    doc = load_raw(date, "ads")
    ok, times, fails = 0, [], 0
    t_all = time.time()
    with cdp.Tab() as tab:
        # tab nền: giả lập đang focus để FB chịu render / tải thêm (không cướp focus tab khác)
        for m, p in (("Emulation.setFocusEmulationEnabled", {"enabled": True}),
                     ("Page.setWebLifecycleState", {"state": "active"})):
            try:
                tab.send(m, p)
            except Exception:  # noqa: BLE001
                pass
        for i, s in enumerate(shops):
            dom = s["domain"]
            if i:
                time.sleep(a.delay)
            try:
                rec = fb_one(tab, dom, date, a.scroll, discover.unwrap)
            except FbBlocked as ex:
                log(f"  !! {dom}: {ex} → DỪNG phần ads (không lách)")
                doc["blocked"] = f"{now_utc()} {ex}"
                save_raw(date, "ads", doc)
                break
            except Exception as ex:  # noqa: BLE001
                log(f"  ! {dom}: {type(ex).__name__}: {str(ex)[:160]}")
                fails += 1
                if fails >= 4:
                    log("  !! lỗi 4 lần liền → dừng phần ads")
                    break
                continue
            times.append(rec["secs"])
            if rec["status"] != "ok":
                fails += 1
                log(f"  ! {dom}: không đọc được số results ({rec['secs']}s)")
                if fails >= 4:
                    log("  !! không đọc được 4 lần liền → dừng phần ads (FB đổi giao diện / chặn?)")
                    break
                continue
            fails = 0
            ok += 1
            doc["shops"][s["id"]] = rec
            save_raw(date, "ads", doc)   # ghi sau mỗi shop: chết giữa chừng vẫn giữ phần đã thu
            log(f"  [{i + 1}/{len(shops)}] {dom}: {'~' if rec['approx'] else ''}{rec['n_results']} results · "
                f"{rec['n_match']}/{rec['n_cards']} thẻ khớp · ước {rec['ads_est']} · mới 7d {rec['new_7d']} · "
                f"cũ nhất {rec['oldest_start']} · {rec['secs']}s")
    tot = time.time() - t_all
    if times:
        log(f"ADS: {ok}/{len(shops)} shop OK · TB {sum(times) / len(times):.1f} s/shop · tổng {tot:.0f} s")
    return ok


# ====================================================================== 2. Etsy (chỉ trang shop)

def run_etsy(spy_etsy, cdp, shops, date, a):
    doc = load_raw(date, "etsy")
    args = types.SimpleNamespace(max_pages=len(shops) + 2, delay_min=4.0, delay_max=8.0)
    R = spy_etsy.Runner(args)
    ok = 0
    t0 = time.time()
    with cdp.Tab() as tab:
        R.tab = tab
        for s in shops:
            name = s["etsy"]
            if R.het_luot():
                log("  !! Etsy chặn / hết lượt → dừng")
                break
            t1 = time.time()
            if not R.mo(f"https://www.etsy.com/shop/{name}"):
                log(f"  ! {name}: bị chặn")
                continue
            d = tab.eval(spy_etsy.JS_SHOP) or {}
            if "/shop/" not in (d.get("url") or "") or re.search(r"(?i)couldn.t find|not available|page not found",
                                                                 d.get("title") or ""):
                log(f"  ! {name}: trang shop không hợp lệ ({d.get('url')})")
                doc["shops"][s["id"]] = {"status": "khong_co", "at": now_utc(), "url": d.get("url")}
                save_raw(date, "etsy", doc)
                continue
            info = spy_etsy.doc_shop_info(d, name)
            rec = {"status": "ok" if info.get("tong_sales") is not None else "thieu",
                   "sales": info.get("tong_sales"), "reviews": info.get("so_review"), "rating": info.get("rating"),
                   "admirers": info.get("admirers"), "listings": info.get("so_listing"),
                   "star_seller": info.get("star_seller"), "location": info.get("dia_diem"),
                   "since": info.get("mo_shop_tu"), "url": f"https://www.etsy.com/shop/{name}",
                   "at": now_utc(), "src": "Etsy trang shop (Chrome 9230)", "secs": round(time.time() - t1, 1)}
            doc["shops"][s["id"]] = rec
            save_raw(date, "etsy", doc)
            ok += rec["status"] == "ok"
            log(f"  {name}: sales {rec['sales']} · review {rec['reviews']} ({rec['rating']}) · admirers {rec['admirers']}"
                f" · listing {rec['listings']} · {rec['secs']}s")
    if R.canh_bao:
        log("  cảnh báo Etsy: " + " | ".join(R.canh_bao))
    log(f"ETSY: {ok}/{len(shops)} shop OK · {time.time() - t0:.0f} s")
    return ok


# ====================================================================== 3. SimilarWeb

SW_URL = "https://www.similarweb.com/website/{d}/"
SW_SRC = "SimilarWeb (web miễn phí, Chrome 9230)"
MON3 = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
RE_SW_BLOCK = re.compile(r"Pardon Our Interruption|Access Denied|verify you are (a )?human|are you a robot|captcha|"
                         r"unusual activity", re.I)
RE_SW_QUOTA = re.compile(r"(\d+)\s+(?:of|/)\s+(\d+)\s+(?:free\s+)?(?:daily\s+)?searches?", re.I)
RE_SW_LIMIT = re.compile(r"hit your search limit|reached (?:your|the) (?:daily )?(?:limit|search limit)|"
                         r"no (?:more )?searches (?:remaining|left)", re.I)


def _num_after(label, text, pat):
    m = re.search(label + r"\s*[:\n]?\s*" + pat, text, re.I)
    return m.group(1) if m else None


def month_key(mon, year_hint, today):
    mo = MON3.index(mon.upper()[:3]) + 1
    if year_hint:
        y = int(year_hint)
    else:
        y = today.year if mo <= today.month else today.year - 1
    return f"{y}-{mo:02d}"


def parse_similarweb(text, final_url, domain, today=None):
    """Đọc text trang SimilarWeb → dict. status: ok | no_data | blocked | limit | loi."""
    today = today or dt.date.today()
    path = urllib.parse.urlsplit(final_url or "").path.rstrip("/")
    out = {"status": "loi"}
    q = RE_SW_QUOTA.search(text)
    if q:
        out["quota_remaining"], out["quota_total"] = int(q.group(1)), int(q.group(2))
    if RE_SW_BLOCK.search(text[:5000]) and len(text) < 4000:
        out["status"] = "blocked"
        return out
    if path.endswith("/website") or (domain not in (final_url or "").lower()):
        out["status"] = "no_data"
        return out
    # bản miễn phí hết lượt: banner "You've hit your search limit" ở đầu trang, mọi số là "- -"
    if RE_SW_LIMIT.search(text[:3000]):
        out["status"] = "limit"
        return out
    # Tổng visits (thử 14/10, prints10.com): "Total Visits Last 3 Months / JUL / AUG / SEP / <1M / VISITS /
    # Compare prints10.com to: / 276.5K / prints10.com"
    dm = re.escape(domain)
    m = re.search(r"Compare\s+" + dm + r"\s+to:?\s*\n\s*(\d[\d.,]*\s*[KMB]?)\s*\n\s*" + dm, text, re.I)
    vis = (m.group(1) if m else None) or _num_after(r"Total Visits", text, r"(\d[\d.,]*\s*[KMB]?)(?![\d.,%])")
    chg = _num_after(r"Last Month Change", text, r"([-−+]?\s*\d[\d.,]*)\s*%")
    m = re.search(r"has (increased|decreased) by (\d[\d.,]*)%", text, re.I)   # câu "...has increased by 75.4% compared to last month"
    if m and (chg is None or chg.strip() == m.group(2)):
        chg = ("-" if m.group(1).lower() == "decreased" else "") + m.group(2)
    bounce = _num_after(r"Bounce Rate", text, r"(\d[\d.,]*)\s*%")
    ppv = _num_after(r"Pages per Visit", text, r"(\d[\d.,]*)")
    dur = _num_after(r"Avg\.? Visit Duration", text, r"(\d{1,2}:\d{2}:\d{2})")
    rank = _num_after(r"Global Rank", text, r"#?\s*(\d[\d,]*)")
    if not vis and RE_SW_LIMIT.search(text):
        out["status"] = "limit"
        return out
    if not vis and re.search(r"(?i)not enough data|doesn.t have enough|we couldn.t find", text):
        out["status"] = "no_data"
        return out
    # tháng dữ liệu: "Sep 2026" (lấy cái cuối) hoặc chữ "SEP" gần chữ Visits
    mon = year = None
    mm = re.findall(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(20\d\d)\b", text, re.I)
    if mm:
        mon, year = mm[-1]
    else:
        k = text.find("Visits")
        m = re.search(r"\b(" + "|".join(MON3) + r")\b", text[max(0, k - 1500):k + 1500])
        if m:
            mon = m.group(1)
    # top country: dòng "Tên nước" rồi "62.16%" (sau tiêu đề Top Countries nếu có)
    countries = []
    i = max(text.find("Top Countries"), text.find("Top countries"))
    seg = text[i:i + 1500] if i >= 0 else ""
    j = seg.find("Demographics")
    seg = seg[:j] if j > 0 else seg
    # mỗi nước: tên rồi 1..n dòng "%"; lấy dòng % CUỐI (bản miễn phí có khi chèn "100%" của thanh tỉ lệ trước số thật)
    for cm in re.finditer(r"(?:^|\n)\s*([A-Z][A-Za-z .,'&()-]{2,40}?)\s*((?:\n\s*\d{1,3}(?:\.\d{1,2})?\s*%)+)", seg):
        name = cm.group(1).strip()
        if re.search(r"(?i)rate|visit|change|duration|traffic|other|total|search|direct|social|referral|mail|display|"
                     r"desktop|mobile|male|female|age|countries", name):
            continue
        pct = float(re.findall(r"(\d{1,3}(?:\.\d{1,2})?)\s*%", cm.group(2))[-1])
        if name not in [c["country"] for c in countries] and pct <= 100:
            countries.append({"country": name, "pct": pct})
        if len(countries) >= 5:
            break
    if not vis:
        return out
    out.update({
        "status": "ok", "visits": parse_k(vis), "visits_text": vis.strip(),
        "change_pct": float(chg.replace("−", "-").replace(" ", "").replace(",", "")) if chg else None,
        "bounce_pct": float(bounce.replace(",", "")) if bounce else None,
        "pages_per_visit": float(ppv.replace(",", "")) if ppv else None,
        "duration": dur, "global_rank": parse_k(rank) if rank else None,
        "month": month_key(mon, year, today) if mon else None,
        "top_countries": countries,
    })
    return out


def traffic_doc():
    return load_json(TRAFFIC_FILE, None) or {"updated_at": None, "domains": {}, "checks": []}


def store_traffic(doc, domain, res, date, src=SW_SRC, count_check=True):
    ent = doc["domains"].setdefault(domain, {"latest": None, "history": {}})
    rec = {k: v for k, v in res.items() if k not in ("quota_remaining", "quota_total")}
    rec.update({"checked": date, "at": now_utc(), "source": src})
    if res["status"] == "ok":
        ent["latest"] = rec
        if rec.get("month"):
            h = ent["history"].setdefault(rec["month"], {})
            h.update({"visits": rec["visits"], "change_pct": rec.get("change_pct"), "checked": date})
            h.pop("derived", None)
            # tháng trước suy từ % đổi (chỉ khi chưa có số thật của tháng đó)
            if rec.get("change_pct") is not None and rec.get("visits"):
                y, mo = map(int, rec["month"].split("-"))
                prev = f"{y - (mo == 1)}-{(mo - 2) % 12 + 1:02d}"
                if prev not in ent["history"]:
                    ent["history"][prev] = {"visits": round(rec["visits"] / (1 + rec["change_pct"] / 100)),
                                            "derived": True, "checked": date}
            ent["history"] = dict(sorted(ent["history"].items()))
    elif res["status"] == "no_data":
        ent["no_data"] = date
    ent["last_check"] = date
    ent["last_status"] = res["status"]
    if count_check:
        c = {"date": date, "domain": domain, "status": res["status"]}
        if "quota_remaining" in res:
            c["quota_remaining"] = res["quota_remaining"]
        doc["checks"].append(c)
        doc["checks"] = doc["checks"][-500:]
    doc["updated_at"] = now_utc()
    doc["domains"] = dict(sorted(doc["domains"].items()))
    save_json(TRAFFIC_FILE, doc, compact=False)


def traffic_queue(shops, doc, ads_raw):
    """Thứ tự tra: chưa tra trước, rồi tra lâu nhất; cùng hạng thì nhiều ads (ước) trước."""
    def key(s):
        ent = doc["domains"].get(s["domain"]) or {}
        last = ent.get("last_check") or ""
        ads = ((ads_raw.get("shops") or {}).get(s["id"]) or {}).get("ads_est") or 0
        return (last, -ads, s["domain"])
    return sorted(shops, key=key)


def run_traffic(cdp, shops, date, a, ads_raw):
    doc = traffic_doc()
    used = sum(1 for c in doc["checks"] if c["date"] == date and c.get("counted", True)
               and c["status"] in ("ok", "no_data", "limit", "loi"))
    left = min(a.traffic_max, SW_DAILY_LIMIT - used)
    if any(c["date"] == date and c["status"] == "limit" for c in doc["checks"]):
        left = 0   # SimilarWeb đã báo hết lượt hôm nay
    if left <= 0:
        log(f"TRAFFIC: hôm nay đã tra {used}/{SW_DAILY_LIMIT} lượt SimilarWeb → bỏ qua")
        return 0
    queue = traffic_queue(shops, doc, ads_raw)
    log(f"TRAFFIC: còn {left} lượt hôm nay (đã dùng {used}) · tra: {', '.join(s['domain'] for s in queue[:left])}")
    ok = 0
    (LOG_DIR / "similarweb").mkdir(parents=True, exist_ok=True)
    with cdp.Tab() as tab:
        for s in queue[:left]:
            dom = s["domain"]
            tab.goto(SW_URL.format(d=dom), wait=a.sw_wait)
            text = tab.text() or ""
            final = tab.final_url() or ""
            (LOG_DIR / "similarweb" / f"{date}_{dom}.txt").write_text(final + "\n\n" + text, encoding="utf-8")
            res = parse_similarweb(text, final, dom, dt.date.fromisoformat(date))
            log(f"  {dom}: {res.get('status')} · visits {res.get('visits_text')} · đổi {res.get('change_pct')}% · "
                f"bounce {res.get('bounce_pct')} · ppv {res.get('pages_per_visit')} · {res.get('duration')} · "
                f"tháng {res.get('month')} · top {[(c['country'], c['pct']) for c in res.get('top_countries') or []][:3]}"
                f" · quota còn {res.get('quota_remaining')}")
            if res["status"] == "blocked":
                log("  !! SimilarWeb chặn → DỪNG (không lách)")
                doc["checks"].append({"date": date, "domain": dom, "status": "blocked"})
                save_json(TRAFFIC_FILE, doc, compact=False)
                break
            store_traffic(doc, dom, res, date)
            ok += res["status"] == "ok"
            if res["status"] == "limit" or res.get("quota_remaining") == 0:
                log("  !! SimilarWeb báo hết lượt hôm nay → dừng")
                break
    return ok


# ====================================================================== main

def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Thu ads FB / Etsy / SimilarWeb qua Chrome 9230")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--ads-only", action="store_true")
    g.add_argument("--etsy-only", action="store_true")
    g.add_argument("--traffic-only", action="store_true")
    ap.add_argument("--no-traffic", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="chỉ N shop đầu mỗi phần (thử)")
    ap.add_argument("--only", default="", help="id shop cách nhau dấu phẩy (domain hoặc etsy:Ten)")
    ap.add_argument("--date", default="", help="ngày dữ liệu (mặc định hôm nay giờ VN)")
    ap.add_argument("--scroll", type=int, default=1, help="số lần cuộn tối đa trên Ad Library (0–2)")
    ap.add_argument("--delay", type=float, default=2.0, help="giây nghỉ giữa 2 shop (ads)")
    ap.add_argument("--traffic-max", type=int, default=SW_DAILY_LIMIT, help="số shop tra SimilarWeb lần này (≤ 3/ngày)")
    ap.add_argument("--sw-wait", type=float, default=12.0, help="giây chờ trang SimilarWeb render")
    ap.add_argument("--spy-dir", default=str(ROOT.parent / "4-SPY"))
    ap.add_argument("--reparse-traffic", nargs=2, metavar=("FILE", "DOMAIN"),
                    help="đọc lại file text SimilarWeb đã lưu ở collect/logs/similarweb (không tốn lượt), in kết quả")
    ap.add_argument("--save", action="store_true", help="dùng với --reparse-traffic: ghi kết quả vào traffic.json")
    a = ap.parse_args()
    a.scroll = max(0, min(2, a.scroll))
    date = a.date or today_vn()

    if a.reparse_traffic:
        f, dom = a.reparse_traffic
        raw = Path(f).read_text(encoding="utf-8")
        final, _, text = raw.partition("\n\n")
        fdate = Path(f).name[:10]
        res = parse_similarweb(text, final, dom, dt.date.fromisoformat(fdate))
        log(str(res))
        if a.save and res["status"] in ("ok", "no_data"):
            store_traffic(traffic_doc(), dom, res, fdate, count_check=False)
            log("đã ghi traffic.json")
        return

    sys.path.insert(0, a.spy_dir)
    try:
        import cdp  # noqa: E402
        import discover  # noqa: E402
    except ImportError as ex:
        sys.exit(f"Không import được cdp/discover từ {a.spy_dir}: {ex}")
    try:
        before = {t["id"] for t in cdp.list_tabs() if t.get("type") == "page"}
    except cdp.ChromeChuaBat as ex:
        log(str(ex))
        sys.exit(2)

    only = [x.strip() for x in a.only.split(",") if x.strip()]

    def pick(platform):
        lst = active_shops(platform)
        if only:
            lst = [s for s in lst if s["id"] in only or s.get("domain") in only or s.get("etsy") in only]
        return lst[: a.limit] if a.limit else lst

    do_ads = not (a.etsy_only or a.traffic_only)
    do_etsy = not (a.ads_only or a.traffic_only)
    do_traffic = not (a.ads_only or a.etsy_only or a.no_traffic)
    total = 0
    try:
        if do_ads:
            shops = pick("shopify")
            log(f"\n=== ADS ({len(shops)} shop Shopify) · {date}")
            total += run_ads(cdp, discover, shops, date, a)
        if do_etsy:
            import spy_etsy  # noqa: E402
            shops = pick("etsy")
            log(f"\n=== ETSY ({len(shops)} shop) · {date}")
            total += run_etsy(spy_etsy, cdp, shops, date, a)
        if do_traffic:
            shops = active_shops("shopify")
            if only:
                shops = [s for s in shops if s["id"] in only]
            log(f"\n=== TRAFFIC SimilarWeb · {date}")
            total += run_traffic(cdp, shops, date, a, load_raw(date, "ads"))
    except cdp.ChromeChuaBat as ex:
        log(str(ex))
        sys.exit(2)
    finally:
        time.sleep(1.5)   # /json/close bất đồng bộ
        try:
            after = {t["id"] for t in cdp.list_tabs() if t.get("type") == "page"}
            log(f"\nTab mới còn sót sau khi chạy: {len(after - before)} (tab có sẵn không đụng)")
        except Exception:  # noqa: BLE001
            pass
    sys.exit(0 if total else 1)


if __name__ == "__main__":
    main()
