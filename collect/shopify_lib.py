# -*- coding: utf-8 -*-
"""shopify_lib.py — hàm lõi đọc catalog + rank bestseller của shop Shopify (chỉ đọc dữ liệu công khai).

CHÉP từ `4-SPY/spy_shopify.py` (bản 14/10/2026) để chạy được trên GitHub Actions (cloud không có 4-SPY).
Sửa 4-SPY thì nhớ chép lại phần tương ứng ở đây. Khác bản gốc:
  - 429: tôn trọng header Retry-After, nghỉ tăng dần 15/30/60/90 s (Shopify giới hạn theo IP cho MỌI shop,
    bị 429 ở shop này thì shop sau cũng bị) → run_shopify.py có thêm vòng chạy lại shop lỗi sau khi nghỉ.
  - Ép giá USD: gửi cookie cart_currency=USD + localization=US mỗi request và KHÔNG lưu cookie shop trả về
    (thử 14/10: từ IP Việt Nam có Accept-Language, carpenter-farmhouse.com trả giá VND 263000 thay vì $10).
  - fetch_rank có tham số max_pages (mặc định 25 trang thay vì 80) để bớt request HTML nặng.
  - log ra stdout UTF-8.
"""
import http.cookiejar
import random
import re
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
FORCE_COOKIES = {"cart_currency": "USD", "localization": "US"}
MAX_PAGES_JSON = 100      # 100 x 250 = 25.000 sp, quá đủ
MAX_PAGES_RANK = 25      # bản gốc 80; 25 trang HTML đủ top vài trăm sp mà đỡ bị 429

# bắt /products/<handle> và /collections/<x>/products/<handle>
RE_PRODUCT_LINK = re.compile(r'href=["\'](?:https?://[^"\'/]+)?(?:/[a-z]{2}(?:-[a-z]{2})?)?'
                             r'(?:/collections/[^"\'/?#]+)?/products/([A-Za-z0-9\-_%.]+)',
                             re.IGNORECASE)


def log(msg):
    print(msg, flush=True)


class Http:
    """Session requests có nghỉ `delay`..`delay+0.5` giây giữa các request, retry 429 / lỗi mạng."""

    def __init__(self, delay=1.5):
        self.delay = delay
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        # không lưu cookie shop đặt (cart_currency=VND / localization=VN theo IP) → luôn xem giá USD
        self.s.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        self._last = 0.0

    def get(self, url, accept="*/*"):
        for attempt in range(4):
            wait = self.delay + random.uniform(0, 0.5) - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.s.get(url, headers={"Accept": accept}, cookies=FORCE_COOKIES, timeout=30)
                self._last = time.time()
            except requests.RequestException as e:
                self._last = time.time()
                log(f"    lỗi mạng ({e.__class__.__name__}), thử lại")
                time.sleep(3)
                continue
            if r.status_code == 429:
                try:
                    ra = int(r.headers.get("Retry-After") or 0)
                except ValueError:
                    ra = 0
                nghi = min(120, max(ra, (15, 30, 60, 90)[attempt]))
                log(f"    429 quá tải, nghỉ {nghi}s rồi thử lại")
                time.sleep(nghi)
                continue
            return r
        return None


# ---------------------------------------------------------------- catalog


def to_float(x):
    try:
        return round(float(x), 2)
    except (TypeError, ValueError):
        return None


def slim_product(p, domain):
    variants = []
    for v in p.get("variants") or []:
        variants.append({
            "id": v.get("id"),
            "title": v.get("title"),
            "price": to_float(v.get("price")),
            "compare_at_price": to_float(v.get("compare_at_price")),
            "available": v.get("available"),  # None nếu shop không trả
            "sku": v.get("sku") or "",
        })
    prices = [v["price"] for v in variants if v["price"] is not None]
    images = p.get("images") or []
    tags = p.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return {
        "id": p.get("id"),
        "handle": p.get("handle"),
        "title": p.get("title"),
        "product_type": p.get("product_type") or "",
        "vendor": p.get("vendor") or "",
        "tags": tags,
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
        "published_at": p.get("published_at"),
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "options": [{"name": o.get("name"), "values": o.get("values")} for o in p.get("options") or []],
        "n_variants": len(variants),
        "variants": variants,
        "n_images": len(images),
        "image": images[0].get("src") if images else "",
        "url": f"https://{domain}/products/{p.get('handle')}",
    }


