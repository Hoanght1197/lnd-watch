# -*- coding: utf-8 -*-
"""build_summary.py — tổng hợp mọi snapshot thành JSON cho trang web (schema trong SPEC.md).

Đọc:  data/shopify/<domain>/<ngày>.json · data/etsy/<shop>/<ngày>.json · data/ads/<key>/<ngày>.json
Ghi:  data/shopify/<domain>/summary.json · data/etsy/<shop>/summary.json · data/ads/<key>/summary.json
      data/index.json · data/alerts.json · data/themes.json
Rồi:  ghi gọn snapshot thô (JSON không thụt dòng), xoá snapshot THÔ Shopify cũ hơn 30 ngày (summary giữ series cũ).

Thuần tính toán, chạy được trên Linux (Actions) và Windows. Idempotent: mọi mốc thời gian lấy từ dữ liệu
(fetched_at / ngày snapshot), không lấy giờ chạy → chạy lại cùng dữ liệu ra cùng file.
    python collect/build_summary.py            # build + xoá snapshot Shopify > 30 ngày
    python collect/build_summary.py --no-prune
Ghi chú:
  - Thời gian "trơn" (không múi giờ) trong snapshot của 4-SPY coi là giờ Việt Nam (UTC+7) rồi đổi sang UTC.
  - Series luôn tính lại từ snapshot thô. Riêng Shopify (thô bị xoá sau 30 ngày): series/first_seen cũ trong
    summary.json được giữ cho các ngày cũ hơn mốc xoá (ngày dữ liệu mới nhất - 30). Xoá tay 1 snapshot còn trong
    hạn thì series/alert của ngày đó mất theo ở lần build sau.
  - Alert tính lại từ snapshot cho 90 ngày gần nhất (tính từ ngày dữ liệu mới nhất); alert cũ hơn mốc xoá thô
    Shopify (30 ngày) giữ từ alerts.json cũ; dedupe theo (date, type, shop, url); mới nhất trước.
"""
import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
RULES_PATH = HERE / "themes_rules.json"
VN = dt.timezone(dt.timedelta(hours=7))
RE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

KEEP_ALERT_DAYS = 90
KEEP_RAW_SHOPIFY_DAYS = 30    # snapshot thô Shopify giữ 30 ngày (summary giữ series cũ)
RANK_JUMP_MIN = 5         # lên ≥ 5 bậc ...
RANK_JUMP_TOP = 20        # ... và vào top 20 thì báo
AD_LONG_DAYS = 14         # ad chạy > 14 ngày = có lời
MAX_ALERT_PER_GROUP = 40  # tối đa alert / (ngày, loại, shop) để shop nhập hàng loạt không làm ngập feed

# Giống NICHE_RE trong 4-SPY/discover.py (siết 14/10/2026) — chép lại để chạy trên cloud.
NICHE_RE = re.compile(r"name sign|nursery|name cutout|name plaque|name board|wood(?:en)? ?(?:name|sign|letter|wall|cut ?out)"
                      r"|baby name|kids? room|playroom|monogram sign|layered wood", re.I)

# Tỉ giá GẦN ĐÚNG để quy giá Etsy về USD (Etsy hiển thị theo tiền của trình duyệt quét, vd VND).
# Chỉ dùng để so sánh, field gốc price/currency vẫn giữ.
FX_USD = {"USD": 1.0, "VND": 1 / 26300, "EUR": 1.08, "GBP": 1.27, "CAD": 0.72, "AUD": 0.65, "JPY": 1 / 150, "INR": 1 / 84}

SOURCE_SHOPIFY = "products.json + collections/all?sort_by=best-selling"
SOURCE_ETSY = "etsy shop page + listing page (JSON-LD)"
SOURCE_ADS = "Meta Ad Library (web)"

# tag rác của app (không mang nghĩa design)
RE_TAG_JUNK = re.compile(r"^(ops-|catalog-|bestseller\d|_|no upsell|global recommendation|new-arrival)", re.I)


# ================================================================ tiện ích


