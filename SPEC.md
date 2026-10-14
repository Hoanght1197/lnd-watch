# 5-SPY-WEB — Spy đối thủ dạng web (thiết kế 14/10/2026)

Mục tiêu: 1 trang web (Artifact claude.ai, link cố định, ai có link đều xem) hiển thị dữ liệu đối thủ
bảng tên gỗ (Shopify + Etsy + ads). Dữ liệu nằm trong repo GitHub public `Hoanght1197/lnd-watch`
(thư mục này). Trang web `fetch` thẳng JSON từ `https://raw.githubusercontent.com/Hoanght1197/lnd-watch/main/data/...`.

Nghiên cứu nền: `F:\CHU TAN\NGHIEN-CUU\2026-10-14-tool-spy\reports\Tool spy Shopify Etsy.md` (mục "Tool riêng: 7 màn hình").
Nguyên tắc: **chỉ số đếm được** (không ước tính doanh thu), mọi ô ghi nguồn + thời điểm quét, delta theo ngày/tuần.

## Ai kéo dữ liệu
| Phần | Chạy ở đâu | Cách | Lý do |
|---|---|---|---|
| Shopify (products.json, best-selling) | **GitHub Actions** cron 23:00 UTC (= 6h sáng VN) | `collect/run_shopify.py` → commit `data/` | HTTP công khai, không cần trình duyệt |
| Etsy (sales shop, listing) + FB Ad Library | **Máy anh Hoàng**, Task Scheduler 6:05 sáng | `collect/run_local.ps1` → gọi script trong `..\4-SPY` qua Chrome 9230 → commit + push | Etsy/FB chặn IP cloud, cần Chrome thật |
| Tổng hợp + cảnh báo + nhãn theme | Cả 2 nơi, sau khi thu | `collect/build_summary.py` | thuần tính toán |

Script lõi có sẵn (đọc, tái dùng, KHÔNG sửa): `F:\CHU TAN\BUILD STORE SHOPIFY\4-SPY\spy_shopify.py` (catalog + rank + diff),
`spy_etsy.py` (discover/watch qua `cdp.py`), `discover.py` (tìm shop + FB Ad Library). Snapshot mẫu thật:
`4-SPY\data\shopify\wondroot.com\2026-10-14.json`, `4-SPY\data\etsy\<shop>\2026-10-14.json`, `4-SPY\data\discover\shops.json`.

## Cấu trúc repo
```
collect/   run_shopify.py  run_local.ps1  build_summary.py  themes_rules.json  requirements.txt
.github/workflows/shopify.yml
data/      index.json  alerts.json  themes.json
           shopify/<domain>/<YYYY-MM-DD>.json   (snapshot thô, giống 4-SPY)
           shopify/<domain>/summary.json
           etsy/<shop>/<YYYY-MM-DD>.json + summary.json
           ads/<page_or_domain>/<YYYY-MM-DD>.json + summary.json
web/       index.html (+ assets nếu cần)  — trang Artifact
watch.txt  (shopify domains)   etsy_watch.txt (shop Etsy)   ads_watch.txt (domain/page FB)
```

## Schema JSON (web đọc đúng các file này)
### `data/index.json`
```json
{"updated_at":"2026-10-14T23:05:00Z",
 "shopify":[{"domain":"wondroot.com","name":"Wondroot","first_seen":"2026-10-14","last_ok":"2026-10-14","n_products":395}],
 "etsy":[{"shop":"StayNaturalStore","last_ok":"2026-10-14","sales":3479}],
 "ads":[{"key":"wondroot.com","last_ok":"2026-10-14","n_active":7}],
 "dates":["2026-10-13","2026-10-14"]}
```
### `data/shopify/<domain>/summary.json`
```json
{"domain":"wondroot.com","updated_at":"...","source":"products.json + collections/all?sort_by=best-selling",
 "series":[{"date":"2026-10-14","n_products":395,"n_niche":395,"n_new_7d":10,"price_by_size":{"10":34.99,"12":51.99,"24":142.99},"rank_source":"best-selling"}],
 "products":[{"handle":"...","title":"...","image":"https://cdn.shopify.com/...","url":"...",
   "published_at":"2026-09-01","price_min":34.99,"price_max":199.99,"price_by_size":{"10":34.99,"12":51.99},
   "rank":1,"rank_7d":3,"rank_30d":null,"tags":["floral","butterfly"],
   "theme":"floral","layout":"canh-ten","font":"script","is_niche":true}]}
```
`price_by_size`: khoá = số inch (chuỗi), lấy từ variant title có số. `theme/layout/font` do `build_summary.py` gán theo
`themes_rules.json` (regex trên title+tags: dinosaur, safari, floral, space, woodland, ocean, boho, farm, sports, western, bunny, bee, monogram…;
layout: chu-cai-canh | canh-ten | script-hoa | ten-2-dong | khac; font: script | block | mixed | khac). Không khớp → `"khac"`.

