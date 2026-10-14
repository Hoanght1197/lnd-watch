# -*- coding: utf-8 -*-
"""run_shopify.py — thu snapshot Shopify cho mọi domain trong watch.txt.

Mỗi domain: /products.json (catalog) + /collections/all?sort_by=best-selling (rank)
→ data/shopify/<domain>/<YYYY-MM-DD>.json (cùng format snapshot của 4-SPY/spy_shopify.py,
thêm trường `shop_name` lấy từ /meta.json). Cùng ngày chạy lại thì ghi đè.

Chạy được trên Linux (GitHub Actions) và Windows. Chỉ ĐỌC dữ liệu công khai.
    python collect/run_shopify.py                       # mọi domain trong watch.txt
    python collect/run_shopify.py --only wondroot.com,woodemon.com --delay 2
    python collect/run_shopify.py --date 2026-10-14     # ép ngày snapshot
Ngày mặc định = ngày theo giờ Việt Nam (UTC+7) để khớp với phần Etsy/ads chạy 6h sáng ở máy anh Hoàng
(Actions chạy 23:00 UTC = 6:00 sáng VN hôm sau).
Mã thoát: 0 nếu ít nhất 1 shop OK, 1 nếu không shop nào lấy được.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from shopify_lib import Http, fetch_catalog, fetch_rank, log, norm_domain, read_list  # noqa: E402

DATA_DIR = ROOT / "data" / "shopify"
VN = dt.timezone(dt.timedelta(hours=7))


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def shop_name(http, domain, prods):
    """Tên shop: /meta.json (Shopify trả {"name": ...}); không được thì vendor phổ biến nhất."""
    r = http.get(f"https://{domain}/meta.json", accept="application/json")
    try:
        if r is not None and r.status_code == 200:
            n = (r.json() or {}).get("name")
            if n:
                return str(n).strip()
    except ValueError:
        pass
    c = Counter(p.get("vendor") for p in prods if p.get("vendor"))
    return c.most_common(1)[0][0] if c else domain


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))  # thô ghi gọn cho repo khỏi phình
    os.replace(tmp, path)


def run_one(http, domain, date, no_rank, rank_pages):
    log(f"\n== {domain}")
    prods = fetch_catalog(http, domain)
    if not prods:
        log("  ! không lấy được catalog → bỏ qua shop này")
        return None
    if no_rank:
        rank, src = [], "bỏ qua (--no-rank)"
    else:
        rank, src = fetch_rank(http, domain, rank_pages)
    handles = {p["handle"] for p in prods}
    name = shop_name(http, domain, prods)
    log(f"  {name}: {len(prods)} sp · rank {len(rank)} handle ({sum(h in handles for h in rank)} khớp) · {src}")
    snap = {"domain": domain, "date": date, "fetched_at": now_utc(), "shop_name": name,
            "rank_source": src, "rank": rank, "products": prods}
    save_json(DATA_DIR / domain / f"{date}.json", snap)
    return snap


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Thu snapshot Shopify (catalog + rank bestseller)")
    ap.add_argument("--watch", default=str(ROOT / "watch.txt"), help="file danh sách domain")
    ap.add_argument("--only", default="", help="chỉ chạy các domain này, cách nhau dấu phẩy")
    ap.add_argument("--date", default="", help="ngày snapshot YYYY-MM-DD (mặc định hôm nay giờ VN)")
    ap.add_argument("--delay", type=float, default=1.5, help="giây nghỉ giữa request (mặc định 1.5)")
    ap.add_argument("--no-rank", action="store_true", help="bỏ bước lấy rank bestseller")
    ap.add_argument("--rank-pages", type=int, default=25, help="tối đa số trang best-selling mỗi shop (mặc định 25)")
    ap.add_argument("--retry-wait", type=int, default=180,
                    help="giây nghỉ trước vòng chạy lại các shop lỗi (0 = không chạy lại)")
    a = ap.parse_args()

    date = a.date or dt.datetime.now(VN).date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        sys.exit("--date phải dạng YYYY-MM-DD")
    src = a.only.split(",") if a.only else read_list(a.watch)
    domains = []
    for d in src:
        d = norm_domain(d)
        if d and d not in domains:
            domains.append(d)
    if not domains:
        sys.exit(f"Không có domain nào (kiểm tra {a.watch} / --only)")

    http = Http(a.delay)
    ok, loi = [], []
    log(f"run_shopify {date}: {len(domains)} shop")

    def one(d):
        try:  # lỗi 1 shop không làm chết cả lượt
            return run_one(http, d, date, a.no_rank, a.rank_pages)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            log(f"  ! {d}: lỗi {type(e).__name__}: {e}")
            return None

    for d in domains:
        (ok if one(d) else loi).append(d)
    if loi and a.retry_wait > 0:
        # thường do 429 (Shopify giới hạn theo IP) → nghỉ rồi chạy lại 1 vòng các shop lỗi
        log(f"\n{len(loi)} shop lỗi → nghỉ {a.retry_wait}s rồi chạy lại: {', '.join(loi)}")
        time.sleep(a.retry_wait)
        con = []
        for d in loi:
            (ok if one(d) else con).append(d)
        loi = con
    log(f"\nXong: OK {len(ok)} ({', '.join(ok)}) · lỗi {len(loi)} ({', '.join(loi) or '-'})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
