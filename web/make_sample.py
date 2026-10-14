"""Sinh web/sample-data.js cho dashboard spy (chế độ DATA_MODE="sample").

Nguồn thật (chỉ đọc): ..\\4-SPY\\data\\shopify\\wondroot.com\\2026-10-14.json,
..\\4-SPY\\data\\etsy\\{StayNaturalStore,grossbale}\\2026-10-14.json, ..\\4-SPY\\data\\discover\\shops.json.
Phần BỊA (ghi rõ "sample" trong source): series 14 ngày, rank_7d, 2 shop woodemon.com /
carpenter-farmhouse.com, ngày ads, alerts. Chạy: python web/make_sample.py
"""
import json, re, random, datetime as dt
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPY = HERE.parent.parent / "4-SPY" / "data"
OUT = HERE / "sample-data.js"
TODAY = dt.date(2026, 10, 14)
NOW = "2026-10-14T23:05:00Z"
VND_PER_USD = 24780  # Etsy trả giá VND khi xem từ VN; 246570 VND ≈ $9.95
random.seed(14)

def d(n):  # ngày cách hôm nay n ngày
    return (TODAY - dt.timedelta(days=n)).isoformat()

DATES = [d(i) for i in range(13, -1, -1)]

THEMES = [
    ("dinosaur", r"dino|t[- ]?rex|triceratops"), ("safari", r"safari|jungle|lion|giraffe|elephant|zebra|rhino"),
    ("space", r"space|astronaut|rocket|planet|moon|star"), ("ocean", r"ocean|whale|dolphin|turtle|sea|nautical|fish"),
    ("farm", r"farm|barn|cow|pig|horse|pony|tractor|sheep"), ("western", r"cowboy|cowgirl|western|rodeo"),
    ("sports", r"sport|football|soccer|baseball|basketball|hockey"), ("bunny", r"bunny|rabbit"), ("bee", r"\bbee|honey"),
    ("woodland", r"woodland|forest|fox|deer|bear|owl|mountain"), ("boho", r"boho|rainbow|dreamcatcher"),
    ("floral", r"floral|flower|rose|daisy|butterfly|peony|wildflower|sunflower|lavender"),
    ("christmas", r"christmas|ornament|santa|noel"), ("monogram", r"monogram|initial|letter"),
]
SEASONS = [("christmas", r"christmas|ornament|santa|xmas"), ("halloween", r"halloween|pumpkin"),
           ("easter", r"easter"), ("valentine", r"valentine"), ("back-to-school", r"school")]

def tag_text(t):
    t = t.lower()
    theme = next((k for k, rx in THEMES if re.search(rx, t)), "khac")
    if re.search(r"monogram|initial|letter", t): layout = "chu-cai-canh"
    elif re.search(r"floral|flower|wreath", t) and re.search(r"script|cursive|name", t): layout = "script-hoa"
    elif re.search(r"plaque|scene|cutout", t): layout = "canh-ten"
    elif re.search(r"first.*middle|two names|2 names", t): layout = "ten-2-dong"
    else: layout = "khac"
    if re.search(r"script|cursive|calligraph", t): font = "script"
    elif re.search(r"block|bold|serif|monogram", t): font = "block"
    elif re.search(r"floral|boho", t): font = "script"
    else: font = "khac"
    season = [k for k, rx in SEASONS if re.search(rx, t)]
    return theme, layout, font, season

def size_prices(variants):
    out = {}
    for v in variants:
        m = re.search(r"(\d{1,2})\s*(?:in|\"|inch)", v.get("title", ""), re.I)
        if m and v.get("price") is not None:
            k = m.group(1)
            out[k] = min(out.get(k, 1e9), float(v["price"]))
    return {k: round(v, 2) for k, v in sorted(out.items(), key=lambda x: int(x[0]))}

def median(xs):
    xs = sorted(xs)
    if not xs: return None
    n = len(xs); return round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2, 2)

def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

data = {}
alerts = []
theme_counts = {}

def count_theme(theme, plat):
    theme_counts.setdefault(theme, {"shopify": 0, "etsy": 0})[plat] += 1

# ---------------- Shopify thật: wondroot ----------------
snap = load(SPY / "shopify" / "wondroot.com" / "2026-10-14.json")
by_handle = {p["handle"]: p for p in snap["products"]}
ranked = [h for h in snap["rank"] if h in by_handle][:60]
products = []
for i, h in enumerate(ranked, 1):
    p = by_handle[h]
    theme, layout, font, season = tag_text(p["title"] + " " + " ".join(p.get("tags", [])))
    r7 = max(1, i + random.randint(-6, 9)) if i > 3 else i + random.randint(0, 2)
    products.append({
        "handle": h, "title": p["title"], "image": p.get("image", ""), "url": p.get("url", ""),
        "published_at": (p.get("published_at") or "")[:10], "price_min": p.get("price_min"), "price_max": p.get("price_max"),
        "price_by_size": size_prices(p.get("variants", [])), "rank": i, "rank_7d": r7, "rank_30d": None,
        "tags": [t for t in p.get("tags", []) if not t.startswith("ops-")][:8], "season": season,
        "theme": theme, "layout": layout, "font": font, "is_niche": True,
    })
    count_theme(theme, "shopify")

