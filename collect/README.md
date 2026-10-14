# collect/ — bộ thu dữ liệu spy đối thủ (5-SPY-WEB)

Thu dữ liệu đối thủ bảng tên gỗ → `data/` → trang web đọc thẳng qua raw.githubusercontent.com.
Schema các file JSON nằm trong `../SPEC.md`. Chỉ đọc dữ liệu công khai, không ghi gì lên store nào.

| Phần | Chạy ở đâu | Lịch | Lệnh |
|---|---|---|---|
| Shopify (catalog + rank bestseller) | GitHub Actions `.github/workflows/shopify.yml` | 23:00 UTC = 6:00 sáng VN | `run_shopify.py` → `build_summary.py` → `check_schema.py` → commit |
| Etsy + FB Ad Library | máy anh Hoàng, Task Scheduler | 6:05 sáng | `run_local.ps1` |

## File
| File | Việc |
|---|---|
| `run_shopify.py` | tải `/products.json` + `/collections/all?sort_by=best-selling` cho mỗi domain trong `../watch.txt` → `data/shopify/<domain>/<ngày>.json` (format giống snapshot 4-SPY, thêm `shop_name`). Nghỉ 1,5 s giữa request, retry 429, lỗi 1 shop không dừng cả lượt. |
| `shopify_lib.py` | hàm lõi CHÉP từ `4-SPY/spy_shopify.py` (cloud không có 4-SPY). Sửa bản gốc thì chép lại. |
| `run_ads.py` | (chỉ local) Meta Ad Library qua Chrome 9230 cho mỗi dòng `../ads_watch.txt` → `data/ads/<key>/<ngày>.json`. Dùng `cdp.Tab`, `unwrap`, `norm_domain` của `../4-SPY` (import, không sửa). Tab tự đóng. |
| `run_local.ps1` | (chỉ local, PowerShell 5.1) bật Chrome 9230 nếu chưa chạy → `spy_etsy.py watch` → `run_ads.py` → chép snapshot Etsy từ `4-SPY\data\etsy` → build → kiểm schema → git commit / pull --rebase / build lại / push. Log `collect/logs/<ngày>.log`. |
| `build_summary.py` | từ mọi snapshot sinh `summary.json` mỗi shop, `data/index.json`, `data/alerts.json`, `data/themes.json`; ghi gọn mọi snapshot thô (JSON không thụt dòng; summary/index/alerts/themes vẫn indent=1), xoá snapshot thô Shopify cũ hơn 30 ngày (`--no-prune` để giữ). Chạy lại bao nhiêu lần cũng ra cùng kết quả. |
| `themes_rules.json` | regex gán `theme` / `layout` / `font` (sửa xong chạy lại `build_summary.py`). |
| `check_schema.py` | kiểm field bắt buộc theo SPEC; mã thoát 1 nếu sai (Actions và run_local sẽ KHÔNG commit). |
| `requirements.txt` | `requests` (phần local cần thêm `websocket-client`, máy anh đã có sẵn cho 4-SPY). |

## Chạy tay
```bash
# Shopify (chạy được cả Windows lẫn Linux)
python collect/run_shopify.py                                  # mọi domain trong watch.txt
python collect/run_shopify.py --only wondroot.com,woodemon.com --delay 2
python collect/run_shopify.py --date 2026-10-14                # ép ngày (mặc định = hôm nay giờ VN)
# --rank-pages 25 (số trang best-selling tối đa), --retry-wait 180 (nghỉ rồi chạy lại shop lỗi; 0 = không), --no-rank

# Ads (cần Chrome 9230 đang chạy)
python collect/run_ads.py                                      # mọi dòng trong ads_watch.txt
python collect/run_ads.py --only wondroot.com --scroll 20

# Tổng hợp + kiểm
python collect/build_summary.py
python collect/check_schema.py
```
Etsy: `python ..\4-SPY\spy_etsy.py watch --shops <đường dẫn>\etsy_watch.txt --max-pages 80` (ghi vào `4-SPY\data\etsy`),
`run_local.ps1` tự chép sang `data/etsy/`.

Chạy cả lượt local bằng tay (CÓ git push): `powershell -NoProfile -ExecutionPolicy Bypass -File collect\run_local.ps1`

## Thêm / bớt shop
- Shopify: thêm 1 dòng domain (không `https://`, không `www.`) vào `../watch.txt`. Lần chạy Actions sau sẽ có.
- Etsy: thêm tên shop vào `../etsy_watch.txt` (≤ 10 shop/ngày cho khỏi bị chặn; `--max-pages 80` trong run_local đủ ~4–5 shop).
- Ads: thêm vào `../ads_watch.txt` 1 domain (tìm ads có landing về domain đó) hoặc `page:<page_id>` (mọi ads của 1 Facebook page; lưu với key `page-<id>`).
- Dòng bắt đầu `#` là ghi chú. Bỏ shop: xoá dòng; dữ liệu cũ vẫn nằm trong `data/` (xoá thư mục nếu muốn ẩn khỏi web).