def fetch_catalog(http, domain):
    """Trả list sản phẩm, hoặc None nếu không phải Shopify / lỗi."""
    out, seen = [], set()
    for page in range(1, MAX_PAGES_JSON + 1):
        url = f"https://{domain}/products.json?limit=250&page={page}"
        r = http.get(url, accept="application/json")
        if r is None:
            log(f"  ! {domain}: không kết nối được")
            return None if page == 1 else out
        if r.status_code != 200:
            log(f"  ! {domain}: products.json HTTP {r.status_code} → bỏ qua (có thể không phải Shopify)")
            return None if page == 1 else out
        try:
            items = r.json().get("products")
        except ValueError:
            log(f"  ! {domain}: products.json không phải JSON → bỏ qua (không phải Shopify?)")
            return None if page == 1 else out
        if not isinstance(items, list):
            log(f"  ! {domain}: JSON lạ, không có 'products' → bỏ qua")
            return None if page == 1 else out
        if not items:
            break
        new = 0
        for p in items:
            if p.get("id") in seen:
                continue
            seen.add(p.get("id"))
            out.append(slim_product(p, domain))
            new += 1
        log(f"  trang {page}: +{new} sp (tổng {len(out)})")
        if new == 0 or len(items) < 250:
            break
    return out


# ---------------------------------------------------------------- rank bestseller


def handles_in_html(html):
    """Lấy handle sản phẩm theo thứ tự xuất hiện, bỏ trùng.
    Ưu tiên phần <main> để tránh link ở menu/footer/gợi ý."""
    m_lo = re.search(r"<main[\s>]", html, re.IGNORECASE)   # đúng thẻ <main>, không bắt nhầm <main-menu>
    lo = m_lo.start() if m_lo else -1
    hi = html.rfind("</main>")
    body = html[lo:hi] if lo != -1 and hi > lo else html
    seen, order = set(), []
    for m in RE_PRODUCT_LINK.finditer(body):
        h = m.group(1).strip().lower().rstrip(".")
        if h and h not in seen:
            seen.add(h)
            order.append(h)
    return order


def fetch_rank(http, domain, max_pages=MAX_PAGES_RANK):
    """Trả (list handle theo thứ hạng, nguồn) hoặc ([], lý do)."""
    order, seen = [], set()
    for page in range(1, max_pages + 1):
        url = f"https://{domain}/collections/all?sort_by=best-selling"
        if page > 1:
            url += f"&page={page}"
        r = http.get(url, accept="text/html")
        if r is None or r.status_code != 200:
            code = "mạng" if r is None else r.status_code
            if page == 1:
                log(f"  ! rank: /collections/all lỗi ({code}), thử fallback")
                break
            log(f"  rank: trang {page} lỗi ({code}), dừng")
            break
        new = [h for h in handles_in_html(r.text) if h not in seen]
        if not new:
            break
        for h in new:
            seen.add(h)
            order.append(h)
        log(f"  rank trang {page}: +{len(new)} (tổng {len(order)})")
    if order:
        return order, "collections/all?sort_by=best-selling"

    # fallback: products.json của collection all (Shopify có thể KHÔNG sắp theo doanh số)
    url = f"https://{domain}/collections/all/products.json?limit=250&sort_by=best-selling"
    r = http.get(url, accept="application/json")
    try:
        items = r.json().get("products") if r is not None and r.status_code == 200 else None
    except ValueError:
        items = None
    if items:
        return ([p["handle"] for p in items],
                "collections/all/products.json (FALLBACK, thứ tự có thể không phải doanh số)")
    return [], "không lấy được rank"


def read_list(path):
    """Đọc file danh sách (mỗi dòng 1 mục, '#' là ghi chú). Domain: bỏ https://, www., '/' cuối."""
    out = []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return out
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line and line not in out:
            out.append(line)
    return out


def norm_domain(s):
    s = re.sub(r"^https?://", "", (s or "").strip().lower()).split("/")[0]
    return s[4:] if s.startswith("www.") else s
