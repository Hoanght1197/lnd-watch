# -*- coding: utf-8 -*-
"""run_ads.py — lấy ads ĐANG CHẠY trên Meta (Facebook) Ad Library cho từng domain/page trong ads_watch.txt.

CHỈ chạy ở máy anh Hoàng (cần Chrome 9230 thật, FB chặn IP cloud). Dùng `cdp.Tab` + `unwrap`/`norm_domain`
của `..\\4-SPY` (import qua sys.path, không sửa 4-SPY). Mở 1 tab mới, đọc, rồi LUÔN đóng tab đó.

ads_watch.txt, mỗi dòng:
    wondroot.com          → tìm "wondroot.com" trên Ad Library, giữ ad có landing/text về domain đó
    page:123456789        → mọi ad đang chạy của Facebook page id 123456789 (key lưu = page-123456789)
Ghi: data/ads/<key>/<YYYY-MM-DD>.json
    {"key","date","fetched_at","source","url","n_cards","n_matched",
     "ads":[{"library_id","first_seen","start_date","text","landing","product_handle","image",
             "platforms","page_name","n_versions","active":true}]}
first_seen giữ từ snapshot trước (ad đã thấy thì giữ ngày thấy đầu tiên). Bị FB chặn/đòi login → không ghi file.
    python collect/run_ads.py                       # mọi dòng trong ads_watch.txt
    python collect/run_ads.py --only wondroot.com --scroll 8
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA_DIR = ROOT / "data" / "ads"
VN = dt.timezone(dt.timedelta(hours=7))
RE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# Thẻ ad trên Ad Library: mở rộng JS_FB của 4-SPY/discover.py (thêm ảnh, ngày bắt đầu, tên page).
JS_ADS = r"""
(() => {
  const out = [];
  const labels = Array.from(document.querySelectorAll('span,div'))
      .filter(e => e.childElementCount === 0 && /^Library ID:?\s*\d+/.test(e.textContent.trim()));
  for (const el of labels) {
    const id = (el.textContent.match(/\d{6,}/) || [''])[0];
    let card = el, p = el.parentElement;
    while (p) {
      const n = (p.textContent.match(/Library ID/g) || []).length;
      if (n > 1) break;
      card = p; p = p.parentElement;
    }
    const links = Array.from(card.querySelectorAll('a[href]')).map(a => a.href).filter(h => h.startsWith('http'));
    const imgs = Array.from(card.querySelectorAll('img')).map(i => ({src: i.currentSrc || i.src || '', w: i.naturalWidth || i.width || 0}))
        .filter(i => i.src.startsWith('http') && i.w >= 100 && !/s60x60/.test(i.src));  // bỏ avatar page 60x60
    imgs.sort((a, b) => b.w - a.w);
    const vid = card.querySelector('video');
    out.push({id, links, text: card.innerText.slice(0, 3000), image: imgs.length ? imgs[0].src : '',
              poster: vid ? (vid.poster || '') : ''});
  }
  const blockedTxt = /log in to continue|you must log in|temporarily blocked/i.test(document.body.innerText.slice(0, 4000));
  return {cards: out, blockedTxt, nCards: out.length};
})()
"""

MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
RE_START1 = re.compile(r"Started running on\s+(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})")
RE_START2 = re.compile(r"Started running on\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})")
RE_HANDLE = re.compile(r"/products/([A-Za-z0-9\-_%.]+)")
NOISE = re.compile(r"^(​|Active|Inactive|Platforms|Open Drop-down|See ad details|See summary details|Sponsored|"
                   r"This ad has multiple versions|Library ID.*|Started running on.*|\d+ ads? use(s)? this creative and text|"
                   r"Shop Now|Learn More|Sign Up|Order Now|Buy Now|See Details|Book Now|Get Offer|Send Message|Contact Us|Download|Watch More|Apply Now|Get Quote|Subscribe|Low impression count|\d+:\d+ / \d+:\d+)$", re.I)


def log(msg):
    print(msg, flush=True)


def load_spy(spy_dir):
    sys.path.insert(0, str(spy_dir))
    import cdp  # noqa: E402
    import discover  # noqa: E402
    return cdp, discover


def parse_start(text):
    for rx, order in ((RE_START1, "dmy"), (RE_START2, "mdy")):
        m = rx.search(text or "")
        if m:
            a, b, y = m.groups()
            day, mon = (a, b) if order == "dmy" else (b, a)
            mo = MONTHS.get(mon.lower()[:3])
            try:
                return dt.date(int(y), mo, int(day)).isoformat() if mo else None
            except ValueError:
                return None
    return None


def parse_card(c, unwrap):
    t = c.get("text") or ""
    lines = [l.strip() for l in t.split("\n")]
    # tên page = dòng ngay trước "Sponsored"; nội dung = các dòng sau "Sponsored"
    page_name, body = "", []
    if "Sponsored" in lines:
        i = lines.index("Sponsored")
        page_name = next((l for l in reversed(lines[:i]) if l and not NOISE.match(l)), "")
        body = [l for l in lines[i + 1:] if not NOISE.match(l)]
    else:
        body = [l for l in lines if l and not NOISE.match(l)]
    text = "\n".join(body).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)[:1500]
    links = [unwrap(l) for l in c.get("links") or []]
    links = [l for l in links if "facebook.com" not in l and "fb.me" not in l and "instagram.com" not in l]
    m = re.search(r"(\d+) ads? use", t)
    nv = int(m.group(1)) if m else (2 if "multiple versions" in t else 1)
    return {"page_name": page_name, "text": text, "links": links, "start_date": parse_start(t), "n_versions": nv,
            "image": c.get("image") or c.get("poster") or ""}


def pick_landing(links, domain=None):
    def good(l):
        return not domain or domain in (urllib.parse.urlsplit(l).hostname or "")
    prod = [l for l in links if "/products/" in l and good(l)]
    anyl = [l for l in links if good(l)]
    best = (prod or anyl or [""])[0]
    return best.split("?")[0] if "/products/" in best else best


def prev_snapshot(key, date):
    d = DATA_DIR / key
    if not d.exists():
        return {}
    dates = sorted(p.stem for p in d.glob("*.json") if RE_DATE.fullmatch(p.stem) and p.stem < date)
    for x in reversed(dates):
        try:
            s = json.loads((d / f"{x}.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        return {str(a["library_id"]): a for a in s.get("ads") or [] if a.get("library_id")}
    return {}


def scan(tab, url, max_scroll):
    # tab nền: giả lập đang được focus + vòng đời active để FB chịu tải thêm khi cuộn (không cướp focus của tab khác)
    for m, p in (("Emulation.setFocusEmulationEnabled", {"enabled": True}),
                 ("Page.setWebLifecycleState", {"state": "active"})):
        try:
            tab.send(m, p)
        except Exception:  # noqa: BLE001
            pass
    tab.goto(url, wait=7)
    n_prev, same = -1, 0
    r = {}
    for _ in range(max_scroll + 1):
        r = tab.eval(JS_ADS, timeout=90) or {}
        n = r.get("nCards") or 0
        if r.get("blockedTxt"):
            break
        same = same + 1 if n == n_prev else 0
        if same >= 3:   # cuộn 3 lần liền không thêm thẻ → hết
            break
        if same:        # chưa thêm thẻ → kéo lên 1 đoạn rồi mới cuộn xuống lại
            tab.eval("window.scrollBy(0, -2500); window.dispatchEvent(new Event('scroll'));")
            time.sleep(1)
        n_prev = n
        # đọc chiều cao/vị trí TRƯỚC khi cuộn: ép tab nền tính layout, thiếu bước này FB dừng ở ~48 thẻ (thử 14/10)
        h = tab.eval("document.documentElement.scrollHeight")
        y = tab.eval("window.scrollY")
        log(f"  cuộn {_}: {n} thẻ · cao {h} · y {y}")
        # Tab chạy nền: cuộn thường không kích hoạt tải thêm → cuộn 2 nhịp + bắn sự kiện 'scroll' bằng tay
        # (Input.dispatchMouseEvent bị treo ở tab nền nên không dùng).
        tab.eval("window.scrollTo(0, document.documentElement.scrollHeight - 1200);"
                 "window.dispatchEvent(new Event('scroll'));")
        time.sleep(0.5)
        tab.eval("window.scrollTo(0, document.documentElement.scrollHeight);"
                 "window.dispatchEvent(new Event('scroll'));"
                 "[document.documentElement.scrollHeight, window.scrollY]")   # đọc lại để ép trình duyệt tính layout
        time.sleep(3)
    return r


def run_key(cdp_mod, discover, tab, entry, date, max_scroll):
    entry = entry.strip()
    if entry.lower().startswith("page:"):
        pid = re.sub(r"\D", "", entry.split(":", 1)[1])
        key, domain = f"page-{pid}", None
        url = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US"
               f"&view_all_page_id={pid}&search_type=page&media_type=all")
    else:
        domain = discover.norm_domain(entry)
        key = domain
        url = ("https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=US&q="
               + urllib.parse.quote(domain) + "&search_type=keyword_unordered&media_type=all")
    log(f"\n== {key}")
    r = scan(tab, url, max_scroll)
    if r.get("blockedTxt") or "/login" in (tab.final_url() or ""):
        log("  ! FB đòi login / chặn → KHÔNG ghi snapshot")
        return None
    cards = r.get("cards") or []
    prev = prev_snapshot(key, date)
    ads, seen = [], set()
    for c in cards:
        lid = c.get("id")
        if not lid or lid in seen:
            continue
        a = parse_card(c, discover.unwrap)
        if domain:
            doms = {discover.norm_domain(l) for l in a["links"]}
            if not any(d == domain or d.endswith("." + domain) for d in doms if d) \
                    and domain not in a["text"].lower():
                continue  # ad của shop khác (FB tìm từ khoá rời rạc)
        seen.add(lid)
        landing = pick_landing(a["links"], domain)
        m = RE_HANDLE.search(landing)
        p = prev.get(lid) or {}
        ads.append({"library_id": lid, "first_seen": p.get("first_seen") or date, "start_date": a["start_date"],
                    "text": a["text"], "landing": landing, "product_handle": m.group(1).lower() if m else "",
                    "image": a["image"], "platforms": [], "page_name": a["page_name"],
                    "n_versions": a["n_versions"], "active": True})
    snap = {"key": key, "date": date,
            "fetched_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source": "Meta Ad Library (web)", "url": url, "n_cards": len(cards), "n_matched": len(ads), "ads": ads}
    out = DATA_DIR / key / f"{date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, out)
    n_new = sum(1 for a in ads if a["library_id"] not in prev)
    log(f"  {len(cards)} thẻ trên trang · {len(ads)} ad của {key} · mới so với lần trước {n_new if prev else '-'}")
    return snap


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Lấy ads đang chạy trên Meta Ad Library (qua Chrome 9230)")
    ap.add_argument("--watch", default=str(ROOT / "ads_watch.txt"))
    ap.add_argument("--only", default="", help="chỉ chạy các mục này, cách nhau dấu phẩy")
    ap.add_argument("--date", default="", help="ngày snapshot (mặc định hôm nay giờ VN)")
    ap.add_argument("--scroll", type=int, default=20, help="số lần cuộn tối đa mỗi trang")
    ap.add_argument("--delay", type=float, default=5.0, help="giây nghỉ giữa 2 mục")
    ap.add_argument("--spy-dir", default=str(ROOT.parent / "4-SPY"), help="thư mục 4-SPY (cdp.py, discover.py)")
    a = ap.parse_args()
    date = a.date or dt.datetime.now(VN).date().isoformat()
    cdp_mod, discover = load_spy(a.spy_dir)

    if a.only:
        entries = [x.strip() for x in a.only.split(",") if x.strip()]
    else:
        entries = []
        for line in Path(a.watch).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and line not in entries:
                entries.append(line)
    if not entries:
        sys.exit("Không có mục nào trong ads_watch.txt / --only")

    ok = 0
    try:
        with cdp_mod.Tab() as tab:   # 1 tab duy nhất, luôn đóng khi xong
            for i, e in enumerate(entries):
                if i:
                    time.sleep(a.delay)
                try:
                    if run_key(cdp_mod, discover, tab, e, date, a.scroll):
                        ok += 1
                except cdp_mod.ChromeChuaBat:
                    raise
                except Exception as ex:  # noqa: BLE001  lỗi 1 mục không làm chết cả lượt
                    log(f"  ! {e}: {type(ex).__name__}: {str(ex)[:200]}")
    except cdp_mod.ChromeChuaBat as ex:
        sys.exit(str(ex))
    log(f"\nXong ads: {ok}/{len(entries)} mục OK")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
