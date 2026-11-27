---
source_hash: 7f8476aeb8b6
---
# Chuyển từ CashFactory { #moving-from-cashfactory }

CashPilot có thể đọc file `.env` của CashFactory và chuyển thông tin đăng nhập dịch vụ của bạn sang, để
bạn không phải nhập lại. Bạn kiểm tra mọi thứ trước khi CashPilot lưu.

## Trước khi bắt đầu { #before-you-start }

Bạn cần tài khoản chủ sở hữu CashPilot và ít nhất một worker CashPilot.

Hãy dừng CashFactory trên một máy trước khi bạn triển khai cùng các dịch vụ đó ở đó từ
CashPilot. Hai bản chạy sau cùng một kết nối chỉ kiếm tiền như một, và cùng một id thiết bị EarnApp
không được chạy hai lần. Chạy `docker compose down` trong thư mục
CashFactory.
[File compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
của nó cũng khởi động ba container mount Docker socket: Portainer (dòng 31)
và hai container Watchtower (dòng 141 và 264). Hãy chắc chắn rằng chúng cũng đã bị xóa: `docker ps`
không được liệt kê container nào trong số đó.

## Dùng file nào { #which-file-to-use }

Dùng file `.env` trong thư mục CashFactory của bạn, file bạn đã điền từ
[file mẫu](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Docker Compose đọc file đó, và nó khai triển `$` trong các giá trị không nằm trong
dấu nháy đơn. Một giá trị như vậy sẽ không giống những gì file hiển thị, nên CashPilot yêu cầu
bạn nhập lại thay vì đoán.

## Cách nhập { #how-to-import }

1. Mở **Settings** (Cài đặt), rồi **Import from another tool** (Nhập từ công cụ khác) (hoặc vào `/import`).
2. Thêm file `.env`, hoặc dán nội dung của nó. Để công cụ ở "Tell from the
   files" (Nhận biết từ file), hoặc chọn CashFactory.
3. Kiểm tra bảng. Đánh dấu các dịch vụ bạn muốn và điền mọi giá trị được đánh dấu
   là thiếu.
4. Nhấn **Save the ticked services** (Lưu các dịch vụ đã đánh dấu), rồi triển khai chúng tới các worker từ
   cùng trang đó.

## Những gì được chuyển sang { #what-comes-over }

| Ứng dụng CashFactory | Các khóa được đọc | Dịch vụ CashPilot | Những gì được chuyển sang |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | id thiết bị, để thiết bị đã liên kết của bạn tiếp tục kiếm tiền |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | email, mật khẩu |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | email, mật khẩu |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | email, khóa API |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id người dùng |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID thiết bị |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | khóa API |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | không có gì: không còn hoạt động |

Một giá trị vẫn hiển thị giá trị giữ chỗ của file mẫu (`<email>`, `sdk-node-<md5sum>`)
được coi là chưa đặt, và một dịch vụ không có gì ngoài các giá trị giữ chỗ sẽ bị bỏ khỏi
bảng.

## Những gì không bao giờ được chuyển sang { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot đặt tên mỗi thiết bị theo worker mà nó chạy trên đó, để
  hai worker không bao giờ báo cùng một tên. Các thiết bị cũ của bạn vẫn được liệt kê là
  ngoại tuyến trong bảng điều khiển của từng nhà cung cấp cho đến khi bạn xóa chúng ở đó.
- **Bitping.** CashFactory giữ thông tin đăng nhập Bitping trong một volume Docker, không phải trong
  `.env`, nên việc nhập không có gì để đọc và không hiển thị hàng Bitping nào. Hãy nhập
  thông tin đăng nhập trong biểu mẫu triển khai của Bitping.
- **Portainer và Watchtower.** CashPilot tự quản lý và cập nhật các
  container của nó.

## Theo dõi thu nhập { #earnings-tracking }

Với Honeygain và IPRoyal Pawns, thông tin đăng nhập của container cũng là thông tin đăng nhập tài khoản,
nên CashPilot cũng điền luôn thông tin thu thập thu nhập của chúng, trừ khi bạn đã đặt
chúng trong **Settings** (Cài đặt). Với mọi dịch vụ khác, hãy thêm thông tin đăng nhập để thu thập thu nhập trong
**Settings > Earnings collection** (Cài đặt > Thu thập thu nhập).

## An toàn { #safety }

- Không có gì trong file được chạy hay khai triển, và không địa chỉ nào trong đó được truy cập.
- File được đọc một lần và không được giữ lại. Những gì bạn lưu được lưu trữ mã hóa, như
  mọi thông tin đăng nhập khác trong CashPilot.
- Các bí mật chỉ hiển thị là "set" (đã đặt) trên trang.
- Các lần nhập đã lưu ở lại trên trang nhập cho đến khi bạn nhấn **Forget** (Quên), để bạn có thể
  triển khai chúng tới nhiều worker hơn sau này.
