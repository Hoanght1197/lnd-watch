# -*- coding: utf-8 -*-
"""build.py — gộp số liệu thô thành file web đọc. Thuần tính toán, chạy cả local lẫn Actions.

Vào:  data/shops.json · data/raw/<ngày>/{ads,etsy,shopify}.json · data/traffic.json
Ra:   data/daily/<ngày>.json      1 dòng / shop / ngày (gọn)
      data/leaderboard.json       bảng xếp hạng (web đọc chính)
      data/alerts.json            cảnh báo 90 ngày gần nhất
Không dùng giờ hiện tại → chạy lại bao nhiêu lần cũng ra cùng kết quả (cùng dữ liệu vào).
Kiểm cấu trúc đầu ra; sai thì mã thoát 1 (Actions / run_local sẽ không commit).
    python collect/build.py
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DAILY, DATA, TRAFFIC_FILE, load_json, load_raw, load_shops, log, raw_dates,  # noqa: E402
                    save_json, utf8_stdout)

SERIES_DAYS = 30
ALERT_DAYS = 90
SW_PER_DAY = 3


def D(s):
    return dt.date.fromisoformat(s)


def ads_est(r):
    """Số ads 'thật của shop' ước từ n_results thô + tỉ lệ thẻ có landing về đúng domain.
    n_results ≤ số thẻ đã tải → đếm thẳng n_match. Tỉ lệ khớp < 50 % → kết quả nhiễu, chỉ lấy n_match (cận dưới)."""
    n, cards, match, ratio = r.get("n_results"), r.get("n_cards") or 0, r.get("n_match") or 0, r.get("match_ratio")
    if n is None:
        return None, False
    if n == 0:
        return 0, False
    if n <= cards:
        return match, False
    if ratio is None:
        return None, False
    if ratio < 0.5:
        return match, True
    return round(n * ratio), False


# ---------------------------------------------------------------- daily

def build_daily(dates):
    """{date: {id: record}} + ghi data/daily/<date>.json."""
    out = {}
    for d in dates:
        ads, etsy, shp = load_raw(d, "ads")["shops"], load_raw(d, "etsy")["shops"], load_raw(d, "shopify")["shops"]
        recs = {}
        for sid, r in ads.items():
            if r.get("status") != "ok":
                continue
            est, noisy = ads_est(r)
            recs.setdefault(sid, {"id": sid, "platform": "shopify"})["ads"] = {
                "n_results": r["n_results"], "approx": r.get("approx"), "n_cards": r.get("n_cards"),
                "n_match": r.get("n_match"), "match_ratio": r.get("match_ratio"), "est": est, "noisy": noisy,
                "new_7d": r.get("new_7d"), "oldest_start": r.get("oldest_start"), "at": r.get("at"), "src": r.get("src")}
        for sid, r in shp.items():
            if r.get("status") != "ok":
                continue
            recs.setdefault(sid, {"id": sid, "platform": "shopify"})["shopify"] = {
                k: r.get(k) for k in ("name", "currency", "n_products", "new_7d", "new_30d", "capped",
                                      "price_min", "price_max", "newest", "at", "src")}
        for sid, r in etsy.items():
            if r.get("status") != "ok":
                continue
            recs.setdefault(sid, {"id": sid, "platform": "etsy"})["etsy"] = {
                k: r.get(k) for k in ("sales", "reviews", "rating", "admirers", "listings", "star_seller", "at", "src")}
        if recs:
            rows = [recs[k] for k in sorted(recs)]
            save_json(DAILY / f"{d}.json", rows)
            out[d] = recs
    return out


# ---------------------------------------------------------------- helpers

def series_of(daily, sid, block, field):
    return [(d, (daily[d].get(sid) or {}).get(block, {}).get(field)) for d in sorted(daily)
            if (daily[d].get(sid) or {}).get(block) is not None]


def etsy_deltas(ser, latest):
    """ser: [(date, sales)] → sales_1d, sales_7d (+ số ngày thật của khoảng)."""
    ser = [(d, v) for d, v in ser if v is not None]
    if len(ser) < 2:
        return None, None, None
    d_last, v_last = ser[-1]
    d_prev, v_prev = ser[-2]
    gap = (D(d_last) - D(d_prev)).days
    s1 = v_last - v_prev if gap == 1 else None
    base = [x for x in ser if (D(d_last) - D(x[0])).days >= 7]
    b = base[-1] if base else ser[0]
    days = (D(d_last) - D(b[0])).days
    return s1, v_last - b[1], days


def traffic_queue(shops, traffic, ads_latest):
    def key(s):
        ent = traffic.get(s["domain"]) or {}
        return (ent.get("last_check") or "", -(ads_latest.get(s["id"]) or 0), s["domain"])
    return sorted(shops, key=key)


# ---------------------------------------------------------------- alerts

def build_alerts(daily, shops_by_id, traffic, latest):
    al = []
    if not latest:
        return al
    name = lambda sid: (shops_by_id.get(sid) or {}).get("_name") or sid  # noqa: E731
    ids = sorted({sid for recs in daily.values() for sid in recs})
    for sid in ids:
        sh = shops_by_id.get(sid) or {}
        ser = series_of(daily, sid, "ads", "est")
        for (d0, a), (d1, b) in zip(ser, ser[1:]):
            if a is None or b is None:
                continue
            if a == 0 and b > 0:
                al.append({"date": d1, "type": "ads_new_shop", "shop": sid, "platform": "shopify", "name": name(sid),
                           "title": f"{name(sid)} bắt đầu chạy ads", "detail": f"0 → {b} ads", "value": b,
                           "url": sh.get("_ads_url")})
            elif a > 0 and (b - a >= 20 or (b >= a * 1.5 and b - a >= 5)):
                al.append({"date": d1, "type": "ads_jump", "shop": sid, "platform": "shopify", "name": name(sid),
                           "title": f"{name(sid)} tăng ads", "detail": f"{a} → {b} ads (+{b - a})", "value": b - a,
                           "url": sh.get("_ads_url")})
        es = [(d, v) for d, v in series_of(daily, sid, "etsy", "sales") if v is not None]
        per_day = []
        for (d0, a), (d1, b) in zip(es, es[1:]):
            gap = max(1, (D(d1) - D(d0)).days)
            per_day.append((d1, (b - a) / gap))
        for i, (d1, v) in enumerate(per_day):
            prev = [x for dd, x in per_day[:i] if 0 < (D(d1) - D(dd)).days <= 14]
            if len(prev) >= 3:
                avg = sum(prev) / len(prev)
                if v >= 3 and v > 2 * max(avg, 0.5):
                    al.append({"date": d1, "type": "etsy_sales_spike", "shop": sid, "platform": "etsy", "name": name(sid),
                               "title": f"{name(sid)} bán tăng vọt", "detail": f"{v:.0f} sales/ngày (TB 14 ngày {avg:.1f})",
                               "value": round(v), "url": sh.get("url")})
    for dom, ent in traffic.items():
        for month, h in (ent.get("history") or {}).items():
            c = h.get("change_pct")
            if c is not None and c >= 30 and not h.get("derived"):
                sid = dom
                al.append({"date": h.get("checked"), "type": "traffic_jump", "shop": sid, "platform": "shopify",
                           "name": name(sid), "title": f"{name(sid)} traffic tăng mạnh",
                           "detail": f"T{int(month[5:])}/{month[:4]}: {h.get('visits'):,} visits ({c:+.1f}%)".replace(",", "."),
                           "value": c,
                           "url": f"https://www.similarweb.com/website/{dom}/"})
    added = [s.get("added_on") for s in shops_by_id.values() if s.get("added_on")]
    first_batch = min(added) if added else None
    for sid, s in shops_by_id.items():
        if s.get("added_on") and s["added_on"] != first_batch:
            al.append({"date": s["added_on"], "type": "new_shop", "shop": sid, "platform": s["platform"], "name": name(sid),
                       "title": f"Thêm shop {name(sid)}", "detail": s.get("note") or "", "value": None,
                       "url": s.get("_link")})
    cut = (D(latest) - dt.timedelta(days=ALERT_DAYS)).isoformat()
    al = [a for a in al if a.get("date") and a["date"] >= cut]
    al.sort(key=lambda a: (a["date"], a["type"], a["shop"]), reverse=True)
    return al


# ---------------------------------------------------------------- leaderboard

def main():
    utf8_stdout()
    shops = load_shops()
    if not shops:
        log("! data/shops.json trống → chạy collect/sync_shops.py ở máy local")
        sys.exit(1)
    dates = raw_dates()
    daily = build_daily(dates)
    ddates = sorted(daily)
    latest = ddates[-1] if ddates else None
    win = ddates[-SERIES_DAYS:]
    tdoc = load_json(TRAFFIC_FILE, {}) or {}
    traffic = tdoc.get("domains") or {}
    raw_latest = {src: {} for src in ("ads", "etsy", "shopify")}
    for d in dates:   # bản ghi OK mới nhất của từng nguồn (kèm mẫu ads)
        for src in raw_latest:
            for sid, r in load_raw(d, src)["shops"].items():
                if r.get("status") == "ok":
                    raw_latest[src][sid] = dict(r, _date=d)

    by_id = {s["id"]: s for s in shops}
    for s in shops:
        sp = raw_latest["shopify"].get(s["id"]) or {}
        s["_name"] = sp.get("name") or s.get("name") or s["id"]
        s["_link"] = f"https://{s['domain']}" if s["platform"] == "shopify" else (s.get("url") or f"https://www.etsy.com/shop/{s['etsy']}")
        ar = raw_latest["ads"].get(s["id"])
        s["_ads_url"] = ar.get("url") if ar else None

    active = [s for s in shops if s.get("active", True)]
    ads_latest = {sid: ads_est(r)[0] for sid, r in raw_latest["ads"].items()}
    q = traffic_queue([s for s in active if s["platform"] == "shopify"], traffic, ads_latest)
    # lịch tra dự kiến: 3 shop/ngày theo hàng chờ, bắt đầu từ ngày sau ngày dữ liệu mới nhất
    base = D(latest) if latest else None
    plan = {s["id"]: (base + dt.timedelta(days=1 + i // SW_PER_DAY)).isoformat() if base else None for i, s in enumerate(q)}

    rows = []
    for s in active:
        sid = s["id"]
        row = {"id": sid, "platform": s["platform"], "name": s["_name"], "link": s["_link"],
               "first_seen": s.get("first_seen"), "sources": s.get("sources") or [], "note": s.get("note") or "",
               "updated": {}}
        if s["platform"] == "shopify":
            row["domain"] = s["domain"]
            a = raw_latest["ads"].get(sid)
            if a:
                est, noisy = ads_est(a)
                row.update({"ads_active": a.get("n_results"), "ads_approx": a.get("approx"), "ads_match": a.get("n_match"),
                            "ads_cards": a.get("n_cards"), "ads_match_ratio": a.get("match_ratio"), "ads_est": est,
                            "ads_noisy": noisy, "ads_new_7d": a.get("new_7d"), "oldest_ad_start": a.get("oldest_start"),
                            "oldest_ad_days": a.get("oldest_days")})
                row["ads_detail"] = {"pages": a.get("pages") or [], "samples": a.get("samples") or [], "url": a.get("url"),
                                     "src": a.get("src")}
                row["updated"]["ads"] = a.get("at")
            p = raw_latest["shopify"].get(sid)
            if p:
                row.update({"n_products": p.get("n_products"), "new_products_7d": p.get("new_7d"),
                            "new_products_30d": p.get("new_30d"), "new_products_capped": p.get("capped"),
                            "price_min": p.get("price_min"), "price_max": p.get("price_max"), "currency": p.get("currency"),
                            "newest_product": p.get("newest")})
                row["updated"]["shopify"] = p.get("at")
            t = traffic.get(s["domain"]) or {}
            lt = t.get("latest")
            row["traffic_status"] = "ok" if lt else ("no_data" if t.get("no_data") else None)
            row["traffic_next"] = plan.get(sid)
            if lt:
                tc = lt.get("top_countries") or []
                row.update({"traffic_visits": lt.get("visits"), "traffic_month": lt.get("month"),
                            "traffic_change_pct": lt.get("change_pct"), "bounce": lt.get("bounce_pct"),
                            "pages_per_visit": lt.get("pages_per_visit"), "duration": lt.get("duration"),
                            "top_country": tc[0]["country"] if tc else None, "top_country_pct": tc[0]["pct"] if tc else None})
                row["traffic_detail"] = {"countries": tc, "source": lt.get("source"), "checked": lt.get("checked"),
                                         "history": [{"month": m, "visits": h.get("visits"), "derived": bool(h.get("derived"))}
                                                     for m, h in sorted((t.get("history") or {}).items())]}
                row["updated"]["traffic"] = lt.get("at")
            elif t.get("no_data"):
                row["updated"]["traffic"] = t.get("no_data")
            row["series_ads"] = [((daily[d].get(sid) or {}).get("ads") or {}).get("est") for d in win]
            row["series_ads_raw"] = [((daily[d].get(sid) or {}).get("ads") or {}).get("n_results") for d in win]
        else:
            row["etsy"] = s["etsy"]
            e = raw_latest["etsy"].get(sid)
            if e:
                s1, s7, days = etsy_deltas(series_of(daily, sid, "etsy", "sales"), latest)
                row.update({"etsy_sales": e.get("sales"), "etsy_sales_1d": s1, "etsy_sales_7d": s7, "etsy_sales_7d_days": days,
                            "etsy_reviews": e.get("reviews"), "etsy_rating": e.get("rating"), "etsy_admirers": e.get("admirers"),
                            "etsy_listings": e.get("listings"), "etsy_star_seller": e.get("star_seller"),
                            "etsy_location": e.get("location"), "etsy_since": e.get("since")})
                row["updated"]["etsy"] = e.get("at")
            row["series_etsy_sales"] = [((daily[d].get(sid) or {}).get("etsy") or {}).get("sales") for d in win]
        rows.append(row)
    rows.sort(key=lambda r: (-(r.get("ads_est") or -1), -(r.get("etsy_sales_7d") or -1), r["id"].lower()))

    alerts = build_alerts(daily, by_id, traffic, latest)
    stamps = [load_raw(d, src).get("updated_at") or "" for d in dates for src in ("ads", "etsy", "shopify")]
    stamps.append(tdoc.get("updated_at") or "")
    lb = {"updated_at": max(stamps) if any(stamps) else None, "latest_date": latest, "dates": win,
          "counts": {"shopify": sum(r["platform"] == "shopify" for r in rows), "etsy": sum(r["platform"] == "etsy" for r in rows)},
          "sources": {
              "ads": "Meta Ad Library (web, country=ALL): ~N results ở đầu trang (thô, gồm ad nhắc tới từ khoá) + đếm thẻ đã tải có landing về đúng domain",
              "traffic": "SimilarWeb web miễn phí (≤ 3 shop/ngày), số ước tính của SimilarWeb",
              "etsy": "Etsy trang shop: tổng sales / review / admirers (số thật Etsy hiển thị)",
              "shopify": "Shopify /meta.json + /products.json?limit=30 (30 sp mới nhất)"},
          "traffic_quota": {"per_day": SW_PER_DAY, "queue": [s["domain"] for s in q[:9]]},
          "rows": rows}

    # ---- kiểm
    errs = []
    for r in rows:
        for k in ("id", "platform", "name", "link"):
            if not r.get(k):
                errs.append(f"{r.get('id')}: thiếu {k}")
        if r["platform"] not in ("shopify", "etsy"):
            errs.append(f"{r['id']}: platform lạ")
        for k in ("series_ads", "series_etsy_sales"):
            if k in r and len(r[k]) != len(win):
                errs.append(f"{r['id']}: {k} lệch độ dài")
    for a in alerts:
        if not (a.get("date") and a.get("type") and a.get("shop")):
            errs.append(f"alert thiếu trường: {a}")
    if errs:
        log("! build lỗi:\n  " + "\n  ".join(errs[:20]))
        sys.exit(1)
    save_json(DATA / "leaderboard.json", lb)
    save_json(DATA / "alerts.json", alerts, compact=False)
    n_ads = sum(1 for r in rows if r.get("ads_active") is not None)
    n_tr = sum(1 for r in rows if r.get("traffic_status") == "ok")
    n_et = sum(1 for r in rows if r.get("etsy_sales") is not None)
    n_sp = sum(1 for r in rows if r.get("n_products") is not None)
    log(f"build: {len(ddates)} ngày · leaderboard {len(rows)} shop (ads {n_ads} · traffic {n_tr} · etsy {n_et} · "
        f"shopify {n_sp}) · alerts {len(alerts)} · mới nhất {latest}")


if __name__ == "__main__":
    main()
