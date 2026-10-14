# collect/ — bộ thu dữ liệu spy đối thủ (LND Watch)

**Mô hình từ 14/10/2026 (anh Hoàng: "lấy tên shop và thống kê theo traffic / số ad, không cần cào hết sản phẩm"):
đơn vị = SHOP.** Không tải toàn bộ products.json, không lưu sản phẩm. Mỗi shop chỉ có vài số liệu cấp shop theo ngày.
Chỉ đọc dữ liệu công khai, không ghi gì lên store nào.

| Phần | Chạy ở đâu | Lịch | Lệnh |
|---|---|---|---|
| Shopify nhẹ (meta + 30 sp mới nhất) | GitHub Actions `.github/workflows/shopify.yml` | 23:00 UTC = 6:00 sáng VN | `run_cloud.py` → `build.py` → commit |
| Ads FB + Etsy + SimilarWeb | máy anh Hoàng, Task Scheduler (cần Chrome 9230) | 6:05 sáng | `run_local.ps1` |

## File
| File | Việc |
|---|---|
| `common.py` | đường dẫn, đọc/ghi JSON, ngày giờ VN, `parse_k` ("39.9K" → 39900). Biến môi trường `LND_DATA` = thư mục data khác (để thử trên bản sao). |
| `sync_shops.py` | (local) tạo / cập nhật `data/shops.json` từ `4-SPY\data\discover\shops.json` (Shopify: sp cùng ngách ≥ 20 hoặc ads ≥ 1) + `4-SPY\reports\<mới nhất>_etsy_discover.csv` (Etsy top 15 theo điểm) + `../shops_extra.txt`. Tích luỹ: không xoá shop cũ, cờ `active`. |
| `run_local.py` | (local, Chrome 9230) 3 phần: **ads** (Meta Ad Library), **etsy** (chỉ trang shop, `doc_shop_info` của 4-SPY), **traffic** (SimilarWeb ≤ 3 shop/ngày). Mở 1 tab mới / phần, đọc xong đóng, không đụng tab khác. |
| `run_cloud.py` | (cloud) mỗi shop Shopify: `/meta.json` + `/products.json?limit=30` (thêm `limit=250` chỉ khi cả 30 sp đều mới trong 30 ngày). Giá ép USD. |
| `shopify_lib.py` | session HTTP (nghỉ giữa request, retry 429, ép cookie USD). |
| `build.py` | gộp `raw/` + `traffic.json` → `daily/<ngày>.json`, `leaderboard.json`, `alerts.json`; kiểm cấu trúc (sai → mã thoát 1, không commit). Không dùng giờ hiện tại → chạy lại cho cùng kết quả. |
| `run_local.ps1` | (local, PowerShell 5.1) bật Chrome 9230 nếu chưa chạy → `git pull` → `sync_shops.py` → `run_local.py` → `build.py` → git commit / pull --rebase / build lại / push. Log `collect/logs/<ngày>.log`. |

## Dữ liệu (`data/`)
| File | Ai ghi | Nội dung |
|---|---|---|
| `shops.json` | sync_shops | `{"shops":[{id, platform, domain\|etsy, name, first_seen, added_on, sources, note, keywords, active}]}`; id Shopify = domain, Etsy = `etsy:<Tên>` |
| `raw/<ngày>/ads.json` | run_local | mỗi shop: `n_results` (số "~N results" thô), `approx`, `n_cards` (thẻ đã tải), `n_match` (thẻ có landing/text về đúng domain), `match_ratio`, `new_7d`, `oldest_start`, `pages`, 3 `samples` (text, landing, id), `at`, `src`, `secs` |
| `raw/<ngày>/etsy.json` | run_local | `sales, reviews, rating, admirers, listings, star_seller, location, since` |
| `raw/<ngày>/shopify.json` | run_cloud | `name, currency, n_products` (published_products_count), `new_7d, new_30d, capped, price_min, price_max, newest` |
| `traffic.json` | run_local | mỗi domain: `latest` (visits, change_pct, bounce_pct, pages_per_visit, duration, month, top_countries, source) + `history` theo tháng; `checks` = nhật ký từng lượt tra (đếm quota 3/ngày) |
| `daily/<ngày>.json` | build | mảng gọn 1 dòng / shop: khối `ads` / `shopify` / `etsy` (mỗi khối có `at`, `src`) |
| `leaderboard.json` | build | web đọc chính: `rows` mỗi shop (ads_active, ads_match, ads_est, ads_new_7d, oldest_ad_days, traffic_*, etsy_sales, etsy_sales_7d, new_products_7d/30d, price_min/max, `series_ads` / `series_etsy_sales` 30 ngày, `updated` từng nguồn, `traffic_next` = ngày tra dự kiến) |
| `alerts.json` | build | 90 ngày, mới trước: `ads_jump` (ads ước tăng ≥ 50 % và +5, hoặc +20), `ads_new_shop` (0 → có ads), `traffic_jump` (tháng tăng ≥ 30 %), `etsy_sales_spike` (sales/ngày ≥ 3 và > 2× TB 14 ngày, cần ≥ 3 khoảng trước), `new_shop` (shop thêm sau đợt đầu) |

Mỗi nguồn ghi file raw riêng → máy local và Actions không xung đột git; file tổng hợp luôn build lại sau pull.

