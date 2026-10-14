# -*- coding: utf-8 -*-
"""common.py — hàm dùng chung cho bộ thu LND Watch (mô hình mới 14/10/2026: đơn vị = SHOP, không lưu sản phẩm).

Chạy được cả Linux (GitHub Actions) lẫn Windows. Chỉ stdlib.
Đường dẫn dữ liệu:
    data/shops.json                 danh sách shop (sync_shops.py)
    data/raw/<ngày>/<nguồn>.json    số liệu thô từng nguồn trong ngày: ads | etsy | shopify  (mỗi nguồn 1 file → git không xung đột)
    data/traffic.json               SimilarWeb, mới nhất + lịch sử theo tháng (run_local.py --traffic)
    data/daily/<ngày>.json          gộp mọi nguồn của ngày, 1 dòng / shop (build.py)
    data/leaderboard.json           bảng xếp hạng web đọc (build.py)
    data/alerts.json                cảnh báo 90 ngày (build.py)
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = Path(os.environ["LND_DATA"]) if os.environ.get("LND_DATA") else ROOT / "data"   # LND_DATA: thử trên bản sao
RAW = DATA / "raw"
DAILY = DATA / "daily"
SHOPS_FILE = DATA / "shops.json"
TRAFFIC_FILE = DATA / "traffic.json"
VN = dt.timezone(dt.timedelta(hours=7))
RE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def utf8_stdout():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass


def log(msg):
    print(msg, flush=True)


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_vn():
    """Ngày dữ liệu = ngày giờ Việt Nam (Actions 23:00 UTC = 6:00 sáng VN hôm sau, khớp phần local 6:05)."""
    return dt.datetime.now(VN).date().isoformat()


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def save_json(path, obj, compact=True):
    """Ghi nguyên tử. compact = không thụt dòng (file thô / theo ngày); False = indent 1 (file người đọc)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if compact:
        txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    else:
        txt = json.dumps(obj, ensure_ascii=False, indent=1)
    tmp.write_text(txt + "\n", encoding="utf-8")
    os.replace(tmp, path)


def raw_path(date, source):
    return RAW / date / f"{source}.json"


def load_raw(date, source):
    """{"date","source","updated_at","shops":{id: record}}"""
    return load_json(raw_path(date, source), None) or {"date": date, "source": source, "updated_at": None, "shops": {}}


def save_raw(date, source, doc):
    doc["date"], doc["source"], doc["updated_at"] = date, source, now_utc()
    doc["shops"] = dict(sorted(doc["shops"].items()))
    save_json(raw_path(date, source), doc)


def raw_dates():
    if not RAW.exists():
        return []
    return sorted(p.name for p in RAW.iterdir() if p.is_dir() and RE_DATE.fullmatch(p.name))


def norm_domain(s):
    s = re.sub(r"^https?://", "", (s or "").strip().lower()).split("/")[0].split("?")[0].strip(".")
    return s[4:] if s.startswith("www.") else s


def parse_k(s):
    """'39.9K' → 39900 ; '1.2M' → 1200000 ; '~200' → 200 ; '1,234' → 1234 ; '' → None"""
    if s is None:
        return None
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([kKmMbB]?)", str(s))
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    v *= {"k": 1e3, "m": 1e6, "b": 1e9}.get(m.group(2).lower(), 1)
    return int(round(v))


def load_shops():
    d = load_json(SHOPS_FILE, None) or {"shops": []}
    return d.get("shops") or []


def active_shops(platform=None):
    return [s for s in load_shops() if s.get("active", True) and (platform is None or s["platform"] == platform)]


def read_list(path):
    out = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return out
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line and line not in out:
            out.append(line)
    return out
