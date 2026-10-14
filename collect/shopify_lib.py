# -*- coding: utf-8 -*-
"""shopify_lib.py — session HTTP đọc dữ liệu công khai của shop Shopify (dùng cho run_cloud.py).

Gốc chép từ `4-SPY/spy_shopify.py` (bản 14/10/2026); từ 14/10 bỏ phần tải catalog + rank (mô hình mới không lưu sản phẩm).
  - 429: tôn trọng Retry-After, nghỉ tăng dần 15/30/60/90 s (Shopify giới hạn theo IP cho MỌI shop).
  - Ép giá USD: gửi cookie cart_currency=USD + localization=US mỗi request và KHÔNG lưu cookie shop trả về
    (thử 14/10: từ IP Việt Nam, carpenter-farmhouse.com trả giá VND 263000 thay vì $10).
"""
import http.cookiejar
import random
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
FORCE_COOKIES = {"cart_currency": "USD", "localization": "US"}


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
        self.n_requests = 0

    def get(self, url, accept="*/*"):
        for attempt in range(4):
            wait = self.delay + random.uniform(0, 0.5) - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.s.get(url, headers={"Accept": accept}, cookies=FORCE_COOKIES, timeout=30)
                self._last = time.time()
                self.n_requests += 1
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

    def json(self, url):
        """GET JSON → (dict | None, mã lỗi | None)."""
        r = self.get(url, accept="application/json")
        if r is None:
            return None, "mạng"
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        try:
            return r.json(), None
        except ValueError:
            return None, "không phải JSON"


def to_float(x):
    try:
        return round(float(x), 2)
    except (TypeError, ValueError):
        return None
