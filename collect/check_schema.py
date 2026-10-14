# -*- coding: utf-8 -*-
"""check_schema.py — kiểm các file JSON trong data/ có đủ field bắt buộc theo SPEC.md (web đọc đúng các file này).

    python collect/check_schema.py          # in lỗi, mã thoát 1 nếu có lỗi
Chạy sau build_summary.py (cả trên Actions để chặn commit dữ liệu hỏng).
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

S, I, F, B, L, D, N = str, int, float, bool, list, dict, type(None)
NUM = (I, F)
ALERT_TYPES = {"new_product", "price_change", "rank_jump", "new_ad", "ad_long", "etsy_sales_spike",
               "new_listing", "lost_bestseller", "new_theme"}
PLATFORMS = {"shopify", "etsy", "ads"}
LAYOUTS = {"chu-cai-canh", "canh-ten", "script-hoa", "ten-2-dong", "khac"}
FONTS = {"script", "block", "mixed", "khac"}

# field: kiểu cho phép ("date"/"ts" = chuỗi ISO ngày / thời gian UTC)
SHOPIFY_SUMMARY = {"domain": S, "updated_at": "ts", "source": S, "series": L, "products": L}
SHOPIFY_SERIES = {"date": "date", "n_products": I, "n_niche": I, "n_new_7d": I, "price_by_size": D, "rank_source": S}
SHOPIFY_PRODUCT = {"handle": S, "title": S, "image": S, "url": S, "published_at": ("date", N),
                   "price_min": NUM + (N,), "price_max": NUM + (N,), "price_by_size": D,
                   "rank": (I, N), "rank_7d": (I, N), "rank_30d": (I, N), "tags": L,
                   "theme": S, "layout": S, "font": S, "is_niche": B}
ETSY_SUMMARY = {"shop": S, "url": S, "updated_at": "ts", "source": S, "info": D, "series": L, "deltas": D, "listings": L}
ETSY_INFO = {"sales": (I, N), "reviews": (I, N), "rating": NUM + (N,), "admirers": (I, N), "listings": (I, N),
             "since": (S, N), "star_seller": B, "location": S, "website": S}
ETSY_SERIES = {"date": "date", "sales": (I, N), "reviews": (I, N), "admirers": (I, N), "listings": (I, N)}
ETSY_DELTAS = {"sales_1d": (I, N), "sales_7d": (I, N), "sales_30d": (I, N), "reviews_7d": (I, N)}
ETSY_LISTING = {"id": S, "title": S, "url": S, "image": S, "price": NUM + (N,), "currency": S,
                "reviews": (I, N), "favorites": (I, N), "bestseller": B, "in_carts": (S, I, N),
                "listed_on": ("date", N), "favorites_7d": (I, N), "reviews_7d": (I, N),
                "theme": S, "layout": S, "font": S}
ADS_SUMMARY = {"key": S, "source": S, "updated_at": "ts", "ads": L, "series": L}
ADS_AD = {"library_id": S, "first_seen": "date", "last_seen": "date", "days_running": I, "active": B,
          "text": S, "landing": S, "product_handle": S, "image": S, "platforms": L}
ADS_SERIES = {"date": "date", "n_active": I, "n_new": I}
ALERT = {"date": "date", "type": S, "shop": S, "platform": S, "title": S, "url": S, "image": S, "detail": S,
         "value": NUM + (N,)}
INDEX = {"updated_at": ("ts", N), "shopify": L, "etsy": L, "ads": L, "dates": L}
INDEX_SHOPIFY = {"domain": S, "name": S, "first_seen": "date", "last_ok": "date", "n_products": I}
INDEX_ETSY = {"shop": S, "last_ok": "date", "sales": (I, N)}
INDEX_ADS = {"key": S, "last_ok": "date", "n_active": I}
THEMES = {"themes": L, "layouts": L, "fonts": L, "counts": D}

errors = []


def err(where, msg):
    errors.append(f"{where}: {msg}")


def ok_type(v, t):
    ts = t if isinstance(t, tuple) else (t,)
    for x in ts:
        if x == "date" and isinstance(v, str) and RE_DATE.match(v):
            return True
        if x == "ts" and isinstance(v, str) and RE_TS.match(v):
            return True
        if isinstance(x, type):
            if x is I and isinstance(v, bool):
                continue
            if x is F and isinstance(v, int) and not isinstance(v, bool):
                return True
            if isinstance(v, x):
                return True
    return False


def check(obj, spec, where, max_err=5):
    if not isinstance(obj, dict):
        err(where, f"không phải object ({type(obj).__name__})")
        return
    n = 0
    for k, t in spec.items():
        if k not in obj:
            err(where, f"thiếu field '{k}'")
            n += 1
        elif not ok_type(obj[k], t):
            err(where, f"field '{k}' sai kiểu: {obj[k]!r:.80}")
            n += 1
        if n >= max_err:
            err(where, "… (dừng, quá nhiều lỗi)")
            return


def check_list(items, spec, where, limit=None):
    for i, x in enumerate(items[:limit] if limit else items):
        before = len(errors)
        check(x, spec, f"{where}[{i}]")
        if len(errors) - before and len(errors) > 200:
            return


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        err(str(path.relative_to(ROOT)), "không có file")
    except json.JSONDecodeError as e:
        err(str(path.relative_to(ROOT)), f"JSON hỏng: {e}")
    return None


def labels_ok(x, themes, where):
    if x.get("theme") not in themes:
        err(where, f"theme lạ '{x.get('theme')}'")
    if x.get("layout") not in LAYOUTS:
        err(where, f"layout lạ '{x.get('layout')}'")
    if x.get("font") not in FONTS:
        err(where, f"font lạ '{x.get('font')}'")


def sorted_dates(series, where):
    ds = [e.get("date") for e in series]
    if ds != sorted(ds) or len(set(ds)) != len(ds):
        err(where, "series không tăng dần theo ngày hoặc trùng ngày")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    th = load(DATA / "themes.json")
    themes = set()
    if th is not None:
        check(th, THEMES, "themes.json")
        themes = set(th.get("themes") or [])
        for t in themes:
            c = (th.get("counts") or {}).get(t)
            if not (isinstance(c, dict) and isinstance(c.get("shopify"), int) and isinstance(c.get("etsy"), int)):
                err("themes.json", f"counts['{t}'] thiếu shopify/etsy")
        if "khac" not in themes:
            err("themes.json", "thiếu theme 'khac'")

    idx = load(DATA / "index.json")
    if idx is not None:
        check(idx, INDEX, "index.json")
        check_list(idx.get("shopify") or [], INDEX_SHOPIFY, "index.shopify")
        check_list(idx.get("etsy") or [], INDEX_ETSY, "index.etsy")
        check_list(idx.get("ads") or [], INDEX_ADS, "index.ads")
        if any(not (isinstance(d, str) and RE_DATE.match(d)) for d in idx.get("dates") or []):
            err("index.json", "dates có phần tử không phải YYYY-MM-DD")

        for e in idx.get("shopify") or []:
            w = f"shopify/{e.get('domain')}/summary.json"
            s = load(DATA / "shopify" / e.get("domain", "?") / "summary.json")
            if s is None:
                continue
            check(s, SHOPIFY_SUMMARY, w)
            check_list(s.get("series") or [], SHOPIFY_SERIES, w + " series")
            sorted_dates(s.get("series") or [], w)
            check_list(s.get("products") or [], SHOPIFY_PRODUCT, w + " products")
            for i, p in enumerate(s.get("products") or []):
                labels_ok(p, themes, f"{w} products[{i}]")
                if not all(re.fullmatch(r"\d+(\.\d+)?", k) and isinstance(v, (int, float))
                           for k, v in (p.get("price_by_size") or {}).items()):
                    err(f"{w} products[{i}]", "price_by_size phải {\"<inch>\": số}")
        for e in idx.get("etsy") or []:
            w = f"etsy/{e.get('shop')}/summary.json"
            s = load(DATA / "etsy" / e.get("shop", "?") / "summary.json")
            if s is None:
                continue
            check(s, ETSY_SUMMARY, w)
            check(s.get("info") or {}, ETSY_INFO, w + " info")
            check(s.get("deltas") or {}, ETSY_DELTAS, w + " deltas")
            check_list(s.get("series") or [], ETSY_SERIES, w + " series")
            sorted_dates(s.get("series") or [], w)
            check_list(s.get("listings") or [], ETSY_LISTING, w + " listings")
            for i, x in enumerate(s.get("listings") or []):
                labels_ok(x, themes, f"{w} listings[{i}]")
        for e in idx.get("ads") or []:
            w = f"ads/{e.get('key')}/summary.json"
            s = load(DATA / "ads" / e.get("key", "?") / "summary.json")
            if s is None:
                continue
            check(s, ADS_SUMMARY, w)
            check_list(s.get("ads") or [], ADS_AD, w + " ads")
            check_list(s.get("series") or [], ADS_SERIES, w + " series")
            sorted_dates(s.get("series") or [], w)
            if sum(1 for a in s.get("ads") or [] if a.get("active")) != e.get("n_active"):
                err(w, "số ad active khác index.n_active")

    al = load(DATA / "alerts.json")
    if al is not None:
        if not isinstance(al, list):
            err("alerts.json", "phải là mảng")
        else:
            check_list(al, ALERT, "alerts")
            keys = set()
            for i, a in enumerate(al):
                if a.get("type") not in ALERT_TYPES:
                    err(f"alerts[{i}]", f"type lạ '{a.get('type')}'")
                if a.get("platform") not in PLATFORMS:
                    err(f"alerts[{i}]", f"platform lạ '{a.get('platform')}'")
                k = (a.get("date"), a.get("type"), a.get("shop"), a.get("url"))
                if k in keys:
                    err(f"alerts[{i}]", f"trùng (date,type,shop,url) {k}")
                keys.add(k)
            ds = [a.get("date") or "" for a in al]
            if ds != sorted(ds, reverse=True):
                err("alerts.json", "chưa sắp mới nhất trước")
            if ds and (dt.date.fromisoformat(ds[0]) - dt.date.fromisoformat(ds[-1])).days >= 90:
                err("alerts.json", "giữ quá 90 ngày")

    if errors:
        print(f"LỖI SCHEMA ({len(errors)}):")
        for e in errors[:200]:
            print("  -", e)
        sys.exit(1)
    n_sp = len(idx.get("shopify") or []) if idx else 0
    print(f"Schema OK: index ({n_sp} Shopify, {len(idx.get('etsy') or [])} Etsy, {len(idx.get('ads') or [])} ads), "
          f"{len(al or [])} alert, {len(themes)} theme")


if __name__ == "__main__":
    main()