pbs_all = {}
for p in products:
    for k, v in p["price_by_size"].items(): pbs_all.setdefault(k, []).append(v)
wr_price = {k: median(v) for k, v in pbs_all.items()}
n_total = len(snap["products"])
new7 = sum(1 for p in snap["products"] if (p.get("published_at") or "")[:10] >= d(7))
series = []
for i, day in enumerate(DATES):
    back = 13 - i
    pr = dict(wr_price)
    if back > 5 and "12" in pr: pr["12"] = round(pr["12"] + 3.0, 2)  # sample: đổi giá 12in 6 ngày trước
    series.append({"date": day, "n_products": n_total - back * 3, "n_niche": n_total - back * 3,
                   "n_new_7d": max(0, new7 - back), "price_by_size": pr, "rank_source": "best-selling"})
data["shopify/wondroot.com/summary.json"] = {
    "domain": "wondroot.com", "name": "Wondroot", "updated_at": NOW,
    "source": "products.json + collections/all?sort_by=best-selling (sample: 60 SP đầu theo rank thật 14/10; series 13 ngày trước bịa)",
    "series": series, "products": products}

# ---------------- Shopify giả lập ----------------
SIM_TITLES = {
    "woodemon.com": ["Custom Wooden Name Sign Floral Wreath Script", "Personalized Dinosaur Name Puzzle Sign", "Boho Rainbow Nursery Name Sign",
                     "Woodland Fox & Bear Layered Name Sign", "Safari Animals Nursery Plaque", "Script Name Sign with Butterflies",
                     "Ocean Whale Wooden Name Cutout", "Christmas Ornament Personalized Baby Name", "Monogram Letter with Flowers Sign",
                     "Space Astronaut Name Plaque", "Farm Barn Cow Name Sign", "Bunny Floral Script Name Sign", "Bee Honey Nursery Name Sign",
                     "Western Cowboy Boots Name Sign", "Sports Baseball Name Plaque"],
    "carpenter-farmhouse.com": ["Farmhouse Barn Name Sign Rustic", "Tractor Farm Nursery Plaque", "Cowgirl Floral Script Name Sign",
                                "Woodland Deer Mountain Name Sign", "Wildflower Script Name Sign", "Halloween Pumpkin Kids Name Sign",
                                "Monogram Initial Rustic Sign", "Horse Pony Nursery Name Plaque", "Daisy Boho Name Sign",
                                "Easter Bunny Personalized Sign", "Back to School Name Board", "Christmas Santa Ornament Name"],
}
SIM_BASE = {"woodemon.com": (29.99, 2.6), "carpenter-farmhouse.com": (39.0, 3.1)}
SIZES = ["8", "10", "12", "14", "16", "18", "20", "24", "30"]
for dom, titles in SIM_TITLES.items():
    base, per = SIM_BASE[dom]
    prods = []
    n = 30
    for i in range(1, n + 1):
        t = titles[(i - 1) % len(titles)] + ("" if i <= len(titles) else f" v{(i - 1) // len(titles) + 1}")
        theme, layout, font, season = tag_text(t)
        pbs = {s: round(base + (int(s) - 8) * per * (1.6 if int(s) >= 24 else 1) - 0.01, 2) for s in SIZES if not (dom.startswith("carp") and s in ("8", "30"))}
        pub = d(random.randint(0, 80))
        prods.append({"handle": f"sample-{i}", "title": t, "image": "", "url": f"https://{dom}/products/sample-{i}",
                      "published_at": pub, "price_min": min(pbs.values()), "price_max": max(pbs.values()), "price_by_size": pbs,
                      "rank": i, "rank_7d": max(1, i + random.randint(-5, 6)), "rank_30d": None, "tags": [theme], "season": season,
                      "theme": theme, "layout": layout, "font": font, "is_niche": True})
        count_theme(theme, "shopify")
    pmed = {s: median([p["price_by_size"][s] for p in prods if s in p["price_by_size"]]) for s in SIZES}
    pmed = {k: v for k, v in pmed.items() if v}
    ser = []
    for i, day in enumerate(DATES):
        back = 13 - i
        pr = dict(pmed)
        if dom == "woodemon.com" and back > 3 and "24" in pr: pr["24"] = round(pr["24"] - 10, 2)
        ser.append({"date": day, "n_products": (180 if dom.startswith("wood") else 95) - back, "n_niche": (140 if dom.startswith("wood") else 61) - back,
                    "n_new_7d": random.randint(2, 9), "price_by_size": pr, "rank_source": "best-selling"})
    data[f"shopify/{dom}/summary.json"] = {"domain": dom, "name": dom.split(".")[0].replace("-", " ").title() + " (sample)",
                                           "updated_at": NOW, "source": "SAMPLE giả lập: số liệu bịa để thử giao diện", "series": ser, "products": prods}