### `data/etsy/<shop>/summary.json`
```json
{"shop":"StayNaturalStore","url":"...","updated_at":"...","source":"etsy shop page + listing page (JSON-LD)",
 "info":{"sales":3479,"reviews":516,"rating":4.9,"admirers":980,"listings":134,"since":"2025","star_seller":true,"location":"United Kingdom","website":""},
 "series":[{"date":"2026-10-14","sales":3479,"reviews":516,"admirers":980,"listings":134}],
 "deltas":{"sales_1d":null,"sales_7d":null,"sales_30d":null,"reviews_7d":null},
 "listings":[{"id":"4364120977","title":"...","url":"...","image":"...","price":9.95,"currency":"USD",
   "reviews":237,"favorites":2787,"bestseller":true,"in_carts":"20+","listed_on":"2025-03-02",
   "favorites_7d":null,"reviews_7d":null,"theme":"floral","layout":"khac","font":"script"}]}
```
### `data/ads/<key>/summary.json`
```json
{"key":"wondroot.com","source":"Meta Ad Library (web)","updated_at":"...",
 "ads":[{"library_id":"123","first_seen":"2026-10-01","last_seen":"2026-10-14","days_running":14,"active":true,
   "text":"...","landing":"https://wondroot.com/products/...","product_handle":"...","image":"","platforms":["facebook","instagram"]}],
 "series":[{"date":"2026-10-14","n_active":7,"n_new":1}]}
```
### `data/alerts.json`
```json
[{"date":"2026-10-14","type":"new_product|price_change|rank_jump|new_ad|ad_long|etsy_sales_spike|new_listing|lost_bestseller|new_theme",
  "shop":"wondroot.com","platform":"shopify|etsy|ads","title":"...","url":"...","image":"...","detail":"rank 11 → 1","value":10}]
```
Giữ 90 ngày alert gần nhất, mới nhất trước.
### `data/themes.json`
`{"themes":["dinosaur","safari",...],"layouts":[...],"fonts":[...],"counts":{"dinosaur":{"shopify":12,"etsy":5}}}`

## 7 màn hình web (theo báo cáo nghiên cứu, thứ tự ưu tiên)
1. **Tổng quan / Watchlist**: bảng mọi shop (Shopify + Etsy): số SP ngách, SP mới 7/30 ngày, giá 12in / 24in, review + review mới/tuần (Etsy), ads đang chạy + ad lâu nhất, sales/ngày (Etsy), lần quét cuối. Click shop → trang chi tiết. Bên phải: feed cảnh báo từ `alerts.json` lọc theo loại/ngày.
2. **Sales Etsy theo ngày**: chart đường nhiều shop (sales 1d/7d/30d), bảng xếp hạng theo sales 7d; nhãn "số thật từ Etsy".
3. **Lưới design theo theme**: grid ảnh thumbnail lớn (Shopify products + Etsy listings) lọc theme/layout/font/shop/giá; sort theo rank, review mới, favorites, ngày đăng; ô "mẫu của mình" (từ `data/mine.json` nếu có, 16 mẫu Little Nest) để so cạnh. Đây là màn hình khác biệt, làm đẹp.
4. **Bảng giá theo size**: ma trận shop × size (8,10,12,14,16,18,20,24,30 in) giá trung vị, cột $/inch, free-ship threshold nếu lấy được; highlight đổi giá so với 7 ngày trước.
5. **Ads board**: card ads (text, ngày bắt đầu, days_running, sản phẩm đích), lọc 3/7/15/30 ngày và "chạy > 14 ngày" (= có lời), nhóm theo shop và theo theme.
6. **Review mining** (v1 đơn giản): từ review text Etsy nếu có trong snapshot (hiện chỉ có số), hiển thị số review theo ngày + placeholder "sẽ bổ sung text".
7. **Lịch mùa vụ**: timeline ngày đăng sản phẩm của từng shop theo tuần (từ `published_at`), đánh dấu tag mùa (christmas, halloween, easter, valentine, back to school) và mốc gợi ý (15/8–15/9 đăng hàng Noel).

Chung: tiếng Việt, mobile ok, dark/light, mỗi số liệu có tooltip "nguồn · lần quét"; nút tải CSV cho mọi bảng; không ước tính doanh thu.
Dữ liệu đọc qua `fetch(RAW_BASE + path)` với `RAW_BASE` là hằng ở đầu file (đổi được), cache-bust `?t=<phút>`.

## Quy ước
- Python 3.11+, chỉ stdlib + `requests` (+ `websocket-client` phần local). Ghi JSON `ensure_ascii=False, indent=1`, mọi ngày ISO `YYYY-MM-DD`, thời gian UTC.
- Script phải chạy được cả trên Linux (Actions) và Windows (local). Không hard-code đường dẫn `F:\` trong phần chạy trên cloud; phần local mới được tham chiếu `..\4-SPY`.
- Không ghi gì lên store Shopify; chỉ đọc dữ liệu công khai.