## Cài lịch chạy local (Task Scheduler) — 6:05 sáng mỗi ngày
Chạy trong PowerShell/cmd của anh (cần đăng nhập Windows lúc đó vì Etsy/FB cần Chrome thật):
```
schtasks /Create /TN "LND-Watch-Local" /SC DAILY /ST 06:05 /IT /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"F:\CHU TAN\BUILD STORE SHOPIFY\5-SPY-WEB\collect\run_local.ps1\""
```
Xem / chạy thử / gỡ:
```
schtasks /Query /TN "LND-Watch-Local" /V /FO LIST
schtasks /Run /TN "LND-Watch-Local"
schtasks /Delete /TN "LND-Watch-Local" /F
```
Trước lần đầu: thư mục `5-SPY-WEB` phải là repo git có remote `origin` = `Hoanght1197/lnd-watch` và máy đã đăng nhập git (push được).

## Ghi chú dữ liệu
- Ngày snapshot = ngày giờ VN. Thời gian trong summary là UTC (`...Z`); thời gian "trơn" trong snapshot 4-SPY coi là giờ VN.
- `rank` = thứ tự Shopify tự xếp theo bán chạy (không phải số đơn). `rank_7d` / `rank_30d` = rank ở snapshot cách 7 / 30 ngày (cho lệch 3 / 7 ngày), chưa đủ lịch sử thì `null`.
- `price_by_size` lấy số inch từ variant title (`12 in`, `12"`, `Small (7 inch)`; `6.1 × 8.5 in` → cạnh lớn). Series dùng giá TRUNG VỊ của sp ngách.
- Shopify giới hạn tốc độ theo IP cho MỌI shop: bị 429 ở 1 shop thì shop sau cũng bị → `run_shopify.py` nghỉ tăng dần 15/30/60/90 s, cuối lượt nghỉ 180 s rồi chạy lại các shop lỗi (thử 14/10 từ máy local: 7 shop đều lấy được sau vòng chạy lại).
- Giá Shopify ép USD (cookie `cart_currency=USD`, `localization=US`, không lưu cookie shop trả về); không ép thì từ IP VN có shop trả VND.
- `is_niche` = regex giống `NICHE_RE` trong `4-SPY/discover.py` (bản 14/10).
- Etsy: giá theo tiền tệ lúc quét (Chrome VN → VND); thêm `price_usd` quy đổi theo tỉ giá cố định `FX_USD` trong `build_summary.py` (gần đúng, chỉ để so sánh). `favorites_7d`, `reviews_7d`, `deltas.*` cần snapshot cũ cách 1/7/30 ngày.
- Ads: `first_seen` giữ từ snapshot trước; `start_date` = "Started running on" của FB; `days_running` tính từ `start_date`. Ảnh ads là link CDN có hạn của Facebook, vài ngày sau có thể chết. `platforms` chưa đọc được (FB hiện bằng icon) → `[]`.
- Alerts tính lại từ snapshot mỗi lần build (giữ 90 ngày; phần cũ hơn 30 ngày lấy từ alerts.json cũ vì thô Shopify đã xoá), tối đa 40 alert / (ngày, loại, shop). Loại: `new_product`, `price_change`, `rank_jump` (lên ≥ 5 bậc và vào top 20, hoặc mới vào top 20), `new_theme`, `new_listing` (id Etsy lớn hơn mọi id cũ), `lost_bestseller`, `etsy_sales_spike` (sales/ngày ≥ 5 và ≥ 2× trung bình các lần trước, cần ≥ 2 khoảng trước), `new_ad`, `ad_long` (vượt 14 ngày). Url alert ads = trang ad trên Ad Library.

## Ghi chú thay đổi
- 14/10/2026: bỏ `cadenlane.com` khỏi watch.txt và xoá `data/shopify/cadenlane.com/` — shop quần áo em bé, chỉ 43 sp ngách / 1246 sp.
- CẢNH BÁO cho phiên chính: `4-SPY\spy_shopify.py` dính lỗi giá VND khi chạy từ IP Việt Nam (vd carpenter-farmhouse.com ra 263000 thay vì $10, do header Accept-Language + cookie `cart_currency=VND`/`localization=VN` shop đặt). Cách sửa giống `collect/shopify_lib.py`: trong `Http.__init__` thêm `self.s.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))` và mỗi `self.s.get(...)` truyền `cookies={"cart_currency": "USD", "localization": "US"}`. Snapshot cũ của 4-SPY có thể đã lẫn giá VND.