# ---------------- Etsy thật ----------------
etsy_index = []
SALES_PER_DAY = {"StayNaturalStore": 9, "grossbale": 6}
for shop in ["StayNaturalStore", "grossbale"]:
    s = load(SPY / "etsy" / shop / "2026-10-14.json")
    info = s["info"]
    listings = []
    for lid, L in s["listings"].items():
        ct = L.get("chi_tiet") or {}
        cur = L.get("tien_te") or "USD"
        price = L.get("gia")
        if price is not None and cur == "VND": price = round(price / VND_PER_USD, 2); cur = "USD"
        theme, layout, font, season = tag_text(L["title"])
        listings.append({"id": lid, "title": L["title"], "url": L["url"], "image": L.get("img", ""), "price": price, "currency": cur,
                         "reviews": ct.get("review_listing"), "favorites": ct.get("favorites"), "bestseller": bool(L.get("bestseller")),
                         "in_carts": ct.get("trong_gio"), "listed_on": ct.get("listed_on"),
                         "favorites_7d": (random.randint(5, 120) if ct.get("favorites") else None),
                         "reviews_7d": (random.randint(0, 9) if ct.get("review_listing") else None),
                         "season": season, "theme": theme, "layout": layout, "font": font})
        count_theme(theme, "etsy")
    sales, rev, adm, nl = info["tong_sales"], info["so_review"], info["admirers"], info["so_listing"]
    rate = SALES_PER_DAY[shop]
    ser = []
    acc_s, acc_r = sales, rev
    vals = []
    for back in range(0, 14):
        vals.append((d(back), acc_s, acc_r))
        step = max(0, rate + random.randint(-4, 5) + (14 if (shop == "StayNaturalStore" and back == 2) else 0))
        acc_s -= step; acc_r -= random.randint(0, 3)
    for day, sv, rv in reversed(vals):
        ser.append({"date": day, "sales": sv, "reviews": rv, "admirers": adm - (13 - DATES.index(day)) * 2, "listings": nl})
    sd = {x["date"]: x["sales"] for x in ser}
    rd = {x["date"]: x["reviews"] for x in ser}
    data[f"etsy/{shop}/summary.json"] = {
        "shop": shop, "url": f"https://www.etsy.com/shop/{shop}", "updated_at": NOW,
        "source": "etsy shop page + listing page (JSON-LD) · sample: số hôm nay thật, 13 ngày trước bịa",
        "info": {"sales": sales, "reviews": rev, "rating": info.get("rating"), "admirers": adm, "listings": nl,
                 "since": info.get("mo_shop_tu"), "star_seller": info.get("star_seller"), "location": info.get("dia_diem"), "website": ""},
        "series": ser,
        "deltas": {"sales_1d": sales - sd[d(1)], "sales_7d": sales - sd[d(7)], "sales_30d": None, "reviews_7d": rev - rd[d(7)]},
        "listings": listings}
    etsy_index.append({"shop": shop, "last_ok": TODAY.isoformat(), "sales": sales})

