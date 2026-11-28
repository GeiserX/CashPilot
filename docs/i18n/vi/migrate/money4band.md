---
source_hash: 5a764f1d0f5a
---
# Chuyển từ money4band { #moving-from-money4band }

CashPilot có thể đọc cấu hình của money4band và chuyển thông tin đăng nhập dịch vụ của bạn sang, để
bạn không phải nhập lại. Bạn kiểm tra mọi thứ trước khi CashPilot lưu.

## Trước khi bắt đầu { #before-you-start }

Bạn cần tài khoản chủ sở hữu CashPilot và ít nhất một worker CashPilot trên
máy đang chạy money4band, hoặc trên một máy khác.

Hãy dừng money4band trên một máy trước khi bạn triển khai cùng các dịch vụ đó ở đó từ
CashPilot. Hai bản chạy sau cùng một kết nối chỉ kiếm tiền như một, và cùng một id thiết bị EarnApp
hoặc ProxyRack không được chạy hai lần. Dùng **Stop apps stack** trong
menu của money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
hoặc chạy `docker compose down` trong thư mục của nó. Nếu bạn đã thiết lập thêm các phiên bản
proxy, hãy dừng từng phiên bản đó nữa.

## Dùng file nào { #which-file-to-use }

Dùng `config/user-config.json` trong thư mục money4band của bạn. Cách đưa nó sang
CashPilot tùy thuộc vào phiên bản money4band của bạn.

Trong money4band 4.x, money4band ghi file đó
khi bạn chạy **Setup Apps**, và nó chứa đúng những gì bạn đã nhập. File `.env`
bên cạnh được tạo ra từ file đó và cũng dùng được, cũng như file `.env`
sửa tay của money4band 3.x. Cả hai chỉ nằm trên đĩa của bạn:
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
của money4band liệt kê chúng.