def log(msg):
    print(msg, flush=True)


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    """Ghi JSON (ensure_ascii=False, indent=1); nội dung không đổi thì không ghi lại (giữ mtime, git sạch)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    s = json.dumps(obj, ensure_ascii=False, indent=1) + "\n"
    try:
        if path.read_text(encoding="utf-8") == s:
            return False
    except FileNotFoundError:
        pass
    tmp = path.with_suffix(".tmp")
    tmp.write_text(s, encoding="utf-8")
    os.replace(tmp, path)
    return True


def d2(s):
    return dt.date.fromisoformat(s)


def days_between(a, b):
    return (d2(b) - d2(a)).days


def shift(date, n):
    return (d2(date) + dt.timedelta(days=n)).isoformat()


def to_utc(ts):
    """'2026-10-14T12:28:32' (giờ VN) | '...Z' | '...+07:00' → '2026-10-14T05:28:32Z'."""
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=VN)
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def snapshot_dates(folder):
    return sorted(p.stem for p in Path(folder).glob("*.json") if RE_DATE.fullmatch(p.stem))


def pick_at_or_before(dates, target, tol):
    """Ngày snapshot gần nhất ≤ target nhưng không sớm hơn target - tol (ngày). Không có → None."""
    lo = shift(target, -tol)
    c = [d for d in dates if lo <= d <= target]
    return c[-1] if c else None


def median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def delta(a, b):
    a, b = num(a), num(b)
    return None if a is None or b is None else round(a - b, 2) if isinstance(a, float) or isinstance(b, float) else a - b


# ================================================================ nhãn theme / layout / font


class Rules:
    def __init__(self, path):
        r = load_json(path)
        if not r:
            sys.exit(f"Không đọc được {path}")
        self.themes = [(t["id"], re.compile(t["re"], re.I)) for t in r["themes"]]
        self.theme_labels = {t["id"]: t.get("label", t["id"]) for t in r["themes"]}
        self.layouts = [(l["id"], re.compile(l["re"], re.I), bool(l.get("need_theme"))) for l in r["layouts"]]
        self.layout_labels = {l["id"]: l.get("label", l["id"]) for l in r["layouts"]}
        self.fonts = {k: re.compile(v, re.I) for k, v in r["fonts"].items()}
        self.font_by_layout = r.get("font_theo_layout") or {}

    def theme(self, title, extra=""):
        best = None  # (vị trí, thứ tự, id)
        for i, (tid, rx) in enumerate(self.themes):
            m = rx.search(title or "")
            if m and (best is None or (m.start(), i) < best[:2]):
                best = (m.start(), i, tid)
        if best:
            return best[2]
        for tid, rx in self.themes:
            if extra and rx.search(extra):
                return tid
        return "khac"

    def label(self, title, tags=None, product_type=""):
        extra = " ".join((tags or [])) + " " + (product_type or "")
        theme = self.theme(title, extra.replace("-", " "))
        blob = f"{title or ''} {extra}"
        layout = "khac"
        for lid, rx, need_theme in self.layouts:
            if need_theme and theme == "khac":
                continue
            if rx.search(blob):
                layout = lid
                break
        s = bool(self.fonts.get("script") and self.fonts["script"].search(blob))
        b = bool(self.fonts.get("block") and self.fonts["block"].search(blob))
        mx = bool(self.fonts.get("mixed") and self.fonts["mixed"].search(blob))
        font = "mixed" if mx or (s and b) else "script" if s else "block" if b else \
            self.font_by_layout.get(layout, "khac")
        return theme, layout, font


def is_niche(title, tags=None, product_type=""):
    return bool(NICHE_RE.search(f"{title or ''} {' '.join(tags or [])} {product_type or ''}"))


# ================================================================ alert


class Alerts:
    def __init__(self):
        self.items = []

    def add(self, date, typ, shop, platform, title, url, image, detail, value):
        self.items.append({"date": date, "type": typ, "shop": shop, "platform": platform, "title": title or "",
                           "url": url or "", "image": image or "", "detail": detail or "", "value": value})


def cap_group(rows):
    """Giữ tối đa MAX_ALERT_PER_GROUP alert mỗi (ngày, loại, shop) — giữ thứ tự đã sắp."""
    out, cnt = [], {}
    for a in rows:
        k = (a["date"], a["type"], a["shop"])
        cnt[k] = cnt.get(k, 0) + 1
        if cnt[k] <= MAX_ALERT_PER_GROUP:
            out.append(a)
    return out


# ================================================================ Shopify

RE_SIZE_PAIR = re.compile(r"(\d+(?:\.\d+)?)\s*(?:in|\"|″|”)?\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(?:in\b|inch|inches|\"|″|”)", re.I)
RE_SIZE_ONE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:in\b|inch(?:es)?\b|\"|″|”|'')", re.I)


def size_of(variant_title):
    """Số inch từ variant title: '12 in', '12"', '12in', 'Small (7 inch)', '6.1 × 8.5 in' (→ cạnh lớn). Không có → None."""
    t = variant_title or ""
    m = RE_SIZE_PAIR.search(t)
    if m:
        v = max(float(m.group(1)), float(m.group(2)))
    else:
        m = RE_SIZE_ONE.search(t)
        if not m:
            return None
        v = float(m.group(1))
    if not 3 <= v <= 80:
        return None
    return str(int(v)) if v == int(v) else f"{v:g}"


def sort_sizes(d):
    return dict(sorted(d.items(), key=lambda kv: float(kv[0])))


def product_price_by_size(p):
    out = {}
    for v in p.get("variants") or []:
        s = size_of(v.get("title"))
        pr = v.get("price")
        if s and pr is not None and pr > 0:
            out[s] = min(out.get(s, pr), pr)
    return sort_sizes(out)


def clean_tags(tags):
    return [t for t in (tags or []) if t and not RE_TAG_JUNK.search(t)][:15]


class ShopifyShop:
    def __init__(self, domain, rules):
        self.domain = domain
        self.dir = DATA / "shopify" / domain
        self.rules = rules
        self.dates = snapshot_dates(self.dir)
        self._cache = {}

    def snap(self, date):
        if date not in self._cache:
            self._cache[date] = load_json(self.dir / f"{date}.json")
        return self._cache[date]

    def drop(self, date):
        self._cache.pop(date, None)

    def enrich(self, p):
        """Thông tin tính thêm cho 1 product thô (cache trên dict)."""
        if "_lbl" not in p:
            p["_lbl"] = self.rules.label(p.get("title"), p.get("tags"), p.get("product_type"))
            p["_niche"] = is_niche(p.get("title"), p.get("tags"), p.get("product_type"))
            p["_pbs"] = product_price_by_size(p)
        return p

    def series_entry(self, date, snap):
        prods = [self.enrich(p) for p in snap.get("products") or []]
        niche = [p for p in prods if p["_niche"]]
        lo = shift(date, -7)
        n_new = sum(1 for p in prods if lo < (p.get("published_at") or p.get("created_at") or "")[:10] <= date)
        sizes = {}
        for p in niche:
            for s, pr in p["_pbs"].items():
                sizes.setdefault(s, []).append(pr)
        pbs = sort_sizes({s: median(v) for s, v in sizes.items() if len(v) >= 1})
        return {"date": date, "n_products": len(prods), "n_niche": len(niche), "n_new_7d": n_new,
                "price_by_size": pbs, "rank_source": snap.get("rank_source") or "",
                "n_ranked": len(snap.get("rank") or [])}

    def rank_map(self, date):
        if not date:
            return {}
        s = self.snap(date)
        return {h: i + 1 for i, h in enumerate((s or {}).get("rank") or [])}

    def build(self, alerts, alert_from, purge_cut):
        if not self.dates:
            return None
        old = load_json(self.dir / "summary.json", {}) or {}
        series = [e for e in old.get("series") or [] if e.get("date", "") < purge_cut]  # ngày đã xoá thô theo hạn
        first_seen_prod = {}
        prev_snap, prev_date = None, None
        for date in self.dates:
            snap = self.snap(date)
            if not snap or not snap.get("products"):
                continue
            series.append(self.series_entry(date, snap))
            for p in snap["products"]:
                first_seen_prod.setdefault(p["handle"], date)
            if prev_snap and date >= alert_from:
                self.diff_alerts(alerts, prev_date, prev_snap, date, snap)
            if prev_date:
                self.drop(prev_date)  # giải phóng RAM, giữ 2 snapshot liền nhau
            prev_snap, prev_date = snap, date
        if not prev_snap:
            return None
        last_date, last = prev_date, prev_snap
        # snapshot cũ cho rank_7d / rank_30d
        r7 = self.rank_map(pick_at_or_before(self.dates, shift(last_date, -7), 3))
        r30 = self.rank_map(pick_at_or_before(self.dates, shift(last_date, -30), 7))
        r0 = {h: i + 1 for i, h in enumerate(last.get("rank") or [])}
        # first_seen sản phẩm: lấy cả từ summary cũ (ngày đã xoá thô)
        for p in old.get("products") or []:
            fs = p.get("first_seen")
            if fs and fs < purge_cut and fs < first_seen_prod.get(p.get("handle"), "9999"):
                first_seen_prod[p["handle"]] = fs
        products = []
        for p in last["products"]:
            self.enrich(p)
            theme, layout, font = p["_lbl"]
            products.append({
                "handle": p["handle"], "title": p.get("title") or "", "image": p.get("image") or "",
                "url": p.get("url") or f"https://{self.domain}/products/{p['handle']}",
                "published_at": (p.get("published_at") or p.get("created_at") or "")[:10] or None,
                "first_seen": first_seen_prod.get(p["handle"]),
                "price_min": p.get("price_min"), "price_max": p.get("price_max"),
                "price_by_size": p["_pbs"],
                "rank": r0.get(p["handle"]), "rank_7d": r7.get(p["handle"]), "rank_30d": r30.get(p["handle"]),
                "available": any(v.get("available") is not False for v in p.get("variants") or []),
                "tags": clean_tags(p.get("tags")),
                "product_type": p.get("product_type") or "",
                "theme": theme, "layout": layout, "font": font, "is_niche": p["_niche"],
            })
        products.sort(key=lambda x: (x["rank"] is None, x["rank"] or 0, x["published_at"] or "", x["handle"]))
        series.sort(key=lambda e: e["date"])
        name = last.get("shop_name") or old.get("name") or ""
        if not name:
            vend = {}
            for p in last["products"]:
                if p.get("vendor"):
                    vend[p["vendor"]] = vend.get(p["vendor"], 0) + 1
            name = max(vend, key=vend.get) if vend else self.domain
        return {"domain": self.domain, "name": name, "updated_at": to_utc(last.get("fetched_at")) or f"{last_date}T00:00:00Z",
                "source": SOURCE_SHOPIFY, "last_ok": last_date, "series": series, "products": products}

    def diff_alerts(self, alerts, pdate, prev, date, cur):
        dom = self.domain
        pm = {p["handle"]: self.enrich(p) for p in prev["products"]}
        cm = {p["handle"]: self.enrich(p) for p in cur["products"]}
        prank = {h: i + 1 for i, h in enumerate(prev.get("rank") or [])}
        crank = {h: i + 1 for i, h in enumerate(cur.get("rank") or [])}
        BIG = 10 ** 9
        # sản phẩm mới
        new = [cm[h] for h in cm if h not in pm]
        new.sort(key=lambda p: (crank.get(p["handle"], BIG), p["handle"]))
        for p in new:
            pub = (p.get("published_at") or "")[:10]
            alerts.add(date, "new_product", dom, "shopify", p.get("title"), p.get("url"), p.get("image"),
                       f"mẫu mới · đăng {pub or '?'} · ${p.get('price_min')}", p.get("price_min"))
        # đổi giá (theo size nếu có, không thì price_min)
        rows = []
        for h, c in cm.items():
            o = pm.get(h)
            if not o:
                continue
            ch = [(s, o["_pbs"][s], c["_pbs"][s]) for s in c["_pbs"] if s in o["_pbs"] and o["_pbs"][s] != c["_pbs"][s]]
            if ch:
                pick = next((x for x in ch if x[0] == "12"), ch[0])
                more = f" (+{len(ch) - 1} size khác)" if len(ch) > 1 else ""
                rows.append((c, f"{pick[0]}in ${pick[1]:g} → ${pick[2]:g}{more}", pick[2]))
            elif not c["_pbs"] and o.get("price_min") is not None and c.get("price_min") is not None \
                    and o["price_min"] != c["price_min"]:
                rows.append((c, f"giá từ ${o['price_min']:g} → ${c['price_min']:g}", c["price_min"]))
        rows.sort(key=lambda x: (crank.get(x[0]["handle"], BIG), x[0]["handle"]))
        for c, det, val in rows:
            alerts.add(date, "price_change", dom, "shopify", c.get("title"), c.get("url"), c.get("image"), det, val)
        # nhảy rank
        if prank and crank:
            jumps = []
            for h, r in crank.items():
                if h not in cm or r > RANK_JUMP_TOP:
                    continue
                p0 = prank.get(h)
                if p0 is None:
                    jumps.append((r, h, f"mới vào rank ở #{r}", None))
                elif p0 - r >= RANK_JUMP_MIN:
                    jumps.append((r, h, f"rank {p0} → {r}", p0 - r))
            for r, h, det, val in sorted(jumps):
                c = cm[h]
                alerts.add(date, "rank_jump", dom, "shopify", c.get("title"), c.get("url"), c.get("image"), det,
                           val if val is not None else r)
        # theme mới của shop (chỉ tính sp ngách)
        def theme_count(m):
            out = {}
            for p in m.values():
                if p["_niche"] and p["_lbl"][0] != "khac":
                    out.setdefault(p["_lbl"][0], []).append(p)
            return out
        tp, tc = theme_count(pm), theme_count(cm)
        for t in sorted(tc):
            if t not in tp:
                ps = sorted(tc[t], key=lambda p: (crank.get(p["handle"], BIG), p["handle"]))
                alerts.add(date, "new_theme", dom, "shopify", f"Theme mới: {self.rules.theme_labels.get(t, t)}",
                           ps[0].get("url"), ps[0].get("image"), f"{t} · {len(ps)} sp", len(ps))


# ================================================================ Etsy


def etsy_price_usd(price, ccy):
    r = FX_USD.get((ccy or "").upper())
    return round(price * r, 2) if (num(price) is not None and r) else None


class EtsyShop:
    def __init__(self, shop, rules):
        self.shop = shop
        self.dir = DATA / "etsy" / shop
        self.rules = rules
        self.dates = snapshot_dates(self.dir)
        self.snaps = {d: load_json(self.dir / f"{d}.json") for d in self.dates}
        self.snaps = {d: s for d, s in self.snaps.items() if s and s.get("info")}
        self.dates = sorted(self.snaps)

    @staticmethod
    def listing_stats(s):
        out = {}
        for lid, L in (s.get("listings") or {}).items():
            ct = L.get("chi_tiet") or {}
            out[lid] = {"favorites": ct.get("favorites"), "reviews": ct.get("review_listing"),
                        "bestseller": bool(L.get("bestseller") or ct.get("bestseller"))}
        return out

    def build(self, alerts, alert_from):
        if not self.dates:
            return None
        series = []   # Etsy không xoá thô → luôn tính lại
        for d in self.dates:
            i = self.snaps[d]["info"]
            series.append({"date": d, "sales": i.get("tong_sales"), "reviews": i.get("so_review"),
                           "admirers": i.get("admirers"), "listings": i.get("so_listing"),
                           "n_scanned": len(self.snaps[d].get("listings") or {})})
        series.sort(key=lambda e: e["date"])
        ser = {e["date"]: e for e in series}
        sdates = sorted(ser)
        last_date = self.dates[-1]
        last = self.snaps[last_date]
        info = last["info"]

        def back(n, tol, key):
            d = pick_at_or_before(sdates, shift(last_date, -n), tol)
            return delta(ser[last_date].get(key), ser[d].get(key)) if d else None

        deltas = {"sales_1d": back(1, 1, "sales"), "sales_7d": back(7, 3, "sales"),
                  "sales_30d": back(30, 7, "sales"), "reviews_7d": back(7, 3, "reviews")}
        d7 = pick_at_or_before(self.dates, shift(last_date, -7), 3)
        st7 = self.listing_stats(self.snaps[d7]) if d7 else {}
        web = (info.get("web_ngoai") or [""])[0] if info.get("web_ngoai") else ""
        listings = []
        for lid, L in (last.get("listings") or {}).items():
            ct = L.get("chi_tiet") or {}
            theme, layout, font = self.rules.label(L.get("title"))
            fav, rev = ct.get("favorites"), ct.get("review_listing")
            o = st7.get(lid) or {}
            price = L.get("gia") if L.get("gia") is not None else ct.get("gia_tu")
            ccy = L.get("tien_te") or ct.get("tien_te") or ""
            listings.append({
                "id": str(lid), "title": L.get("title") or "", "url": L.get("url") or f"https://www.etsy.com/listing/{lid}",
                "image": L.get("img") or "", "price": price, "currency": ccy, "price_usd": etsy_price_usd(price, ccy),
                "reviews": rev, "favorites": fav, "bestseller": bool(L.get("bestseller") or ct.get("bestseller")),
                "in_carts": ct.get("trong_gio"), "listed_on": ct.get("listed_on"),
                "favorites_7d": delta(fav, o.get("favorites")), "reviews_7d": delta(rev, o.get("reviews")),
                "position": L.get("stt"),
                "theme": theme, "layout": layout, "font": font,
                "is_niche": is_niche(L.get("title")),
            })
        listings.sort(key=lambda x: (x["position"] is None, x["position"] or 0))
        # alerts theo từng cặp snapshot liền nhau
        for a, b in zip(self.dates, self.dates[1:]):
            if b >= alert_from:
                self.diff_alerts(alerts, a, b, ser)
        return {"shop": self.shop, "url": f"https://www.etsy.com/shop/{self.shop}",
                "updated_at": to_utc(last.get("luc")) or f"{last_date}T00:00:00Z", "source": SOURCE_ETSY,
                "last_ok": last_date,
                "info": {"sales": info.get("tong_sales"), "reviews": info.get("so_review"), "rating": info.get("rating"),
                         "admirers": info.get("admirers"), "listings": info.get("so_listing"),
                         "since": info.get("mo_shop_tu") or info.get("tuoi") or "",
                         "star_seller": bool(info.get("star_seller")), "location": info.get("dia_diem") or "",
                         "website": web},
                "series": series, "deltas": deltas, "listings": listings}

    def diff_alerts(self, alerts, pdate, date, ser):
        shop = self.shop
        prev, cur = self.snaps[pdate], self.snaps[date]
        url_shop = f"https://www.etsy.com/shop/{shop}"
        # sales tăng đột biến: tốc độ/ngày ≥ 2× trung bình các khoảng trước (cần ≥ 2 khoảng trước) và ≥ 5/ngày
        dates = [d for d in sorted(ser) if d <= date and num(ser[d].get("sales")) is not None]
        rates = []
        for a, b in zip(dates, dates[1:]):
            n = max(days_between(a, b), 1)
            rates.append((b, (ser[b]["sales"] - ser[a]["sales"]) / n))
        cur_rate = next((r for d, r in rates if d == date), None)
        before = [r for d, r in rates if d < date and d >= shift(date, -30)]
        if cur_rate is not None and len(before) >= 2:
            avg = sum(before) / len(before)
            if cur_rate >= 5 and cur_rate >= 2 * max(avg, 1):
                alerts.add(date, "etsy_sales_spike", shop, "etsy", f"{shop}: sales tăng mạnh", url_shop, "",
                           f"+{cur_rate:.0f} sales/ngày (TB trước {avg:.1f}/ngày)", round(cur_rate, 1))
        pl, cl = prev.get("listings") or {}, cur.get("listings") or {}
        pmax = max((int(k) for k in pl if str(k).isdigit()), default=0)
        for lid, L in cl.items():
            ct = L.get("chi_tiet") or {}
            if lid not in pl and str(lid).isdigit() and int(lid) > pmax:   # id Etsy tăng dần → listing mới thật
                alerts.add(date, "new_listing", shop, "etsy", L.get("title"), L.get("url"), L.get("img"),
                           f"listing mới · {L.get('gia')} {L.get('tien_te') or ''}".strip(), L.get("gia"))
            o = pl.get(lid)
            if o and (o.get("bestseller") or (o.get("chi_tiet") or {}).get("bestseller")) \
                    and not (L.get("bestseller") or ct.get("bestseller")):
                alerts.add(date, "lost_bestseller", shop, "etsy", L.get("title"), L.get("url"), L.get("img"),
                           "mất huy hiệu Bestseller", None)


# ================================================================ Ads


RE_HANDLE = re.compile(r"/products/([A-Za-z0-9\-_%.]+)")
AD_URL = "https://www.facebook.com/ads/library/?id="   # url alert ads = trang ad trên Ad Library (mỗi ad 1 url)


class AdsKey:
    def __init__(self, key):
        self.key = key
        self.dir = DATA / "ads" / key
        self.dates = snapshot_dates(self.dir)
        self.snaps = {d: load_json(self.dir / f"{d}.json") for d in self.dates}
        self.snaps = {d: s for d, s in self.snaps.items() if s and not s.get("blocked")}
        self.dates = sorted(self.snaps)

    @staticmethod
    def start_of(ad):
        return ad.get("start_date") or ad.get("first_seen")

    def build(self, alerts, alert_from):
        if not self.dates:
            return None
        series = []   # ads không xoá thô → luôn tính lại
        allads = {}
        prev_ids, prev_date = None, None
        for d in self.dates:
            ads = {str(a["library_id"]): a for a in self.snaps[d].get("ads") or [] if a.get("library_id")}
            ids = set(ads)
            if prev_ids is not None:
                n_new = len(ids - prev_ids)
            else:
                n_new = sum(1 for a in ads.values() if (self.start_of(a) or "") >= shift(d, -1))
            series.append({"date": d, "n_active": len(ids), "n_new": n_new})
            for lid, a in ads.items():
                r = allads.setdefault(lid, {"library_id": lid, "first_seen": a.get("first_seen") or d, "last_seen": d})
                r["first_seen"] = min(r["first_seen"], a.get("first_seen") or d)
                r["last_seen"] = max(r["last_seen"], d)
                r["_last"] = a
            if prev_ids is not None and d >= alert_from:
                for lid in sorted(ids - prev_ids):
                    a = ads[lid]
                    alerts.add(d, "new_ad", self.key, "ads", (a.get("text") or "")[:120] or f"Ad {lid}",
                               AD_URL + lid, a.get("image"),
                               f"ad mới · bắt đầu {self.start_of(a) or '?'} · {a.get('landing') or ''}".rstrip(" ·"), None)
                for lid in sorted(ids & prev_ids):
                    a = ads[lid]
                    st = self.start_of(a)
                    if not st:
                        continue
                    n_now, n_prev = days_between(st, d) + 1, days_between(st, prev_date) + 1
                    if n_now > AD_LONG_DAYS >= n_prev:
                        alerts.add(d, "ad_long", self.key, "ads", (a.get("text") or "")[:120] or f"Ad {lid}",
                                   AD_URL + lid, a.get("image"),
                                   f"chạy {n_now} ngày (từ {st}) → có lời · {a.get('landing') or ''}".rstrip(" ·"), n_now)
            prev_ids, prev_date = ids, d
        last_date = self.dates[-1]
        last_ids = {str(a["library_id"]) for a in self.snaps[last_date].get("ads") or [] if a.get("library_id")}
        out = []
        for lid, r in allads.items():
            a = r.pop("_last")
            st = self.start_of(a) or r["first_seen"]
            first_seen = min(r["first_seen"], st) if st else r["first_seen"]
            landing = a.get("landing") or ""
            m = RE_HANDLE.search(landing)
            out.append({"library_id": lid, "first_seen": first_seen, "last_seen": r["last_seen"],
                        "start_date": a.get("start_date"),
                        "days_running": days_between(st, r["last_seen"]) + 1,
                        "active": lid in last_ids, "text": a.get("text") or "", "landing": landing,
                        "product_handle": a.get("product_handle") or (m.group(1).lower() if m else ""),
                        "image": a.get("image") or "", "platforms": a.get("platforms") or [],
                        "page_name": a.get("page_name") or "", "n_versions": a.get("n_versions")})
        out.sort(key=lambda x: (not x["active"], -x["days_running"], x["library_id"]))
        series.sort(key=lambda e: e["date"])
        last = self.snaps[last_date]
        return {"key": self.key, "source": SOURCE_ADS, "updated_at": to_utc(last.get("fetched_at")) or f"{last_date}T00:00:00Z",
                "last_ok": last_date, "query_url": last.get("url") or "", "ads": out, "series": series}


# ================================================================ main


def max_data_date():
    ds = []
    for plat in ("shopify", "etsy", "ads"):
        for sub in (DATA / plat).glob("*"):
            if sub.is_dir():
                ds += snapshot_dates(sub)
    return max(ds) if ds else None


def compact_raw():
    """Ghi lại snapshot THÔ (shopify/etsy/ads) dạng JSON gọn nếu đang có thụt dòng (vd snapshot Etsy chép từ 4-SPY).
    Nội dung giữ nguyên, chỉ đổi format → repo nhỏ hơn ~30-40%."""
    n = 0
    for plat in ("shopify", "etsy", "ads"):
        for sub in (DATA / plat).glob("*"):
            for d in snapshot_dates(sub):
                p = sub / f"{d}.json"
                raw = p.read_text(encoding="utf-8")
                if "\n" not in raw.strip():
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                os.replace(tmp, p)
                n += 1
    if n:
        log(f"Ghi gọn {n} snapshot thô")


def prune_shopify(latest, dry=False):
    cut = shift(latest, -KEEP_RAW_SHOPIFY_DAYS)
    n = 0
    for sub in (DATA / "shopify").glob("*"):
        for d in snapshot_dates(sub):
            if d < cut:
                n += 1
                if not dry:
                    (sub / f"{d}.json").unlink()
    if n:
        log(f"Xoá {n} snapshot thô Shopify cũ hơn {cut}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Tổng hợp snapshot → summary/index/alerts/themes")
    ap.add_argument("--no-prune", action="store_true", help="không xoá snapshot Shopify cũ")
    a = ap.parse_args()

    rules = Rules(RULES_PATH)
    latest = max_data_date()
    if not latest:
        sys.exit("Chưa có snapshot nào trong data/")
    alert_from = shift(latest, -KEEP_ALERT_DAYS + 1)
    purge_cut = shift(latest, -KEEP_RAW_SHOPIFY_DAYS)
    alerts = Alerts()
    index = {"updated_at": None, "shopify": [], "etsy": [], "ads": [], "dates": []}
    all_dates = set()
    counts = {}
    upd = []

    def count(theme, plat):
        c = counts.setdefault(theme, {"shopify": 0, "etsy": 0})
        c[plat] += 1

    for sub in sorted((DATA / "shopify").glob("*")):
        if not sub.is_dir():
            continue
        sh = ShopifyShop(sub.name, rules)
        s = sh.build(alerts, alert_from, purge_cut)
        if not s:
            continue
        save_json(sub / "summary.json", s)
        last = s["series"][-1]
        index["shopify"].append({"domain": sh.domain, "name": s["name"], "first_seen": s["series"][0]["date"],
                                 "last_ok": s["last_ok"], "n_products": last["n_products"], "n_niche": last["n_niche"],
                                 "n_new_7d": last["n_new_7d"]})
        all_dates.update(e["date"] for e in s["series"])
        upd.append(s["updated_at"])
        for p in s["products"]:
            count(p["theme"], "shopify")
        log(f"shopify {sh.domain}: {len(s['products'])} sp, series {len(s['series'])} ngày")

    for sub in sorted((DATA / "etsy").glob("*")):
        if not sub.is_dir() or sub.name.startswith("_"):
            continue
        es = EtsyShop(sub.name, rules)
        s = es.build(alerts, alert_from)
        if not s:
            continue
        save_json(sub / "summary.json", s)
        index["etsy"].append({"shop": es.shop, "last_ok": s["last_ok"], "sales": s["info"]["sales"],
                              "reviews": s["info"]["reviews"], "sales_7d": s["deltas"]["sales_7d"]})
        all_dates.update(e["date"] for e in s["series"])
        upd.append(s["updated_at"])
        for L in s["listings"]:
            count(L["theme"], "etsy")
        log(f"etsy {es.shop}: {len(s['listings'])} listing, series {len(s['series'])} ngày")

    for sub in sorted((DATA / "ads").glob("*")):
        if not sub.is_dir():
            continue
        ak = AdsKey(sub.name)
        s = ak.build(alerts, alert_from)
        if not s:
            continue
        save_json(sub / "summary.json", s)
        act = [x for x in s["ads"] if x["active"]]
        index["ads"].append({"key": ak.key, "last_ok": s["last_ok"], "n_active": len(act),
                             "max_days_running": max((x["days_running"] for x in act), default=None)})
        all_dates.update(e["date"] for e in s["series"])
        upd.append(s["updated_at"])
        log(f"ads {ak.key}: {len(act)} đang chạy / {len(s['ads'])} từng thấy")

    # ---- alerts: tính lại từ snapshot; alert cũ hơn mốc xoá thô Shopify (30 ngày) không tính lại được → giữ từ file cũ
    old_alerts = [x for x in (load_json(DATA / "alerts.json", []) or [])
                  if alert_from <= x.get("date", "") < purge_cut]
    merged = {}
    for x in old_alerts + cap_group(alerts.items):
        merged[(x["date"], x["type"], x["shop"], x["url"])] = x
    order = {k: i for i, k in enumerate(merged)}
    rows = sorted(merged.values(), key=lambda x: (x["date"], -order[(x["date"], x["type"], x["shop"], x["url"])]),
                  reverse=True)
    save_json(DATA / "alerts.json", rows)

    # ---- themes.json
    tids = [t for t, _ in rules.themes] + ["khac"]
    save_json(DATA / "themes.json", {
        "themes": tids,
        "layouts": [l for l, _, _ in rules.layouts] + ["khac"],
        "fonts": ["script", "block", "mixed", "khac"],
        "labels": {**rules.theme_labels, **rules.layout_labels, "khac": "Khác"},
        "counts": {t: counts.get(t, {"shopify": 0, "etsy": 0}) for t in tids},
    })

    # ---- index.json
    index["updated_at"] = max(u for u in upd if u) if upd else None
    index["dates"] = sorted(all_dates)
    save_json(DATA / "index.json", index)

    compact_raw()
    if not a.no_prune:
        prune_shopify(latest)
    by_type = {}
    for x in rows:
        by_type[x["type"]] = by_type.get(x["type"], 0) + 1
    log(f"alerts: {len(rows)} ({', '.join(f'{k} {v}' for k, v in sorted(by_type.items())) or 'không có'})")
    log(f"index: {len(index['shopify'])} Shopify · {len(index['etsy'])} Etsy · {len(index['ads'])} ads · "
        f"ngày {index['dates'][:1]}…{index['dates'][-1:]}")


if __name__ == "__main__":
    main()
