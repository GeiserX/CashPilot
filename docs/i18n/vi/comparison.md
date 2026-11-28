---
source_hash: b48a8fc19aa4
---
# CashPilot so với các công cụ khác { #how-cashpilot-compares }

Trang này so sánh CashPilot với các dự án mở khác chạy nhiều ứng dụng thu nhập thụ động trong Docker. Chúng tôi đã kiểm tra mọi dự án vào ngày 2026-11-04, và kiểm tra lại CashPilot vào ngày 2026-11-28. Mỗi ô về một dự án khác đều liên kết tới file mà nó lấy thông tin, ở một commit cố định, để bạn có thể tự kiểm tra. Nếu một ô sai hoặc đã lỗi thời, vui lòng [mở một issue](https://github.com/GeiserX/CashPilot/issues).

## Các dự án được so sánh { #projects-compared }

| Dự án | Những gì chúng tôi đã kiểm tra | Số sao ngày 2026-11-04 | Giấy phép |
|---|---|---|---|
| [money4band][m4b-tree] | Bản phát hành 5.0.0, commit của tag `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` tại `65e900d` (2026-10-20), cùng các tuyên bố trong README về binary 3.0.0-beta.9 của nó | 238 | Độc quyền, [giấy phép riêng v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` tại `db9338a` (2026-11-03) | 257 | Không có file LICENSE. [README][ii-license] cho phép sao chép bản gốc và cấm phân phối các bản đã sửa đổi |
| [CashFactory][cf-tree] | `main` tại `0ff4bd0` (2025-04-08) | 410 | File [LICENSE][cf-license-file] là GPL-3.0, nhưng [README][cf-license] cấm phân phối các bản đã sửa đổi |
| [home-assistant-passive-income][ha-tree] (HA add-ons) | Bản phát hành 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Bản phát hành v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

money4band có hai dòng mã. Nhánh mặc định `main` (`3bfafb1`) của nó vẫn chứa mã 4.x, và lần thay đổi mã cuối cùng ở đó là vào 2026-03-03. Bản phát hành 5.0.0 được xây dựng từ một lịch sử riêng. Chúng tôi so sánh 5.0.0 vì đó là thứ bản phát hành mới nhất của nó cung cấp.

Giao diện web, tính năng quản lý đội máy và binary cài đặt của IGM là mã nguồn đóng và không có trong kho mã của nó. Ở những ô phụ thuộc vào chúng, ô đó ghi "README tuyên bố" và liên kết tới dòng README tương ứng. Mọi thứ khác trong cột của IGM đến từ các script shell và file compose trong kho mã.

Không đưa vào: [earning-machine](https://github.com/jf-m/earning-machine) và [passiveMachine](https://github.com/Xpl0itU/passiveMachine) không có commit nào từ năm 2024. Một lần tìm kiếm trên GitHub không thấy dự án nào khác còn được duy trì chạy nhiều hơn một ứng dụng, chỉ có các image cho một ứng dụng duy nhất.

## Tóm tắt { #short-version }

- **InternetIncome, money4band, IGM và, từ v1.69.0, CashPilot có thể kiếm tiền trên nhiều IP qua proxy.** Ba dự án đầu chạy mỗi ứng dụng một lần cho mỗi proxy, và proxy là tính năng chính của InternetIncome. CashPilot chạy thêm các bản sao của một dịch vụ đã được triển khai trên một worker, mỗi bản đi qua một proxy SOCKS5, HTTP CONNECT hoặc exit node của Tailscale ([bản sao qua proxy](proxies.md)).
- **InternetIncome khởi động 23 ứng dụng, IGM khởi động 20 và worker của CashPilot khởi động <!-- n:docker -->21<!-- /n -->.** CashPilot theo dõi tổng cộng nhiều dịch vụ hơn (<!-- n:live -->50<!-- /n -->) vì nó còn theo dõi các dịch vụ dạng tiện ích trình duyệt, ứng dụng máy tính và GPU mà nó không chạy. Từ v1.64.0, nó cũng có thể chạy bất kỳ image nào bạn chỉ định dưới dạng [dịch vụ tùy chỉnh](custom-services.md).
- **money4band và IGM nhận phần thưởng hằng ngày thay bạn, và giữ image của ứng dụng luôn được cập nhật bằng Watchtower.** CashPilot không làm cả hai việc này. Nó chỉ kéo lại image khi bạn triển khai hoặc triển khai lại.
- **CashPilot là dự án duy nhất ở đây đọc số dư từ tài khoản nhà cung cấp của bạn và lưu lịch sử.** money4band 5.0.0 hiển thị ước tính từ danh mục của chính nó, không phải từ tài khoản của bạn. Các dự án khác liên kết tới bảng điều khiển của từng nhà cung cấp.
- **CashPilot là dự án mã nguồn mở duy nhất ở đây có một UI cho nhiều máy chủ.** README của IGM tuyên bố có quản lý đội máy, nhưng mã đó nằm trong binary đóng của nó.
- **Từ v1.70.0, CashPilot là dự án duy nhất ở đây mặc định giữ các container ứng dụng kiếm tiền tránh xa LAN của bạn, với một số giới hạn.** Tính năng này bật cho các bản cài mới và các bản cài được nâng cấp không có ứng dụng kiếm tiền nào trên bridge mặc định của Docker. Một bản cài được nâng cấp có ứng dụng kiếm tiền đã nằm trên bridge đó sẽ giữ chúng ở đó cho đến khi bạn bật cách ly, và một mạng bạn chỉ định trong `CASHPILOT_CONTAINER_NETWORK` không được CashPilot dựng hàng rào ([cách ly](isolation.md#modes)). Từ 2.0.7, Mysterium cũng chạy sau hàng rào; một nút được triển khai bằng 2.0.6 trở về trước vẫn ở trên mạng của máy chủ, không có hàng rào, cho đến khi bạn triển khai lại nó ([Mysterium sau hàng rào](mysterium-fence.md)).

## So sánh song song { #side-by-side }

Cột của CashPilot mô tả v3.0.1. Mỗi ô của cột này đều ngắn, còn [phần ghi chú dưới bảng](#cashpilot-notes) chứa chi tiết và các liên kết tới mã. Các cột khác mô tả các commit trong bảng ở trên.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA add-ons |
|---|---|---|---|---|---|---|
| Số ứng dụng nó có thể khởi động (xem [cách chúng tôi đếm](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> do worker chạy, cộng thêm [image tùy chỉnh](custom-services.md); tổng cộng theo dõi <!-- n:live -->50<!-- /n --> | 15 ([danh mục][m4b-catalog]). README ghi 35, con số này [bao gồm][m4b-readme-35] các ứng dụng cộng đồng và các ứng dụng đã bị bỏ | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([file compose][cf-compose]) | 10 ([các thư mục add-on][ha-tree]) |
| Cách cài đặt | Docker Compose: một UI, cộng một worker trên mỗi máy chủ ([đội máy](fleet.md)) | Python CLI hoặc một binary dựng sẵn ghi ra file compose ([bản phát hành][m4b-tree]) | Trình cài đặt `curl \| sh` ([README][igm-install]) tải về một binary đóng, chỉ được kiểm tra bằng file SHA256SUMS từ cùng bản phát hành ([trình cài đặt][igm-installer-sums]) | Một script bash dài 1.608 dòng gọi `sudo docker run` ([script][ii-script]) | Một file compose tĩnh cộng `setup.sh` chạy bằng sudo ([setup][cf-setup]) | Một kho add-on của Home Assistant; cần Home Assistant OS hoặc Supervised |
| Nhiều máy chủ, một chế độ xem | Có ([đội máy](fleet.md)) | Không, mỗi thiết bị một stack | README tuyên bố có, trong binary đóng ([README][igm-features]) | Không | Không | Không |
| Nhiều proxy hoặc IP | Có, qua proxy SOCKS5, HTTP CONNECT hoặc exit node của Tailscale ([bản sao qua proxy](proxies.md), [ghi chú](#cashpilot-notes)) | Có ([README][m4b-features], [mã][m4b-multiproxy]) | Có ([README][igm-features], [compose][igm-proxy]) | Có, đây là tính năng chính của nó ([README][ii-readme-top]) | Không | Không |
| Thu nhập | <!-- n:collectors -->20<!-- /n --> bộ thu thập đọc số dư từ tài khoản nhà cung cấp của bạn và lưu lịch sử | Ước tính từ các khoảng trong danh mục, không phải dữ liệu tài khoản ([mã][m4b-earnings]) | Không tìm thấy trong các script | Không có | Không có | Không có |
| Khoản thanh toán | Đề xuất một khoản thanh toán khi số dư giảm, và ghi nhận nó khi bạn xác nhận ([schema][cp-payouts]) | Không có | Không có | Không có | Không có | Không có |
| Tự nhận phần thưởng hằng ngày | Không | Có, bằng sidecar ([README][m4b-features]) | Có ([README][igm-features], [compose][igm-sidecars]) | Không | Không | Không |
| Thông tin đăng nhập khi lưu trữ | Mã hóa (Fernet) trong cơ sở dữ liệu của UI ([ghi chú](#cashpilot-notes)) | Mã hóa (Fernet); file khóa nằm trong thư mục dữ liệu ([mã][m4b-crypto]) | Mã hóa (AES-256 bằng openssl); file khóa nằm cạnh kho lưu trữ ([mã][igm-encryptor]) | Văn bản thuần trong `properties.conf`; một số mật khẩu được truyền dưới dạng đối số của `docker run` ([script][ii-password-arg]) | Văn bản thuần trong `.env` ([file][cf-env]) | Tùy chọn của add-on, được Supervisor lưu trong `/data/options.json` ([tài liệu HA][ha-options]) |
| Thiết lập container của ứng dụng kiếm tiền | Loại bỏ mọi capability, `no-new-privileges`, giới hạn pids; từ chối chế độ privileged ([ghi chú](#cashpilot-notes)) | `no-new-privileges` trên mọi dịch vụ không privileged ([mã][m4b-nnp]); container proxy chạy privileged với `NET_ADMIN` ([template][m4b-tun]) | Không đặt gì cho các dịch vụ ứng dụng; Mysterium nhận `NET_ADMIN` ([compose][igm-hosting-myst]); container proxy nhận `NET_ADMIN`, với `no-new-privileges` và giới hạn pids ([compose][igm-proxy]) | Ebesucher chạy với `seccomp=unconfined` ([script][ii-seccomp]); các container proxy và Mysterium nhận `NET_ADMIN` | Không đặt gì | Không add-on nào yêu cầu quyền privileged, mạng của máy chủ hay quyền truy cập Docker API ([cấu hình ví dụ][ha-config]) |
| Docker socket được mount vào | Socket proxy, chỉ đọc, và một container di chuyển dữ liệu chạy một lần ([ghi chú](#cashpilot-notes)) | Watchtower ([template][m4b-watchtower]) | Watchtower, chạy chỉ đọc với `no-new-privileges` ([compose][igm-watchtower]) | Năm container trợ giúp khởi động lại ([script][ii-sock-helper]) và Watchtower ([script][ii-watchtower]) | Portainer, công bố trên các cổng 8000, 9000 và 9443 trên mọi giao diện mạng ([compose][cf-portainer]), và hai Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Không có |
| Tag của image | <!-- n:pinned -->9<!-- /n --> trong số <!-- n:docker -->21<!-- /n --> image ứng dụng kiếm tiền được ghim vào một phiên bản hoặc digest; số còn lại thả nổi | Cả 15 image ứng dụng đều dùng `:latest` ([ví dụ][m4b-image]); container proxy ghim vào v2.6.0, Watchtower vào `:1` | Không có tag, nên Docker dùng `latest` ([compose][igm-hosting]); tag chỉ được đặt cho một số bản build ARM | Phần lớn là `:latest` ([ví dụ][ii-seccomp]); EarnApp `:lite`, Honeygain ghim vào 0.6.6 khi chạy qua proxy trên amd64 ([script][ii-honeygain]), Traffmonetizer dùng tag theo kiến trúc trên ARM; Watchtower `:nightly` | `:latest` hoặc không có tag, trừ EarnApp `:lite` ([compose][cf-compose]) | Mỗi add-on một phiên bản, được một job CI hằng ngày nâng lên ([workflow][ha-bump], [ví dụ][ha-dockerfile]) |
| Cập nhật image ứng dụng | Kéo lại ở mỗi lần triển khai hoặc triển khai lại; không có trình tự cập nhật | Watchtower ([template][m4b-watchtower]) | Watchtower mỗi 4 giờ ([compose][igm-watchtower]) | Watchtower mỗi ngày một lần, nếu bạn bật nó ([script][ii-watchtower]) | Hai Watchtower, mỗi cái chỉ giới hạn cho một ứng dụng, PacketStream ([compose][cf-watchtower-ps]) và EarnFM ([compose][cf-watchtower-efm]); 9 ứng dụng còn lại không được cập nhật | Cập nhật add-on của Home Assistant |
| Cách ly LAN | Bật mặc định cho các bản cài mới ([cách ly](isolation.md#lan-isolation-by-default), [ghi chú](#cashpilot-notes)) | Subnet bridge riêng ([cấu hình][m4b-subnet]), không chặn LAN | Chưa có gì được merge | Không tìm thấy | Không tìm thấy | Không tìm thấy |
| ARM | UI và worker arm64, có kiểm tra nền tảng trước mỗi lần triển khai ([ARM](arm.md)) | Binary arm64 và armv7 ([bản phát hành][m4b-release]) | README tuyên bố hỗ trợ amd64 và arm64, arm32 có giới hạn, và thiết lập QEMU ([README][igm-arch]) | Cần giả lập binfmt cho các image chỉ có amd64 ([README][ii-arm]) | README ghi rằng nó không chạy trên Raspberry Pi ([README][cf-raspberry]) | Tùy từng add-on; ProxyRack chỉ có amd64 ([cấu hình][ha-proxyrack]) |
| UI | Giao diện web, cùng các client Desktop, Android, MCP và Home Assistant | CLI, menu và một bảng điều khiển web cục bộ mặc định bind vào 127.0.0.1 ([mã][m4b-bind]) | CLI, menu, và theo README là một giao diện web trên cổng 4747 truy cập được từ LAN ([README][igm-webui]) | Không có, chỉ là một script | Một trang dấu trang trên cổng 80 cộng Portainer ([README][cf-ui]) | Bảng add-on của Home Assistant |
| Bản phát hành mới nhất | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Không có bản phát hành theo phiên bản | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Các lệnh gọi ra ngoài ngoài các ứng dụng | Kiểm tra cập nhật, tra cứu IP công khai, tỷ giá và số dư on-chain; phông chữ và Chart.js từ CDN ([ghi chú](#cashpilot-notes)) | Bản phát hành trên GitHub, để kiểm tra cập nhật ([mã][m4b-updater]); Docker Hub và ghcr.io, để kiểm tra tag image ([mã][m4b-registry]); khi bạn chạy kiểm tra IP, `api.ipify.org`, `ifconfig.me` hoặc `icanhazip.com` để lấy IP công khai của bạn và `ip-api.com` qua HTTP thường để lấy điểm IP ([mã][m4b-ipscore]) | Bản phát hành trên GitHub ([mã][igm-version]); `api.ipify.org`, `ifconfig.me` hoặc `icanhazip.com` để lấy IP công khai của bạn ([mã][igm-ifconfig]); `ip-api.com` qua HTTP thường để lấy điểm IP ([mã][igm-ipscore]). Binary đóng chưa được kiểm tra | Không tìm thấy | Không tìm thấy | Không tìm thấy |

### Ghi chú về cột của CashPilot { #cashpilot-notes }

- **Nhiều proxy hoặc IP.** Từ v1.69.0, CashPilot chạy thêm các bản sao của một dịch vụ đã triển khai trên một worker, mỗi bản đi qua proxy riêng của nó. SOCKS5 và HTTP CONNECT chỉ mang TCP: đường hầm chỉ cho TCP tới cổng của proxy đi ra, nên các relay UDP của SOCKS5 bị loại bỏ. Một exit node của Tailscale mang được cả UDP. Ứng dụng kiếm tiền dùng chung network namespace của một container đường hầm ([mã][cp-proxy-deploy]). Namespace đó chỉ cho loopback, đường hầm và kết nối riêng của đường hầm tới proxy đi ra: TCP tới địa chỉ và cổng của proxy, hoặc các gói đã đánh dấu của tailscaled ([tường lửa đường hầm][cp-tunnel-fw]). Vì vậy một proxy chết sẽ làm ứng dụng kiếm tiền dừng thay vì để lưu lượng của nó rò rỉ ra ngoài ([cách hoạt động](proxies.md#how-it-works)). Một dịch vụ không thể chạy qua proxy khi nó cần mạng của máy chủ, cổng được công bố, volume, thiết bị, GPU hoặc `NET_ADMIN`, `NET_RAW` hay `SYS_ADMIN`, hoặc khi điều khoản của nó cấm proxy. Vì vậy <!-- n:noproxy -->10<!-- /n --> trong số <!-- n:docker -->21<!-- /n --> chỉ kiếm tiền từ IP riêng của máy chủ ([những gì không thể](proxies.md#what-cannot-run-through-a-proxy)).
- **Thu nhập.** Một số bộ thu thập cần cookie hoặc token sao chép từ trình duyệt của bạn, và một số trong đó sẽ hết hạn. Hướng dẫn của từng dịch vụ cho biết là những bộ nào.
- **Thông tin đăng nhập khi lưu trữ.** UI giữ file khóa mã hóa trong cùng volume dữ liệu với cơ sở dữ liệu ([mã][cp-fernet]). Thông tin đăng nhập của ứng dụng kiếm tiền đến mỗi worker dưới dạng biến môi trường của container, nên chúng là văn bản thuần trong cấu hình Docker của worker đó (`docker inspect`).
- **Thiết lập container của ứng dụng kiếm tiền.** Worker loại bỏ mọi capability, rồi thêm lại những gì danh mục liệt kê cho dịch vụ. Nó đặt `no-new-privileges` và một giới hạn pids, và từ chối các container privileged ([mã][cp-hardening], [mã][cp-privileged], [mặc định bảo mật](security-defaults.md)). Mysterium chạy trong network namespace riêng trên bridge có hàng rào với `NET_ADMIN`, `SETUID` và `SETGID`, trên một image được ghim theo digest ([danh mục][cp-myst]). Một runtime gVisor tùy chọn có thể thêm một kernel chạy trong không gian người dùng ([runtime](security-defaults.md#container-runtimes-gvisor-where-it-works)).
- **Docker socket.** Từ v1.71.0, chỉ socket proxy gắn socket: sockguard 2.4.7, ghim theo digest, chỉ đọc ([compose][cp-sock]). Worker nhận một bản đã lọc, từ chối các container privileged, các bind của `/` hoặc của socket, và các capability hay thiết bị nằm ngoài danh mục ([socket proxy](security-defaults.md#docker-socket-proxy)). Container chạy một lần `cashpilot-migrate` cũng gắn socket: nó gắn nhãn cho những gì các bản phát hành cũ đã tạo, phục vụ việc cách ly theo chủ sở hữu của proxy, và thoát trước khi proxy khởi động ([compose][cp-migrate]). Một ứng dụng kiếm tiền không bao giờ nhận socket ([mã][cp-mounts]). Proxy này chưa phải là một ranh giới root: khi đặt `CASHPILOT_COMPOSE_DIR` hoặc `CASHPILOT_PROXY_BIND_MOUNTS`, một symlink được cài vào một thư mục được phép sẽ chạm tới `/` của máy chủ sau hai lần triển khai ([chi tiết](security-defaults.md#docker-socket-proxy)). Các bản niêm yết Unraid và TrueNAS vẫn gắn socket thô vào worker ([kho ứng dụng](app-stores.md)).
- **Cách ly LAN.** Bật mặc định từ v1.70.0, cho các bản cài mới và các bản cài được nâng cấp không có ứng dụng kiếm tiền nào trên bridge mặc định của Docker. Worker đưa các ứng dụng kiếm tiền lên bridge riêng của nó và ghi một bảng tường lửa cho bridge đó ([mã][cp-fence]). Bảng này loại bỏ các dải địa chỉ riêng, dải tailnet, metadata đám mây, các subnet mà máy chủ kết nối và chính máy chủ. Khi bật phát hiện IP công khai, nó cũng loại bỏ IP công khai của gia đình ([cách ly](isolation.md#lan-isolation-by-default)). Một bản cài được nâng cấp có ứng dụng kiếm tiền đã nằm trên bridge mặc định sẽ ở lại đó cho đến khi bạn nhấn **Turn on isolation** (Bật cách ly). `CASHPILOT_ISOLATION=off` tắt tính năng này. Khi đặt `CASHPILOT_CONTAINER_NETWORK`, CashPilot không ghi hàng rào nào cho mạng đó, và các quy tắc tường lửa là của bạn. Trên Podman không có hàng rào, và trang đội máy có ghi rõ điều đó ([chế độ](isolation.md#modes), [mã][cp-fence-mode]). Từ 2.0.7, Mysterium cũng có hàng rào. Một nút được triển khai bằng 2.0.6 trở về trước vẫn ở trên mạng của máy chủ cho đến khi bạn triển khai lại nó ([Mysterium sau hàng rào](mysterium-fence.md)). Một bước kiểm tra cho thấy các ứng dụng kiếm tiền có thể truy cập những gì ([kiểm tra](isolation-check.md)).
- **Lệnh gọi ra ngoài.** Ngoài chính các ứng dụng, CashPilot gọi tới:
    - Bản phát hành trên GitHub, mỗi ngày một lần, để kiểm tra cập nhật (`CASHPILOT_UPDATE_CHECK=off` dừng việc này, [mã][cp-update]).
    - `api.ipify.org`, `ifconfig.me` hoặc `icanhazip.com` mỗi giờ một lần từ mỗi worker, để lấy IP công khai của nó (`CASHPILOT_EGRESS_DETECT=off` dừng việc này, [mã][cp-egress]).
    - CoinGecko và Frankfurter, cho tỷ giá ([mã][cp-rates]).
    - mempool.space, api.kaspa.org và các nút RPC công khai của Ethereum, Ethereum Classic, Polygon và Solana, cho [số dư on-chain](onchain.md).
    - iptoasn.com, cho bảng tên mạng của nó, nhiều nhất mỗi tuần một lần và chỉ khi có một worker bật [hoạt động](activity.md#network-names-and-countries) ([mã][cp-ipgeo]).
    - Từng nhà cung cấp, cho các bộ thu thập.

    Trình duyệt tải Google Fonts ([template][cp-cdn]) và Chart.js từ jsDelivr ([template][cp-chartjs]).

Không dự án nào gửi dữ liệu đo lường sử dụng trong phần mã chúng tôi đã đọc. Binary đóng của IGM không đọc được.

Mọi dự án ở đây đều truyền thông tin đăng nhập của ứng dụng cho container dưới dạng biến môi trường, và InternetIncome còn truyền một số dưới dạng đối số lệnh, nên trên máy chủ chạy các ứng dụng, chúng là văn bản thuần trong cấu hình container của Docker (`Env` và `Args` trong `docker inspect`), bất kỳ ai có quyền truy cập Docker đều đọc được. Hàng "Thông tin đăng nhập khi lưu trữ" chỉ mô tả bản sao được lưu trữ.

## Cách chúng tôi đếm { #how-we-counted }

- **CashPilot.** Các dịch vụ trong danh mục có trạng thái active hoặc beta và có image Docker, không tính điện toán GPU hay các pool đào coin. Con số trên trang này đến từ `scripts/generate_readme_tables.py`, và CI báo lỗi nếu nó bị lệch.
- **money4band 5.0.0.** Mỗi ứng dụng một file JSON trong `config/catalog/supported/`: 15. Con số "35 apps" trong README còn tính cả danh mục cộng đồng, vốn tắt theo mặc định ([cấu hình][m4b-community]), các ứng dụng không có image Docker, và các ứng dụng đã bị bỏ.
- **IGM.** Các mục trong `apps.json`: 20, tất cả đều được bật. Container proxy, Watchtower và các sidecar nhận thưởng không được tính.
- **InternetIncome.** Mỗi khối chú thích `# Starting ... container` trong `internetIncome.sh`, trừ các khối proxy và Watchtower: 24. Các khối Chrome và Firefox của Ebesucher là một ứng dụng, EarnFM và EarnFM Fleetshare cũng vậy, vì chúng dùng cùng một tài khoản EarnFM. Khối tiện ích Depin khởi động Grass và Gradient ([script][ii-depin]), tức hai ứng dụng. Tổng cộng 23. Bảng trong README liệt kê 27 ứng dụng, một số chỉ có liên kết đăng ký.
- **CashFactory.** Các dịch vụ kiếm tiền trong `docker-compose.yml`: 11. Portainer, máy chủ web và hai Watchtower không được tính. Một dịch vụ bị chú thích bỏ.
- **HA add-ons.** Các thư mục add-on có file cấu hình: 10.

Chúng tôi không kiểm tra xem mỗi ứng dụng trong mỗi danh sách có còn trả tiền hay không.

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L541-L557
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L51
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/orchestrator.py#L1534-L1541
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1977-L1978
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1586-L1631
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/services/bandwidth/mysterium.yml#L25-L27
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L125-L180
[cp-update]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/update_check.py#L46-L56
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/exchange_rates.py#L125-L145
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L373-L380
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L292
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/proxy_tunnel.py#L1145
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/tunnel/cp-tunnel#L1-L27
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L103-L125
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L29-L52
[cp-ipgeo]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/ipgeo.py#L1-L40
[cp-migrate]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L91-L101