money4band 5.0 mã hóa `config/user-config.json` trên đĩa
([ghi chú bảo mật](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)),
và xóa file `.env` của nó sau mỗi lần khởi động
([env builder](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot không đọc được file đã mã hóa. Trong thư mục money4band của bạn, chạy
lệnh `config edit` của nó. Với file binary bản phát hành, dùng file dành cho hệ thống của bạn, ví dụ `./Money4Band-linux-amd64 config edit`, hoặc `.\Money4Band-windows-amd64.exe config edit` trên Windows.
Khi chạy từ mã nguồn, chạy `python run.py config edit`.
Lệnh này chạy money4band qua uv, hoặc qua một môi trường pip khi không có uv ([run.py](https://github.com/MRColorR/money4band/blob/eebbdd410131e4b0fd4c9f9d49f84dc60e6a0e3d/run.py#L48-L69)).
Lệnh `config edit` mở file đã giải mã trong trình soạn thảo của bạn ([tài liệu tham khảo CLI](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Sao chép toàn bộ nội dung của nó, dán vào trang **Import from another tool** (Nhập từ công cụ khác), rồi đóng trình soạn thảo.

Nên dùng file JSON. Trong một `.env`, Docker Compose khai triển `$` trong các giá trị
không có dấu ngoặc kép, nên một mật khẩu có `$` sẽ không giống những gì file hiển thị. CashPilot
không đoán: nó yêu cầu bạn nhập lại giá trị đó.

## Cách nhập { #how-to-import }

1. Mở **Settings** (Cài đặt), rồi **Import from another tool** (Nhập từ công cụ khác) (hoặc vào `/import`).
2. Thêm `user-config.json`, hoặc dán nội dung của nó. Để công cụ ở "Tell from the
   files" (Nhận biết từ file), hoặc chọn money4band.
3. Kiểm tra bảng. Đánh dấu các dịch vụ bạn muốn và điền mọi giá trị được đánh dấu
   là thiếu.
4. Nhấn **Save the ticked services** (Lưu các dịch vụ đã đánh dấu), rồi triển khai chúng tới các worker từ
   cùng trang đó.

## Những gì được chuyển sang { #what-comes-over }

Tên trường đến từ
[template user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
của money4band và các tên trong `.env` mà
[trình tạo](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
của nó ghi ra (`<APP>_<FLAG>`, ví dụ `REPOCKET_APIKEY`). money4band 5.0 giữ
nguyên các tên trường đó trong
[danh mục ứng dụng](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported) của nó.

| Ứng dụng money4band | Dịch vụ CashPilot | Những gì được chuyển sang |
|---|---|---|
| `earnapp` | EarnApp | id thiết bị (`uuid`), để thiết bị đã liên kết của bạn tiếp tục kiếm tiền |
| `honeygain` | Honeygain | email, mật khẩu |
| `iproyalpawns` | IPRoyal Pawns | email, mật khẩu |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | token |
| `repocket` | Repocket | email, khóa API |
| `earnfm` | Earn.fm | khóa API |
| `proxyrack` | ProxyRack | khóa API, UUID thiết bị |
| `proxylite` | ProxyLite | id người dùng |
| `bitping` | Bitping | email, mật khẩu |
| `mystnode` | Mysterium | được bật; xem ghi chú về Mysterium bên dưới |

Một ứng dụng bạn đã tắt trong money4band sẽ hiện ra mà không được đánh dấu. Một ứng dụng đang tắt và
không chứa gì ngoài các giá trị giữ chỗ của template (`yourHONEYGAINMail`) và danh sách
cổng sẽ bị bỏ qua, nên một `user-config.json` chưa chỉnh sửa sẽ cho ra một bảng trống.

Các ứng dụng sau được liệt kê nhưng không được chuyển sang:

| Ứng dụng money4band | Lý do |
|---|---|
| `proxybase` | money4band chạy client cũ của ProxyBase với một id người dùng. CashPilot chạy client hiện tại, client này cần Access Token từ proxybase.org. |
| `urnetwork` | money4band giữ một token phiên. CashPilot đăng nhập URnetwork bằng email và mật khẩu của bạn. |
| `grass` | Grass chạy dưới dạng tiện ích trình duyệt. CashPilot chỉ theo dõi nó, bằng access token từ bảng điều khiển Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot theo dõi các ứng dụng này, nhưng không có container nào để triển khai. |
| `packetshare`, `peer2profit`, `speedshare` | Không còn hoạt động. |

Mọi ứng dụng khác được liệt kê là "CashPilot has no such service" (CashPilot không có dịch vụ này).

## Những gì không bao giờ được chuyển sang { #what-never-comes-over }

- **Tên thiết bị.** CashPilot đặt tên mỗi thiết bị theo worker mà nó chạy trên đó, để
  hai worker không bao giờ báo cùng một tên. Các thiết bị cũ của bạn vẫn được liệt kê là
  ngoại tuyến trong bảng điều khiển của từng nhà cung cấp cho đến khi bạn xóa chúng ở đó.
- **Proxy.** Thêm từng proxy trong mục **Proxies** (Proxy) của trang **Fleet** (Đội máy), rồi chạy
  các bản sao dịch vụ của bạn qua nó; tự việc thêm một proxy không khởi động gì cả.
  Việc lưu một lần nhập cũng không khởi động gì. Một bản sao qua proxy cần cùng dịch vụ đó
  đã được triển khai trên worker trước, và việc triển khai sẽ chạy nó trên kết nối riêng của worker,
  nên một dịch vụ không bao giờ được dùng kết nối đó thì nên để
  không đánh dấu. Xem [Bản sao qua proxy](../proxies.md).
- **Watchtower và thông báo.** CashPilot tự cập nhật các container của nó.
- **Bảng điều khiển của money4band và các cổng của nó.**

## Theo dõi thu nhập { #earnings-tracking }

Với Honeygain, IPRoyal Pawns và Bitping, thông tin đăng nhập của container cũng là
thông tin đăng nhập tài khoản, nên CashPilot cũng điền luôn thông tin thu thập thu nhập của chúng, trừ khi bạn
đã đặt chúng trong **Settings** (Cài đặt). Với mọi dịch vụ khác, hãy thêm thông tin đăng nhập để thu thập thu nhập
trong **Settings > Earnings collection** (Cài đặt > Thu thập thu nhập).

## Mysterium { #mysterium }

Việc nhập sẽ bật Mysterium, nhưng CashPilot khởi động một nút mới với một
danh tính mới. Keystore của nút cũ và mọi khoản thu nhập chưa thanh toán vẫn nằm trong
thư mục `.data/mysterium-node` của money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Hãy thanh toán chúng trước, hoặc làm theo
[hướng dẫn Mysterium](../guides/mysterium.md) để chuyển danh tính sang.

Một `.env` của 3.x không thể cho biết bạn có chạy Mysterium hay không: template của nó luôn
liệt kê cổng của bảng điều khiển. Từ một file 3.x, Mysterium không được nhập, nên hãy thêm
nó từ danh mục nếu bạn đã chạy nó.

## An toàn { #safety }

- Không có gì trong file được chạy hay khai triển, và không địa chỉ nào trong đó được truy cập.
- File được đọc một lần và không được giữ lại. Những gì bạn lưu được lưu trữ mã hóa, như
  mọi thông tin đăng nhập khác trong CashPilot.
- Các bí mật chỉ hiển thị là "set" (đã đặt) trên trang.
- Các lần nhập đã lưu ở lại trên trang nhập cho đến khi bạn nhấn **Forget** (Quên), để bạn có thể
  triển khai chúng tới nhiều worker hơn sau này.
