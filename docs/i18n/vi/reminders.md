---
source_hash: b4ae1a3ae496
---
# Tiền đang chờ: nhắc nhở trước khi bạn mất thu nhập { #money-waiting-reminders-before-you-lose-earnings }

Một số nhà cung cấp thu hồi tiền nếu nó nằm quá lâu. Một khoản số dư có thể hết hạn sau
nhiều tháng không hoạt động. Một khoảng thời gian nhận thưởng có thể đóng lại. Một nhà cung cấp có thể cấm
tài khoản, ngừng trả tiền hoặc đóng cửa trong khi số dư của bạn vẫn còn ở đó.
CashPilot đã đọc được phần lớn những gì nó cần để thấy trước các trường hợp này. Bảng
**Money waiting** (Tiền đang chờ) trên bảng điều khiển cho biết cần làm gì và trước khi nào, và
các kênh thông báo của bạn nhận một thông báo đẩy trước mỗi hạn chót.

CashPilot không bao giờ nhận thưởng hay rút tiền thay bạn. Mỗi lời nhắc liên kết tới
trang của chính nhà cung cấp, và bạn thao tác ở đó.

## Những gì nó nhắc bạn { #what-it-reminds-you-about }

**Quy tắc từ điều khoản của chính nhà cung cấp.** Mỗi quy tắc trích dẫn điều khoản hoặc
trang trợ giúp của nhà cung cấp, và ngày gần nhất có người đọc nó. Liên kết **Source** (Nguồn) trong
menu **More** (Thêm) của hàng sẽ mở trang đó.

| Dịch vụ | Lời nhắc | Khi nào |
|---|---|---|
| Grass | Nhận khoản USDC Stage 2 của bạn | Trước 22 Jan 2027. Grass giữ lại phần không được nhận. |
| MystNodes | Nhận phần thưởng của tháng trước | Trong vòng 30 ngày sau mỗi đợt phân phối hằng tháng |
| Honeygain | Rút số dư của bạn | 24 tháng sau khi nó lần đầu đạt $20 |
| Honeygain | Giữ một thiết bị đang chia sẻ, hoặc thực hiện một khoản thanh toán | 6 tháng sau lần hoạt động hoặc thanh toán gần nhất |
| Repocket | Giữ một thiết bị đang chia sẻ, hoặc rút tiền | 12 tháng sau lần hoạt động hoặc thanh toán gần nhất |
| Bitping | Rút số dư của bạn | 12 tháng sau lần rút tiền gần nhất |
| Salad | Kiếm thêm một ít Reward Points, hoặc tiêu số dư của bạn | 12 tháng sau lần gần nhất số dư tăng. Tiêu một phần số dư không đặt lại mốc này. |

**Rút tiền.** CashPilot báo cho bạn khi số dư đạt mức tối thiểu của nhà cung cấp.
Điều này áp dụng cho mọi dịch vụ mà nó thu thập dữ liệu, trừ các dịch vụ tự
thanh toán. Số dư cũng phải có giá trị ít nhất $5, để một nhà cung cấp
có mức tối thiểu 5 cent không làm phiền bạn ngay từ cent đầu tiên. Khi mức tối thiểu của nhà cung cấp
cao hơn, mức tối thiểu của nhà cung cấp được áp dụng. Khi CashPilot không thể
quy đổi mức tối thiểu hoặc số dư, nó không hiển thị gì. Nó không bao giờ đoán rằng
bạn có thể rút tiền.

**Thông tin đăng nhập hết hạn.** Bạn nhận một thông báo đẩy trước khi token hoặc cookie đã lưu hết hạn.
CashPilot dùng ngày hết hạn mà chính thông tin đăng nhập ghi. Khi nó không ghi
ngày nào, CashPilot dùng thời hạn thông thường của loại thông tin đăng nhập đó, tính
từ ngày bạn lưu nó. Chủ sở hữu đã thấy nó trong **Needs attention** (Cần chú ý),
với nút **Renew** (Gia hạn), nên bảng này không lặp lại nó. Chỉ chủ sở hữu mới nhận
lời nhắc về thông tin đăng nhập từ API, giống như việc kiểm tra sức khỏe thông tin đăng nhập.
Một thông tin đăng nhập bị nhà cung cấp từ chối đã có trong chuông thông báo và đã được đẩy đi,
nên nó không đẩy lại.

## Những dịch vụ được áp dụng { #which-services-it-covers }

Lời nhắc áp dụng cho dịch vụ bạn dùng: một dịch vụ đã triển khai, một dịch vụ bạn thiết lập
là bên ngoài trong **Settings** (Cài đặt), hoặc một ứng dụng mà điện thoại báo về. Một dịch vụ bạn đã gỡ
vẫn được tính khi nó còn số dư, vì các đồng hồ không hoạt động bắt đầu chạy
khi nó dừng. Dịch vụ tùy chỉnh và dịch vụ đã ngừng không có lời nhắc.

## Ngày và "or earlier" (hoặc sớm hơn) { #dates-and-or-earlier }

Các đồng hồ hoạt động đếm từ những gì CashPilot đã ghi nhận:

- lần gần nhất số dư tăng,
- khoản thanh toán gần nhất,
- hoặc lần đọc đầu tiên bằng hoặc vượt mức tối thiểu.

