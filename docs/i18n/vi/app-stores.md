---
source_hash: e99e2c0c80bb
---
# Kho ứng dụng { #app-stores }

Bạn có thể cài CashPilot từ kho ứng dụng của một số hệ điều hành cho máy chủ gia đình.
Mỗi gói cài bảng điều khiển (`drumsergio/cashpilot`) và worker
(`drumsergio/cashpilot-worker`), thành phần khởi động và dừng các container
của dịch vụ. Chỉ các gói CasaOS và Runtipi trong kho mã này mới cài thêm
Docker socket proxy từ `docker-compose.yml`, nên worker của chúng
không bao giờ giữ Docker socket gốc. Các template Unraid, ứng dụng TrueNAS và
gói trong pull request đang mở tới kho ứng dụng CasaOS vẫn mount Docker
socket trực tiếp vào worker.

Dù bạn dùng kho nào, hãy giữ bảng điều khiển trong LAN hoặc VPN của bạn. Nó có thể ra lệnh cho
worker, và worker điều khiển Docker trên máy chủ. Ở nơi worker tự giữ
socket, điều đó tương đương quyền root trên máy chủ.

## Đang có hôm nay { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Tìm **CashPilot** trong thẻ Apps và cài cả hai template:
`cashpilot` (bảng điều khiển) và `cashpilot-worker`. Đặt cùng một
`CASHPILOT_API_KEY` cho cả hai.

Các template đến từ https://github.com/GeiserX/docker-templates và theo
tag image `latest`, nên người dùng Community Applications nhận mỗi bản phát hành
mà không cần thay đổi template.

### TrueNAS SCALE { #truenas-scale }

CashPilot có trong train **community** của TrueNAS. Mở Apps, rồi Discover Apps,
và tìm **CashPilot**.

Định nghĩa ứng dụng được duy trì tại
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot và ghim
một digest image chính xác. Các bot của chính TrueNAS chuyển nó sang các bản phát hành mới, nên nó có thể
chậm vài bản so với CashPilot mới nhất.

## Đang chờ duyệt { #waiting-for-review }

### CasaOS { #casaos }

Một pull request tới kho ứng dụng CasaOS đang mở:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Cho đến khi nó được merge, hãy cài nó như một ứng dụng tùy chỉnh: trong CasaOS chọn App Store,
rồi Custom Install, rồi Import, và dán nội dung của
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Nó cần CasaOS 0.4.5 trở lên: từ bản phát hành đó, trình quản lý ứng dụng của nó được xây dựng trên
Docker Compose 2.23, phiên bản đọc được chính sách của socket proxy từ file.
Các bản cũ hơn bỏ qua chính sách đó, và khi đó worker không thể kết nối tới Docker.

File đó ghim một bản phát hành chính xác. Trước khi nhập nó, hãy đặt cả hai tag image
(`drumsergio/cashpilot` và `drumsergio/cashpilot-worker`) thành bản phát hành
mới nhất từ https://github.com/GeiserX/CashPilot/releases. Chính sách proxy
trong file theo `main`; nếu trang trạng thái của worker báo chính sách của nó
đã lỗi thời, hãy nhập lại file.

## Đã chuẩn bị, chưa gửi { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Gói đã sẵn sàng tại
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
nhưng chưa có trong kho ứng dụng Runtipi. Để dùng nó ngay bây giờ, hãy thêm nó vào một kho ứng dụng
tùy chỉnh do bạn quản lý, theo tài liệu của Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## Không cung cấp { #not-offered }

Umbrel cần một thiết kế worker khác, vì các ứng dụng Umbrel kết nối tới Docker
qua một container Docker-in-Docker thay vì socket của máy chủ. Chúng tôi chưa
thử nghiệm điều đó, nên hiện chưa có gói Umbrel.

Với bất kỳ hệ thống nào khác, hãy dùng `docker-compose.yml` từ kho mã, như trong
[Bắt đầu](getting-started.md).
