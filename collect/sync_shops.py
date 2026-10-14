# -*- coding: utf-8 -*-
r"""sync_shops.py — tạo / cập nhật data/shops.json (danh sách shop theo dõi). CHỈ chạy ở máy local (đọc ..\4-SPY).

Nguồn (chỉ ĐỌC, không sửa 4-SPY):
  - 4-SPY/data/discover/shops.json           kho discover Shopify (nguồn, từ khoá, số ads, số sp cùng ngách)
  - 4-SPY/reports/<ngày mới nhất>_etsy_discover.csv   shop Etsy (điểm, sales, rating…)
  - ../shops_extra.txt                        thêm / tắt tay (xem chú thích trong file)
Chọn:
  - Shopify: verify.platform == Shopify và (san_pham_cung_nganh ≥ 20 hoặc so_ads ≥ 1)
  - Etsy: top 15 theo `diem`
Tích luỹ: shop đã có KHÔNG bao giờ bị xoá; chỉ cập nhật thông tin. Cờ `active` giữ nguyên trừ khi shops_extra.txt đổi.
    python collect/sync_shops.py
    python collect/sync_shops.py --spy-dir "F:\CHU TAN\BUILD STORE SHOPIFY\4-SPY" --etsy-top 15 --min-niche 20
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, SHOPS_FILE, load_json, log, norm_domain, now_utc, save_json, today_vn, utf8_stdout  # noqa: E402

EXTRA_FILE = ROOT / "shops_extra.txt"


def shopify_from_discover(path, min_niche):
    d = load_json(path, {}) or {}
    out = []
    for dom, v in d.items():
        vf = v.get("verify") or {}
        if vf.get("platform") != "Shopify":
            continue
        niche = vf.get("san_pham_cung_nganh") or 0
        ads = v.get("so_ads") or 0
        if niche < min_niche and ads < 1:
            continue
        domain = norm_domain(vf.get("final_domain") or dom)
        out.append({
            "id": domain, "platform": "shopify", "domain": domain, "name": domain,
            "first_seen": v.get("lan_dau_thay") or today_vn(),
            "sources": sorted(set(v.get("nguon") or [])) + ["discover"],
            "note": f"discover: {niche} sp cùng ngách / {vf.get('tong_san_pham')} sp · {ads} ads · "
                    f"giá {vf.get('gia_min')}–{vf.get('gia_max')}",
            "keywords": v.get("tu_khoa") or [],
            "discover": {"so_ads": ads, "san_pham_cung_nganh": niche, "tong_san_pham": vf.get("tong_san_pham"),
                         "gia_min": vf.get("gia_min"), "gia_max": vf.get("gia_max")},
        })
    return out


def etsy_from_csv(spy_dir, top):
    reps = sorted((spy_dir / "reports").glob("*_etsy_discover.csv"))
    if not reps:
        log("  ! không thấy *_etsy_discover.csv trong 4-SPY/reports")
        return []
    path = reps[-1]
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return 0.0
    rows.sort(key=lambda r: (-num(r.get("diem")), -num(r.get("sales_shop"))))
    date = path.name[:10]
    out = []
    for r in rows[:top]:
        name = (r.get("shop") or "").strip()
        if not name:
            continue
        out.append({
            "id": f"etsy:{name}", "platform": "etsy", "etsy": name, "name": name,
            "url": r.get("link_shop") or f"https://www.etsy.com/shop/{name}",
            "first_seen": date, "sources": ["etsy-discover"],
            "note": f"điểm {r.get('diem')} · ~{r.get('sales_shop')} sales · {r.get('rating')}★ · "
                    f"{r.get('tuoi_shop')} · ship từ {r.get('ship_tu')}",
            "keywords": [k.strip() for k in (r.get("tu_khoa") or "").split("|") if k.strip()],
        })
    return out


def parse_extra(path):
    """Mỗi dòng: `domain` | `etsy:TenShop` ; thêm `!` ở đầu để TẮT (active=false); phần sau `#` = ghi chú."""
    items = []
    if not path.exists():
        return items
    for line in path.read_text(encoding="utf-8").splitlines():
        body, _, note = line.partition("#")
        body = body.strip()
        if not body:
            continue
        off = body.startswith("!")
        body = body.lstrip("!").strip()
        if body.lower().startswith("etsy:"):
            name = body.split(":", 1)[1].strip()
            items.append(({"id": f"etsy:{name}", "platform": "etsy", "etsy": name, "name": name,
                           "url": f"https://www.etsy.com/shop/{name}"}, off, note.strip()))
        else:
            dom = norm_domain(body)
            if dom:
                items.append(({"id": dom, "platform": "shopify", "domain": dom, "name": dom}, off, note.strip()))
    return items


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Cập nhật data/shops.json")
    ap.add_argument("--spy-dir", default=str(ROOT.parent / "4-SPY"))
    ap.add_argument("--etsy-top", type=int, default=15)
    ap.add_argument("--min-niche", type=int, default=20)
    a = ap.parse_args()
    spy = Path(a.spy_dir)
    today = today_vn()

    old = load_json(SHOPS_FILE, {}) or {}
    shops = {s["id"]: s for s in old.get("shops") or []}
    n_before = len(shops)

    found = shopify_from_discover(spy / "data" / "discover" / "shops.json", a.min_niche) + etsy_from_csv(spy, a.etsy_top)
    added = []
    for s in found:
        cur = shops.get(s["id"])
        if cur is None:
            s["active"] = True
            s["added_on"] = today
            shops[s["id"]] = s
            added.append(s["id"])
        else:   # cập nhật thông tin mô tả, giữ first_seen / active / name đã sửa tay
            for k in ("note", "keywords", "discover", "url"):
                if s.get(k):
                    cur[k] = s[k]
            cur["sources"] = sorted(set(cur.get("sources") or []) | set(s.get("sources") or []))
            cur["first_seen"] = min(cur.get("first_seen") or s["first_seen"], s["first_seen"])

    for s, off, note in parse_extra(EXTRA_FILE):
        cur = shops.get(s["id"])
        if cur is None:
            s.update({"first_seen": today, "added_on": today, "sources": ["tay"], "note": note, "keywords": []})
            shops[s["id"]] = cur = s
            added.append(s["id"])
        else:
            cur["sources"] = sorted(set(cur.get("sources") or []) | {"tay"})
            if note:
                cur["note_tay"] = note
        cur["active"] = not off

    lst = sorted(shops.values(), key=lambda s: (s["platform"] != "shopify", s["id"].lower()))
    save_json(SHOPS_FILE, {"updated_at": now_utc(), "rule": f"Shopify: sp cùng ngách ≥ {a.min_niche} hoặc ads ≥ 1 · "
                                                           f"Etsy: top {a.etsy_top} theo điểm · + shops_extra.txt",
                           "shops": lst}, compact=False)
    act = [s for s in lst if s.get("active", True)]
    n_sp = sum(s["platform"] == "shopify" for s in act)
    n_et = sum(s["platform"] == "etsy" for s in act)
    log(f"shops.json: {len(lst)} shop ({n_before} trước, +{len(added)} mới) · đang theo dõi: Shopify {n_sp} · Etsy {n_et}"
        f" · tắt {len(lst) - len(act)}")
    if added:
        log("  mới: " + ", ".join(added))


if __name__ == "__main__":
    main()