Đôi khi đồng hồ đã bắt đầu trước lần đọc đầu tiên của CashPilot. Khi đó hạn chót
thực tế có thể sớm hơn những gì CashPilot thấy được, và hàng sẽ ghi
"by 3 Oct 2027 or earlier" (trước 3 Oct 2027 hoặc sớm hơn).

CashPilot xóa lịch sử thu nhập sau 400 ngày, còn đồng hồ của Honeygain
chạy trong 730 ngày. Vì vậy CashPilot lưu điểm bắt đầu của mỗi đồng hồ ngay lần đầu
thấy nó, và giữ lại sau khi phần lịch sử phía sau đã bị xóa. Một khoản thanh toán đặt lại
đồng hồ, trừ khi nhà cung cấp chỉ tính việc kiếm tiền. Salad là một ví dụ: một
khoản thanh toán còn để lại số dư không đặt lại mốc 12 tháng của nó.

Một ngày cố định sẽ biến mất vào ngày sau khi nó qua, vì tiền đã mất.
Một đồng hồ quá hạn vẫn ở lại và cho biết nhà cung cấp có thể đã xóa sổ
khoản tiền đó. Nó ở lại cho đến khi bạn đánh dấu là xong hoặc tắt nó, hoặc cho đến khi một khoản thanh toán
đặt lại nó.

## Những gì bạn có thể làm với một lời nhắc { #what-you-can-do-with-a-reminder }

Chủ sở hữu và người chỉnh sửa thấy các nút. Người xem chỉ thấy lời nhắc. Chỉ chủ sở hữu
mới có thể thao tác với lời nhắc về thông tin đăng nhập.

- **Done** (Xong), hoặc **Requested** (Đã yêu cầu) với một lần rút tiền, ẩn lời nhắc này. Một khoảng
  thời gian hằng tháng sẽ quay lại vào tháng sau. Một lần rút tiền quay lại một lần sau 14 ngày nếu
  số dư vẫn còn, và hỏi khoản thanh toán đã đến chưa. Thời điểm đó
  nằm trong khoảng 60 ngày khiếu nại mà hầu hết nhà cung cấp cho phép.
- **Snooze** (Tạm hoãn) ẩn nó trong một ngày hoặc một tuần và giữ lại các thông báo đẩy của nó. Việc tạm hoãn không bao giờ
  kéo dài qua lần cảnh báo cuối cùng trước hạn chót.
- **Not for me** (Không dành cho tôi), trong menu **More** (Thêm), tắt một lời nhắc, hoặc mọi lời nhắc
  của một dịch vụ. Một ví dụ: Honeygain ở chế độ JumpTask, nơi số dư không đổi
  là bình thường. Các lời nhắc đã tắt được liệt kê ở cuối bảng, với
  **Unmute** (Bật lại).

Cả gia đình dùng chung các lựa chọn này. Khi một người đánh dấu một lời nhắc là xong, nó
xong với mọi người. Mỗi lựa chọn được ghi vào nhật ký kiểm tra cùng tên của
người đã thực hiện.

## Thông báo đẩy { #pushes }

Lời nhắc được gửi tới các kênh bạn đặt cho cảnh báo: ntfy, một webhook hoặc Telegram
([cấu hình](configuration.md)). Khi không đặt kênh nào, bảng này là nơi duy nhất
chúng hiển thị.

- Mỗi lần cảnh báo một thông báo đẩy. Ví dụ, Grass đẩy 60, 30, 7 và 1 ngày trước
  ngày của nó. Một lời nhắc được thấy lần đầu 5 ngày trước ngày của nó sẽ đẩy một lần, khi còn 5
  ngày.
- Thông báo đẩy chỉ được gửi trong khoảng 09:00 đến 21:00. CashPilot dùng múi giờ của
  chủ sở hữu đầu tiên trong **Settings** (Cài đặt), rồi đến `TZ` của container, rồi đến UTC. Một cảnh báo
  đến hạn trong đêm sẽ được gửi ở lần kiểm tra đầu tiên sau 09:00.
- Khi có hơn 3 thông báo đẩy đến hạn cùng lúc, bạn nhận một bản tóm tắt thay vào đó. Điều này
  xảy ra vào ngày bạn nâng cấp, khi mọi số dư vượt mức tối thiểu cùng xuất hiện
  một lúc.
- Một thông báo đẩy chứa dịch vụ, việc cần làm, những gì bạn sẽ mất, ngày và
  liên kết của nhà cung cấp. Nó không bao giờ chứa số dư, địa chỉ, id thiết bị hay
  tên worker. Các topic ntfy có thể là công khai.
- Payload của webhook chứa `kind: "obligation"`, để Home Assistant và các công cụ
  tương tự có thể định tuyến chúng.

## Dành cho người đóng góp danh mục { #for-catalog-contributors }

Các quy tắc nằm trong file YAML của mỗi dịch vụ, dưới `obligations:`.
`services/_schema.yml` mô tả các trường. Chỉ thêm một quy tắc khi
điều khoản hoặc tài liệu của chính nhà cung cấp nêu rõ nó, và khi CashPilot có thể thấy tín hiệu mà
quy tắc đó dựa vào. Liên kết của một quy tắc phải nằm trên tên miền của chính dịch vụ, vì các trang
nhận thưởng giả mạo tồn tại nhắm đúng vào những dịch vụ này. CI báo lỗi với một quy tắc không hợp lệ, và
với một quy tắc có ngày đã quá hơn 30 ngày.