# ---------------- Ads (số ads thật từ discover, ngày bịa) ----------------
disc = load(SPY / "discover" / "shops.json")
ads_index = []
for key in ["wondroot.com", "woodemon.com", "emmafy.com"]:
    v = disc.get(key, {})
    n = v.get("so_ads", 0)
    urls = v.get("vi_du_url", []) or [f"https://{key}/"]
    ads = []
    for i in range(n):
        start = random.choice([1, 2, 4, 6, 9, 12, 16, 21, 27, 33, 45])
        landing = urls[i % len(urls)].split("?")[0]
        handle = landing.split("/products/")[1] if "/products/" in landing else ""
        theme = tag_text(handle.replace("-", " "))[0] if handle else "khac"
        ads.append({"library_id": f"sample{key[:3]}{1000 + i}", "first_seen": d(start), "last_seen": TODAY.isoformat(), "days_running": start + 1,
                    "active": True, "text": f"[sample] Quảng cáo {key} #{i + 1}: Personalized wooden name sign — handmade, ships in 3-5 days.",
                    "landing": landing, "product_handle": handle, "theme": theme, "image": "", "platforms": ["facebook", "instagram"] if i % 3 else ["facebook"]})
    ser = [{"date": day, "n_active": max(0, n - (13 - j) // 4), "n_new": (1 if j % 4 == 0 else 0)} for j, day in enumerate(DATES)]
    data[f"ads/{key}/summary.json"] = {"key": key, "source": "Meta Ad Library (web) · sample: số ads thật 14/10, ngày bắt đầu bịa", "updated_at": NOW, "ads": ads, "series": ser}
    ads_index.append({"key": key, "last_ok": TODAY.isoformat(), "n_active": n})

# ---------------- Alerts (bịa từ dữ liệu trên) ----------------
wp = products
alerts += [
    {"date": d(0), "type": "rank_jump", "shop": "wondroot.com", "platform": "shopify", "title": wp[0]["title"], "url": wp[0]["url"], "image": wp[0]["image"], "detail": f"rank {wp[0]['rank_7d'] + 9} → 1", "value": 9},
    {"date": d(0), "type": "new_product", "shop": "wondroot.com", "platform": "shopify", "title": wp[1]["title"], "url": wp[1]["url"], "image": wp[1]["image"], "detail": "đăng 13/10", "value": 1},
    {"date": d(0), "type": "etsy_sales_spike", "shop": "StayNaturalStore", "platform": "etsy", "title": "Sales tăng vọt", "url": "https://www.etsy.com/shop/StayNaturalStore", "image": "", "detail": "+23 sales/ngày (TB 9)", "value": 23},
    {"date": d(1), "type": "new_ad", "shop": "woodemon.com", "platform": "ads", "title": "Ad mới trên Facebook", "url": "https://woodemon.com/", "image": "", "detail": "1 ad mới", "value": 1},
    {"date": d(1), "type": "ad_long", "shop": "emmafy.com", "platform": "ads", "title": "Ad chạy 46 ngày", "url": "https://emmafy.com/", "image": "", "detail": "chạy > 14 ngày", "value": 46},
    {"date": d(2), "type": "price_change", "shop": "woodemon.com", "platform": "shopify", "title": "Giá 24in", "url": "https://woodemon.com/", "image": "", "detail": "giá 24in tăng $10.00", "value": 10},
    {"date": d(3), "type": "new_listing", "shop": "grossbale", "platform": "etsy", "title": data["etsy/grossbale/summary.json"]["listings"][0]["title"], "url": data["etsy/grossbale/summary.json"]["listings"][0]["url"], "image": data["etsy/grossbale/summary.json"]["listings"][0]["image"], "detail": "listing mới", "value": 1},
    {"date": d(5), "type": "lost_bestseller", "shop": "StayNaturalStore", "platform": "etsy", "title": data["etsy/StayNaturalStore/summary.json"]["listings"][5]["title"], "url": data["etsy/StayNaturalStore/summary.json"]["listings"][5]["url"], "image": data["etsy/StayNaturalStore/summary.json"]["listings"][5]["image"], "detail": "mất badge Bestseller", "value": 0},
    {"date": d(6), "type": "price_change", "shop": "wondroot.com", "platform": "shopify", "title": "Giá 12in", "url": "https://wondroot.com/", "image": "", "detail": "giá 12in giảm $3.00", "value": -3},
    {"date": d(8), "type": "new_theme", "shop": "wondroot.com", "platform": "shopify", "title": "Theme mới: sports", "url": "https://wondroot.com/", "image": "", "detail": "10 SP sports đầu tiên", "value": 10},
]
for a in alerts: a["sample"] = True
data["alerts.json"] = alerts

data["themes.json"] = {"themes": [k for k, _ in THEMES] + ["khac"], "layouts": ["chu-cai-canh", "canh-ten", "script-hoa", "ten-2-dong", "khac"],
                       "fonts": ["script", "block", "mixed", "khac"], "counts": theme_counts}

data["index.json"] = {
    "updated_at": NOW,
    "shopify": [{"domain": "wondroot.com", "name": "Wondroot", "first_seen": "2026-10-14", "last_ok": TODAY.isoformat(), "n_products": n_total},
                {"domain": "woodemon.com", "name": "Woodemon (sample)", "first_seen": d(13), "last_ok": TODAY.isoformat(), "n_products": 180},
                {"domain": "carpenter-farmhouse.com", "name": "Carpenter Farmhouse (sample)", "first_seen": d(13), "last_ok": d(1), "n_products": 95}],
    "etsy": etsy_index, "ads": ads_index, "dates": DATES}
# Cố ý KHÔNG có ads/emmafy.com? -> có. Cố ý thiếu: mine.json (để thử trạng thái thiếu file).

js = "// Sinh bởi make_sample.py — dữ liệu SAMPLE (một phần thật 14/10/2026, phần còn lại bịa để thử giao diện)\nwindow.SAMPLE_DATA = " + json.dumps(data, ensure_ascii=False, indent=0) + ";\n"
OUT.write_text(js, encoding="utf-8")
print("wrote", OUT, len(js) // 1024, "KB,", len(data), "files")
