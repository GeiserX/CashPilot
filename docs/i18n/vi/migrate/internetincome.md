---
source_hash: ca9dd25d45ca
---
# Chuyển từ InternetIncome { #moving-from-internetincome }

CashPilot có thể đọc `properties.conf` của InternetIncome, cùng các file nơi nó
giữ id thiết bị EarnApp và ProxyRack của bạn, và chuyển chúng sang. Bạn kiểm tra
mọi thứ trước khi CashPilot lưu.

## Trước khi bắt đầu { #before-you-start }

Bạn cần tài khoản chủ sở hữu CashPilot và ít nhất một worker CashPilot.

Hãy dừng InternetIncome trên một máy trước khi bạn triển khai cùng các dịch vụ đó ở đó từ
CashPilot. Hai bản chạy sau cùng một kết nối chỉ kiếm tiền như một, và cùng một id thiết bị
không được chạy hai lần. Trong thư mục InternetIncome, hãy chạy:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` xóa các container và giữ lại `earnapp.txt`, `proxyrack.txt` và
thư mục dữ liệu Mysterium. `--deleteBackup` xóa cả những thứ đó
([internetIncome.sh, dòng 61 đến 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
và [dòng 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
nên hãy nhập trước.

## Dùng những file nào { #which-files-to-use }

Từ thư mục InternetIncome:

- `properties.conf`, các thiết lập của bạn.
- `earnapp.txt`, nếu bạn đã chạy EarnApp. Mỗi dòng chứa một liên kết thiết bị
  ([dòng 1250 đến 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, nếu bạn đã chạy ProxyRack. Mỗi dòng một UUID thiết bị
  ([dòng 817 đến 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot lấy thiết bị đầu tiên trong mỗi file: thiết bị mà container chính của bạn
đã dùng và thiết bị bạn đã liên kết với tài khoản. Các dòng khác thuộc về các bản sao
qua proxy, và trang sẽ cho bạn biết nó đã bỏ qua bao nhiêu dòng.

InternetIncome chạy mọi giá trị qua shell
([dòng 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Một giá trị trong dấu nháy đơn được lấy đúng như đã viết, như các chú thích trong
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)
khuyên. Một giá trị ngoài dấu nháy đơn có chứa `$`, dấu backtick, dấu cách hoặc
một ký tự khác mà shell sẽ thay đổi thì không giống những gì file hiển thị, nên
CashPilot yêu cầu bạn nhập lại thay vì chạy shell để tìm ra giá trị đó.

## Cách nhập { #how-to-import }

1. Mở **Settings** (Cài đặt), rồi **Import from another tool** (Nhập từ công cụ khác) (hoặc vào `/import`).
2. Thêm `properties.conf`, cùng `earnapp.txt` và `proxyrack.txt` nếu bạn có
   chúng. Để công cụ ở "Tell from the files" (Nhận biết từ file), hoặc chọn InternetIncome.
3. Kiểm tra bảng. Đánh dấu các dịch vụ bạn muốn và điền mọi giá trị được đánh dấu
   là thiếu. Repocket cần email tài khoản của bạn, thứ mà InternetIncome chưa bao giờ hỏi
   tới.
4. Nhấn **Save the ticked services** (Lưu các dịch vụ đã đánh dấu), rồi triển khai chúng tới các worker từ
   cùng trang đó.

## Những gì được chuyển sang { #what-comes-over }

| Ứng dụng InternetIncome | Các khóa được đọc | Dịch vụ CashPilot | Những gì được chuyển sang |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | khóa API (thêm email của bạn) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | khóa API, UUID thiết bị |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | email, mật khẩu |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | email, mật khẩu |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id người dùng |
| `earnfm` | `EARN_FM_API` | Earn.fm | khóa API |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | id thiết bị |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | email, mật khẩu |
| `mysterium` | `MYSTERIUM=true` | Mysterium | được bật; xem ghi chú về Mysterium bên dưới |

Một giá trị để trống nghĩa là ứng dụng đã tắt, và nó không được liệt kê.

Các ứng dụng sau được liệt kê nhưng không được chuyển sang:

| Ứng dụng InternetIncome | Lý do |
|---|---|
| `urnetwork` | InternetIncome dùng một token phiên. CashPilot đăng nhập URnetwork bằng email và mật khẩu của bạn. |
| `grass` | Grass chạy dưới dạng tiện ích trình duyệt. CashPilot chỉ theo dõi nó, bằng access token từ bảng điều khiển Grass. |
| `titan`, `ebesucher`, `wipter` | CashPilot theo dõi các ứng dụng này, nhưng không có container nào để triển khai. |
| `peer2profit` | Không còn hoạt động. |

Thiết lập của các ứng dụng mà CashPilot không có (antGain, Adnade và các ứng dụng khác) được
liệt kê theo tên là không được đọc.

## Những gì không bao giờ được chuyển sang { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot đặt tên mỗi thiết bị theo worker mà nó chạy trên đó, để
  hai worker không bao giờ báo cùng một tên. Các thiết bị cũ của bạn vẫn được liệt kê là
  ngoại tuyến trong bảng điều khiển của từng nhà cung cấp cho đến khi bạn xóa chúng ở đó.
- **Proxy** (`USE_PROXIES`, `proxies.txt`). Thêm từng proxy trong mục **Proxies** (Proxy)
  của trang **Fleet** (Đội máy), rồi chạy các bản sao dịch vụ của bạn qua nó; tự việc thêm
  một proxy không khởi động gì cả. Với `USE_PROXIES=true`, InternetIncome chỉ chạy
  các dịch vụ của bạn qua proxy. Việc lưu một lần nhập cũng không khởi động gì. Một
  bản sao qua proxy cần cùng dịch vụ đó đã được triển khai trên worker trước, và
  việc triển khai sẽ chạy nó trên kết nối riêng của worker, nên một dịch vụ không bao giờ
  được dùng kết nối đó thì nên để không đánh dấu. Xem [Bản sao qua proxy](../proxies.md).
- **`BROWSER_USERNAME` và `BROWSER_PASSWORD`**, thông tin đăng nhập trình duyệt riêng
  của InternetIncome.

## Theo dõi thu nhập { #earnings-tracking }

Với Honeygain, IPRoyal Pawns và Bitping, thông tin đăng nhập của container cũng là
thông tin đăng nhập tài khoản, nên CashPilot cũng điền luôn thông tin thu thập thu nhập của chúng, trừ khi bạn
đã đặt chúng trong **Settings** (Cài đặt). Với mọi dịch vụ khác, hãy thêm thông tin đăng nhập để thu thập thu nhập
trong **Settings > Earnings collection** (Cài đặt > Thu thập thu nhập).

## Mysterium { #mysterium }

Việc nhập sẽ bật Mysterium, nhưng CashPilot khởi động một nút mới với một
danh tính mới. Keystore của nút cũ và mọi khoản thu nhập chưa thanh toán vẫn nằm trong
thư mục `mysterium-data` của InternetIncome. Hãy thanh toán chúng trước, hoặc làm theo
[hướng dẫn Mysterium](../guides/mysterium.md) để chuyển danh tính sang.

## An toàn { #safety }

- Không có gì trong các file được chạy hay khai triển, và không địa chỉ nào trong đó được truy cập.
- Các file được đọc một lần và không được giữ lại. Những gì bạn lưu được lưu trữ mã hóa, như
  mọi thông tin đăng nhập khác trong CashPilot.
- Các bí mật chỉ hiển thị là "set" (đã đặt) trên trang.
- Các lần nhập đã lưu ở lại trên trang nhập cho đến khi bạn nhấn **Forget** (Quên), để bạn có thể
  triển khai chúng tới nhiều worker hơn sau này.
