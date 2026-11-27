---
source_hash: d88e40f8d9a6
---
# Số dư thanh toán on-chain { #on-chain-payout-balances }

Mở **Payouts** (Thanh toán) để xem số dư tại một địa chỉ nhận thanh toán công khai. Bitcoin dùng
[mempool.space](https://mempool.space/docs/api/rest) và Kaspa dùng
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon và Solana dùng
các nút RPC công khai. CashPilot có thể đọc các địa chỉ này mà không cần khóa.

| Những gì bạn thấy | Ý nghĩa |
|---|---|
| Một số tiền | Trình khám phá đã báo một số dư. Số dư được báo bằng không sẽ hiện là không. Di chuột lên số tiền để xem nguồn. |
| **Pending** (Đang chờ) | Trên Bitcoin, trình khám phá thấy một thay đổi chưa được xác nhận. Dấu cộng nghĩa là tiền đang đến. Dấu trừ nghĩa là tiền đang được chi. Số tiền đã xác nhận được hiển thị riêng. |
| **Could not check** (Không kiểm tra được) | Trình khám phá không phản hồi hoặc gửi dữ liệu mà CashPilot không đọc được. |
| **Address not valid** (Địa chỉ không hợp lệ) | Địa chỉ không qua được bước kiểm tra định dạng. CashPilot đã bỏ qua yêu cầu. |
| **Private chain** (Chuỗi riêng tư) | Đọc số dư Monero cần khóa xem riêng tư (private view key) của bạn. Hãy kiểm tra số dư trong ví của bạn. CashPilot không bao giờ hỏi bạn khóa này. |
| Một dấu gạch ngang | Hàng này không có địa chỉ hoặc trình đọc, hoặc việc tra cứu đang tắt. Khi một thiết lập tắt việc tra cứu, hãy di chuột lên dấu gạch ngang để xem đó là thiết lập nào. |

Endpoint công khai của Kaspa báo một số dư duy nhất. Nó không cung cấp số tiền
đang chờ riêng.

Cột on-chain hiển thị số dư tại địa chỉ ngay lúc này. Nó có thể bao gồm
các khoản chuyển từ nguồn khác. Số dư chưa thanh toán của pool cho thấy những gì pool
vẫn đang giữ cho bạn. Một khoản thanh toán OCEAN qua Lightning không xuất hiện trong
số dư on-chain. Số dư cũng không cho bạn biết khoản chuyển nào đến từ
pool của bạn.

## Chọn nơi gửi yêu cầu tra cứu { #choose-where-the-lookup-goes }

Mỗi lần tra cứu chia sẻ địa chỉ nhận thanh toán công khai của bạn và IP của máy chủ UI với
trình khám phá. Trình khám phá có thể liên kết các địa chỉ bạn kiểm tra từ cùng một IP.

Đặt URL gốc trong môi trường của container UI nếu bạn tự chạy nút riêng.
Để trống biến để dùng giá trị mặc định. Đặt nó thành giá trị rỗng để tắt
việc tra cứu cho chuỗi đó.

Ví dụ, một file override Compose cho dịch vụ UI có thể chứa:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Dùng URL gốc của API Esplora hoặc Kaspa khi cấu hình Bitcoin hoặc Kaspa.
Endpoint Bitcoin cũng cung cấp độ khó của mạng và phần thưởng khối cho
[thu nhập dự kiến](fleet.md#running-costs) của một pool Bitcoin. Việc đọc đó cần một
backend mempool (API `/v1/mining` của nó); một máy chủ Esplora thuần chỉ trả lời
việc tra cứu số dư, và khi đó hàng của pool không hiển thị số tiền dự kiến.
Với Ethereum, Polygon và Solana, hãy đặt các biến tương ứng
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` hoặc
`CASHPILOT_ONCHAIN_URL_SOLANA` thành URL RPC của một nút. Dùng URL HTTP hoặc HTTPS
không có thông tin đăng nhập, chuỗi truy vấn hay fragment. Áp dụng thay đổi bằng cách
tạo lại container UI với môi trường mới.
