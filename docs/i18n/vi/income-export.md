---
source_hash: 38029ca1a5d6
---
# Xuất thu nhập để khai thuế { #income-export-for-taxes }

Mở **Payouts** (Thanh toán), tìm **Income for taxes** (Thu nhập để khai thuế), rồi chọn khoảng ngày và tiền tệ. **This year** (Năm nay) tính đến hôm nay, còn **Last year** (Năm ngoái) bao gồm năm dương lịch trước. Để trống các ngày để xuất toàn bộ lịch sử có sẵn tính đến hôm nay. CashPilot dùng ngày theo UTC và bao gồm cả hai đầu của khoảng.

CashPilot xóa các lần đọc thu nhập 400 ngày sau khi ghi nhận chúng. File CSV dùng phần lịch sử còn lại, nên một năm đã qua có thể chỉ chứa một phần thu nhập đã kiếm được hoặc đã tích lũy của năm đó.

## Chọn cơ sở kế toán { #choose-an-accounting-basis }

- **Cơ sở tiền mặt.** Dùng các hàng payout. Chúng ghi nhận số tiền mà dịch vụ đã thanh toán. CashPilot chỉ bao gồm các khoản thanh toán đã được xác nhận.
- **Cơ sở dồn tích.** Dùng các hàng earned và accrued. Hàng earned cho thấy số tiền bạn có thể rút theo điều khoản của dịch vụ. Hàng accrued cho thấy số tiền chưa thanh toán trong pool mà pool có thể không bao giờ trả.

Dùng một cơ sở cho cùng một khoản thu nhập. Cộng thêm các hàng payout vào các hàng earned và accrued có thể tính cùng một khoản tiền hai lần. Hãy kiểm tra cơ sở nào áp dụng cho hồ sơ khai thuế của bạn.

## Các cột CSV { #csv-columns }

| Cột | Ý nghĩa |
|---|---|
| date | Ngày UTC của lần đọc sau hoặc của khoản thanh toán. Một khoản thanh toán dùng ngày bạn đã nhập hoặc ngày CashPilot phát hiện ra nó. |
| period_start | Ngày UTC của lần đọc trước đó cho dịch vụ và nguồn này. Để trống với các khoản thanh toán. Một khoảng trống giữa các lần đọc nghĩa là số tiền bao gồm toàn bộ khoảng thời gian đó. |
| kind | earned, accrued hoặc payout. |
| service | ID dịch vụ trong CashPilot. |
| coin | Mã tiền tệ hoặc token như CashPilot đã ghi nhận. |
| amount | Số tiền bằng tiền tệ hoặc token đó. |
| usd_rate | Số đô la Mỹ cho mỗi đơn vị coin. |
| usd_value | Số tiền quy ra đô la Mỹ. |
| local_currency | Tiền pháp định bạn đã chọn cho bản xuất. |
| local_rate | Số đơn vị tiền tệ bạn chọn cho mỗi đô la Mỹ. |
| local_value | Số tiền quy ra tiền tệ bạn đã chọn. |
| method | Phương thức thanh toán, nếu có ghi nhận. |

Giá trị quy đổi để trống nghĩa là không có tỷ giá. Số tiền gốc vẫn có mặt. CashPilot bỏ qua các điểm nội bộ như điểm Grass trong các lần đọc thu nhập. Lần đọc đầu tiên của mỗi nguồn cung cấp một số dư đầu kỳ. Các hàng sau ghi nhận phần tăng thêm, nên file CSV có thể bắt đầu sau lần đọc cũ nhất trong khoảng đã chọn.

Nếu có nhiều hơn một nguồn đọc cùng một tài khoản, file CSV có thể tính khoản thu nhập đó nhiều hơn một lần.

Tỷ giá USD đến từ lần đọc sau hoặc từ bản ghi thanh toán. Khi CashPilot bổ sung giá cho một lần đọc, nó dùng giá của CoinGecko lúc 00:00 UTC của ngày đó. CashPilot dùng tỷ giá tham chiếu gần nhất của ECB vào hoặc trước ngày của hàng để quy đổi USD sang tiền tệ bạn đã chọn. Cách này bao gồm cả cuối tuần, ngày lễ và những ngày ECB chưa công bố tỷ giá. [Tỷ giá hằng ngày của Frankfurter](https://frankfurter.dev/v1/)

Frankfurter liệt kê các tiền tệ sau cho bản xuất. [Các tiền tệ được hỗ trợ](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR và ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD và ZAR.

Chọn USD nếu tiền tệ của bạn nằm ngoài danh sách đó hoặc Frankfurter không khả dụng.

## Nhập vào công cụ khác { #import-into-another-tool }

Chuyển file CSV sang định dạng của công cụ trước khi nhập. Trước tiên hãy chọn các hàng theo cơ sở kế toán của bạn. Bỏ qua các hàng payout của một ví mà công cụ đã đồng bộ.

### rotki { #rotki }

Dùng Generic Events với các tiêu đề cột sau.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Đặt Type là Income và Location là external. rotki cũng chấp nhận Deposit, Withdrawal, Loss, Spend và Staking khi các loại đó mô tả đúng một sự kiện. Ánh xạ coin sang Currency, amount sang Amount và service sang Description. Dùng mã định danh tài sản của rotki ở những chỗ nó khác với mã coin. Chuyển date thành dấu thời gian Unix theo UTC tính bằng mili giây. Để trống cả hai trường phí. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Dùng các cột bắt buộc của template Universal.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Định dạng Date là YYYY-MM-DD HH:mm:ss theo UTC. Đặt Received Amount từ amount và Received Currency từ coin. Để trống cả hai trường Sent. Với các giá trị đã biết, ánh xạ local_value và local_currency sang các cột tùy chọn Net Worth Amount và Net Worth Currency. Dùng cột Tag cho mining hoặc reward khi phù hợp. Description và TxHash là tùy chọn. [Template Universal của Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Chưa có tài khoản Koinly? Bạn có thể đăng ký tại đây: https://koinly.io/?via=FFF185D5. Đây là liên kết giới thiệu, và bạn không mất thêm chi phí nào.

### CoinTracking { #cointracking }

Chuyển các hàng thu nhập sang định dạng CSV thông thường của CoinTracking. Custom Importer yêu cầu các trường giao dịch ở cả hai phía, còn một hàng thu nhập chỉ có phía mua. [Yêu cầu của CoinTracking Custom Importer](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Đặt Type là Income hoặc Mining tùy trường hợp. Ánh xạ amount sang Buy Amount, coin sang Buy Currency và service sang Comment. Để trống các trường Sell. Định dạng Date là DD.MM.YYYY HH:MM:SS. Bản xuất cung cấp ngày UTC, nên hãy dùng 00:00:00 cho giờ. Dùng nhãn loại theo ngôn ngữ tài khoản của bạn. [Định dạng CSV thông thường của CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Chưa có tài khoản CoinTracking? Liên kết đăng ký này giảm 10% cho mọi gói trả phí: https://cointracking.info?ref=G962413. Đây là liên kết giới thiệu. CoinTracking trả cho dự án CashPilot 20% số tiền bạn trả, và bạn không phải trả thêm.
