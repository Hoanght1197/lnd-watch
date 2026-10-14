# 5-SPY-WEB — LND Watch: spy đối thủ bảng tên gỗ trẻ em (mô hình SHOP, 14/10/2026)

Yêu cầu anh Hoàng 14/10: **"lấy tên shop và thống kê theo traffic / số ad, không cần cào hết sản phẩm về"**.
Đơn vị = SHOP. Không lưu sản phẩm. Web (GitHub Pages của repo public `Hoanght1197/lnd-watch`) đọc `data/`.
Bản cũ (catalog sản phẩm, lưới design, bảng giá theo size, lịch mùa vụ) đã bỏ — xem lịch sử git.

## Nguồn số liệu
| # | Số liệu | Ở đâu chạy | Cách | Tần suất |
|---|---|---|---|---|
| 1 | Số ads Facebook đang chạy | máy local, Chrome 9230 | Meta Ad Library tìm theo domain (country=ALL): đọc "~N results" + phần thẻ đã tải (≤ 2 lần cuộn): thẻ khớp landing, ad mới 7 ngày, ad lâu nhất, page, 3 mẫu | mọi shop Shopify, hằng ngày (~5 s/shop) |
| 2 | Traffic SimilarWeb | máy local, Chrome 9230 | trang `similarweb.com/website/<domain>/`: visits tháng, % đổi, bounce, trang/lượt, thời lượng, top nước | **≤ 3 shop/ngày** (giới hạn miễn phí, không lách), hàng chờ |
| 3 | Etsy | máy local, Chrome 9230 | CHỈ trang shop: tổng sales, review, rating, admirers, số listing; chênh sales/ngày = số đơn thật | 15–16 shop, hằng ngày |
| 4 | Shopify nhẹ | GitHub Actions 23:00 UTC | `/meta.json` + `/products.json?limit=30`: tổng sp, sp đăng 7/30 ngày, giá min/max 30 sp mới (USD) | mọi shop Shopify, hằng ngày |

Danh sách shop: `data/shops.json` do `collect/sync_shops.py` sinh từ kho discover của `..\4-SPY` + `shops_extra.txt`.

## File dữ liệu
Chi tiết schema: `collect/README.md`. Tóm tắt:
`shops.json` · `raw/<ngày>/{ads,etsy,shopify}.json` · `traffic.json` → (`build.py`) → `daily/<ngày>.json` · `leaderboard.json` · `alerts.json`.

## Web (`web/index.html` → `python web/build_pages.py` → `index.html` gốc)
1. **Xếp hạng shop** (màn chính): bảng sort theo Ads đang chạy (mặc định) / Ads mới 7 ngày / Traffic tháng / % đổi traffic / Sales Etsy 7 ngày / SP mới 30 ngày;
   sparkline ads 30 ngày; lọc Shopify/Etsy; tìm tên; tooltip nguồn + lần quét mọi số; traffic chưa tra hiện "chưa tra · dự kiến dd/mm"; Tải CSV.
   Bấm shop → panel: chart ads theo ngày, traffic theo tháng + top nước, 3 mẫu ads (text, landing, link Ad Library), link shop.
2. **Cảnh báo**: feed lọc theo loại.
3. **Sales Etsy**: chart nhiều shop (sales/ngày hoặc tổng) + bảng xếp hạng sales 7 ngày.

## Quy ước
- Python 3.11+, stdlib + `requests` (+ `websocket-client` phần local qua `..\4-SPY\cdp.py`). Ngày dữ liệu = ngày giờ VN, thời gian UTC.
- Phần cloud không tham chiếu `F:\`; phần local mới dùng `..\4-SPY` (import, không sửa).
- Không ghi gì lên store; chỉ đọc dữ liệu công khai. Chrome 9230 chỉ mở tab mới, đọc, đóng.
- Không ước tính doanh thu. Traffic là số ước của SimilarWeb (ghi rõ trên web).
