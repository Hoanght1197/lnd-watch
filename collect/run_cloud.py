# -*- coding: utf-8 -*-
"""run_cloud.py — phần thu chạy trên GitHub Actions (HTTP công khai, không cần trình duyệt): Shopify NHẸ.

Mỗi shop Shopify đang theo dõi trong data/shops.json, 2 request (thỉnh thoảng 3), KHÔNG cào sản phẩm:
  1. /meta.json                      tên shop, tiền tệ, published_products_count (= tổng sp đang bán)
  2. /products.json?limit=30         30 sp mới nhất (Shopify trả theo ngày tạo, mới trước — đã kiểm 14/10 với wondroot)
     → số sp đăng 7 / 30 ngày (theo published_at), giá min/max của 30 sp đó (ép USD)
  3. chỉ khi cả 30 sp đều mới trong 30 ngày: /products.json?limit=250 để đếm đủ (vẫn 1 request)
Ghi data/raw/<ngày>/shopify.json (không lưu danh sách sản phẩm). Chạy được cả Windows lẫn Linux.
    python collect/run_cloud.py
    python collect/run_cloud.py --limit 5
    python collect/run_cloud.py --only wondroot.com,woodemon.com --delay 2
Mã thoát: 0 nếu ít nhất 1 shop OK, 1 nếu không shop nào.
"""
import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import active_shops, load_raw, log, now_utc, save_raw, today_vn, utf8_stdout  # noqa: E402
from shopify_lib import Http, to_float  # noqa: E402

SRC = "Shopify công khai: /meta.json + /products.json?limit=30 (30 sp mới nhất, giá ép USD)"


def pub_date(p):
    s = p.get("published_at") or p.get("created_at") or ""
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc).date()
    except ValueError:
        return None


def run_one(http, domain, date):
    t0 = time.time()
    n0 = http.n_requests
    d0 = dt.date.fromisoformat(date)
    meta, err_meta = http.json(f"https://{domain}/meta.json")
    data, err = http.json(f"https://{domain}/products.json?limit=30")
    prods = (data or {}).get("products") if isinstance(data, dict) else None
    if not isinstance(prods, list):
        return {"status": "loi", "error": f"products.json: {err or 'không có products'}", "at": now_utc(), "src": SRC}
    newest30 = prods[:30]
    dates = [pub_date(p) for p in newest30]
    capped = False
    if len(newest30) == 30 and all(x and (d0 - x).days <= 30 for x in dates):
        big, _ = http.json(f"https://{domain}/products.json?limit=250")
        bp = (big or {}).get("products") if isinstance(big, dict) else None
        if isinstance(bp, list) and bp:
            dates = [pub_date(p) for p in bp]
            capped = len(bp) == 250 and all(x and (d0 - x).days <= 30 for x in dates)
    new7 = sum(1 for x in dates if x and 0 <= (d0 - x).days <= 7)
    new30 = sum(1 for x in dates if x and 0 <= (d0 - x).days <= 30)
    prices = [to_float(v.get("price")) for p in newest30 for v in p.get("variants") or []]
    prices = [x for x in prices if x]
    meta = meta if isinstance(meta, dict) else {}
    newest = max((x for x in dates if x), default=None)
    return {"status": "ok", "name": (meta.get("name") or "").strip() or None, "currency": meta.get("currency"),
            "n_products": meta.get("published_products_count"), "new_7d": new7, "new_30d": new30, "capped": capped,
            "price_min": min(prices) if prices else None, "price_max": max(prices) if prices else None,
            "newest": newest.isoformat() if newest else None, "n_sample": len(newest30),
            "meta_error": err_meta, "requests": http.n_requests - n0, "at": now_utc(), "src": SRC,
            "secs": round(time.time() - t0, 1)}


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Shopify nhẹ (meta + 30 sp mới nhất) cho mọi shop trong shops.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--date", default="", help="ngày dữ liệu (mặc định hôm nay giờ VN)")
    ap.add_argument("--delay", type=float, default=1.5)
    a = ap.parse_args()
    date = a.date or today_vn()
    shops = active_shops("shopify")
    if a.only:
        only = {x.strip() for x in a.only.split(",") if x.strip()}
        shops = [s for s in shops if s["id"] in only]
    if a.limit:
        shops = shops[: a.limit]
    if not shops:
        sys.exit("Không có shop Shopify nào (data/shops.json trống? chạy sync_shops.py ở máy local)")
    http = Http(delay=a.delay)
    doc = load_raw(date, "shopify")
    ok = 0
    t0 = time.time()
    log(f"=== Shopify nhẹ · {len(shops)} shop · {date}")
    for i, s in enumerate(shops, 1):
        try:
            rec = run_one(http, s["domain"], date)
        except Exception as ex:  # noqa: BLE001  lỗi 1 shop không làm chết cả lượt
            rec = {"status": "loi", "error": f"{type(ex).__name__}: {str(ex)[:150]}", "at": now_utc(), "src": SRC}
        if rec["status"] == "ok":
            ok += 1
            doc["shops"][s["id"]] = rec
            log(f"  [{i}/{len(shops)}] {s['domain']}: {rec['name']} · {rec['n_products']} sp · mới 7d {rec['new_7d']}"
                f" / 30d {rec['new_30d']}{'+' if rec['capped'] else ''} · giá {rec['price_min']}–{rec['price_max']}"
                f" {rec['currency']} · {rec['requests']} req · {rec['secs']}s")
        else:
            old = doc["shops"].get(s["id"])
            if not old or old.get("status") != "ok":   # không đè số tốt đã có trong ngày bằng lỗi
                doc["shops"][s["id"]] = rec
            log(f"  [{i}/{len(shops)}] {s['domain']}: ! {rec.get('error')}")
    save_raw(date, "shopify", doc)
    log(f"Xong: {ok}/{len(shops)} shop OK · {http.n_requests} request · {time.time() - t0:.0f} s")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