## Cách tính số ads
FB Ad Library tìm theo từ khoá = domain, nên `~N results` gồm cả ad chỉ nhắc tới từ khoá (vd `the-woodland.store` ra 50.000).
`ads_est` (cột chính trên web): N ≤ số thẻ đã tải → đếm thẳng thẻ khớp; tỉ lệ khớp ≥ 50 % → `N × tỉ lệ`; tỉ lệ < 50 % → chỉ lấy số thẻ khớp (cận dưới, gắn nhãn "nhiễu").
Không cuộn hết trang: chỉ phần FB tải sẵn + ≤ 2 lần cuộn (~30–50 thẻ). `new_7d`, `oldest_start` tính trên phần đó.

## Chạy tay
```bash
python collect/sync_shops.py                              # in số shop Shopify / Etsy
python collect/run_local.py                               # ads + etsy + traffic (cần Chrome 9230)
python collect/run_local.py --ads-only --limit 5          # thử
python collect/run_local.py --etsy-only --only etsy:grossbale
python collect/run_local.py --traffic-only --traffic-max 1
python collect/run_local.py --reparse-traffic collect/logs/similarweb/<ngày>_<domain>.txt <domain> [--save]   # đọc lại trang đã lưu, không tốn lượt
python collect/run_cloud.py --limit 5
python collect/build.py
python web/build_pages.py                                 # sinh index.html gốc cho GitHub Pages (khi sửa web/index.html)
```
Chạy cả lượt local bằng tay (CÓ git push): `powershell -NoProfile -ExecutionPolicy Bypass -File collect\run_local.ps1`

## SimilarWeb — giới hạn 3 lượt/ngày, KHÔNG lách
- Không dùng incognito / xoá cookie / đổi IP. Hết lượt thì dừng, mai tra tiếp.
- `run_local.py` đếm lượt trong `traffic.json > checks` theo ngày; thấy "You've hit your search limit" (trạng thái `limit`) hoặc trang chặn thì dừng ngay.
- Hàng chờ: shop chưa tra trước, rồi shop tra lâu nhất; cùng hạng thì shop nhiều ads (ước) trước. Web hiện "chưa tra · dự kiến dd/mm".
- Text mỗi trang đã tra lưu ở `collect/logs/similarweb/` (không commit) để đọc lại nếu SimilarWeb đổi giao diện.
- Domain SimilarWeb không có dữ liệu (redirect về `/website/`) → `no_data`.

## Thêm / bớt shop
Sửa `../shops_extra.txt`: `domain.com` hoặc `etsy:TenShop` để thêm, `!` ở đầu để tắt; rồi `python collect/sync_shops.py`.
Danh sách tự cập nhật khi kho discover của 4-SPY có shop mới đạt ngưỡng.

## Cài lịch chạy local (Task Scheduler) — 6:05 sáng mỗi ngày
```
schtasks /Create /TN "LND-Watch-Local" /SC DAILY /ST 06:05 /IT /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"F:\CHU TAN\BUILD STORE SHOPIFY\5-SPY-WEB\collect\run_local.ps1\""
schtasks /Query /TN "LND-Watch-Local" /V /FO LIST
schtasks /Delete /TN "LND-Watch-Local" /F
```

## Ghi chú thay đổi
- **14/10/2026 — đổi mô hình sang đơn vị SHOP.** Bỏ `run_shopify.py` (catalog + rank), `run_ads.py` (cuộn hết Ad Library),
  `build_summary.py`, `check_schema.py`, `themes_rules.json`, `web/make_sample.py` + `web/sample-data.js`, `watch.txt` /
  `ads_watch.txt` / `etsy_watch.txt` (thay bằng `data/shops.json` + `shops_extra.txt`; ModWoodCo từ etsy_watch cũ chuyển sang
  shops_extra; cadenlane.com giữ trạng thái tắt). Ngừng ghi `data/shopify/<domain>/<ngày>.json`, `data/etsy/<shop>/…`,
  `data/ads/<key>/…`, `data/index.json`, `data/themes.json` — các file/thư mục cũ này xoá sau khi dữ liệu mới đã sinh
  (dữ liệu mới sinh xong 14/10; lệnh xoá: `git rm -r data/shopify data/etsy data/ads data/index.json data/themes.json
  collect/build_summary.py collect/check_schema.py collect/run_shopify.py collect/run_ads.py collect/themes_rules.json
  web/make_sample.py web/sample-data.js watch.txt ads_watch.txt etsy_watch.txt`). Lịch sử vẫn còn trong git.
  Web bỏ lưới design, bảng giá theo size, lịch mùa vụ, review (không còn dữ liệu sản phẩm).
- 14/10: SimilarWeb thử thật: woodemon.com (phiên chính tra tay), prints10.com OK; emmafy.com gặp "You've hit your search limit"
  → hôm đó dừng (emmafy vẫn nằm đầu hàng chờ).
- Cảnh báo cho phiên chính (vẫn đúng): `4-SPY\spy_shopify.py` dính giá VND khi chạy từ IP Việt Nam; cách sửa giống `shopify_lib.py`
  (cookie policy không lưu + ép cookie `cart_currency=USD`, `localization=US`).
