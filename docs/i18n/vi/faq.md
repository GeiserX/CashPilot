---
source_hash: 915470497dbc
---
# Câu hỏi thường gặp { #faq }

**Chia sẻ băng thông có an toàn không?**

Các dịch vụ chia sẻ băng thông thường định tuyến lưu lượng hợp pháp (nghiên cứu thị trường, xác minh quảng cáo, so sánh giá, phân phối nội dung) qua kết nối của bạn. Dù vậy, bạn đang chia sẻ địa chỉ IP của mình, nên hãy đọc kỹ điều khoản dịch vụ và chính sách quyền riêng tư của từng dịch vụ trước khi đăng ký. Với một số dịch vụ, bạn có thể chạy chúng trên VPS thay vì IP dân cư. **Đây không phải lời khuyên pháp lý -- hãy tham khảo các dịch vụ cụ thể mà bạn định dùng và, nếu cần, tìm tư vấn pháp lý độc lập về khu vực pháp lý của bạn.**

**Tôi có thể kiếm được bao nhiêu?**

Thu nhập khác nhau rất nhiều tùy vị trí, nhà mạng, số lượng thiết bị và những dịch vụ bạn chạy. Bảng điều khiển theo dõi thu nhập thực tế của bạn theo thời gian để bạn có thể tối ưu thiết lập. Để tham khảo sơ bộ, và không phải lời hứa, một máy chủ gia đình chạy 10 đến 15 dịch vụ kiếm được khoảng $30 đến $100 mỗi tháng, và có thể ít hơn, thậm chí bằng không. Thêm máy chủ, hoặc điện toán GPU, sẽ tăng thêm con số đó.

**Tôi có thể chạy trên VPS hoặc máy chủ đám mây không?**

Một số dịch vụ yêu cầu IP dân cư và sẽ không trả tiền (hoặc sẽ cấm) các IP VPS/trung tâm dữ liệu. Danh mục ghi "residential IP" (IP dân cư) trong phần những gì chúng cần. Các dịch vụ hoạt động trên VPS là cách tốt để mở rộng mà không cần thêm phần cứng ở nhà.

**Thông tin đăng nhập được lưu như thế nào?**

Mọi thông tin đăng nhập của dịch vụ được mã hóa khi lưu trong cơ sở dữ liệu SQLite bằng một khóa Fernet lưu tại `/data/.fernet_key`, khóa này được tạo tự động ở lần chạy đầu. File cơ sở dữ liệu nằm trong volume Docker được mount (`cashpilot_data:/data`). Không có thông tin đăng nhập nào được gửi đi đâu cả, ngoại trừ tới chính các container của dịch vụ.

Lưu ý rằng đây là một khóa khác với `CASHPILOT_SECRET_KEY`, khóa này chỉ ký các phiên đăng nhập.

### Sao lưu khóa mã hóa { #backing-up-the-encryption-key }

Khả năng khôi phục thông tin đăng nhập của bạn phụ thuộc hoàn toàn vào `/data/.fernet_key`. Nếu mất file đó, bạn sẽ phải nhập lại mọi thông tin đăng nhập, vì không có cách nào giải mã các giá trị đã lưu khi không có nó.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

File luôn được ưu tiên hơn biến môi trường, nên việc đặt `CASHPILOT_ENCRYPTION_KEY` trên một bản cài đã có khóa không thay đổi gì và an toàn. Nó chỉ được dùng khi không có file khóa nào, đó chính là trường hợp khôi phục.

Nếu CashPilot hoàn toàn không ghi được khóa ra đĩa, vì `/data` không ghi được hoặc chưa được mount, nó từ chối khởi động thay vì mã hóa thông tin đăng nhập của bạn bằng một khóa sẽ biến mất ở lần khởi động lại tiếp theo. Đặt `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` nếu đó thực sự là điều bạn muốn.

<a id="forgot-password"></a>

### Quên mật khẩu hoặc tên người dùng { #forgot-password-or-username }

CashPilot không có tính năng đặt lại qua e-mail. Người vận hành máy chủ đặt lại mật khẩu từ console của container CashPilot UI. Các dịch vụ, thu nhập và thông tin đăng nhập đã lưu của bạn không bị ảnh hưởng: chúng được mã hóa bằng `/data/.fernet_key`, không phải bằng mật khẩu của bạn.

Lệnh `python -m app.users` cần CashPilot 2.3 trở lên. Trên 2.2 trở về trước, nó báo lỗi `No module named app.users`. Hãy cập nhật trước: với Docker Compose, đổi tag `drumsergio/cashpilot` và `drumsergio/cashpilot-worker` thành `2.3` hoặc mới hơn (một tag ghim như `2.2` hoặc `2.2.9` sẽ ở lại bản phát hành đó), rồi chạy `docker compose up -d` ([Cập nhật CashPilot](getting-started.md#updating-cashpilot)). Trên Unraid, hãy cập nhật container.

1. Liệt kê các tài khoản. Việc này cũng hiển thị tên người dùng bạn đã quên. Tên người dùng phân biệt chữ hoa chữ thường.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Đặt một mật khẩu ngẫu nhiên mới cho tài khoản. Thay `alice` bằng tên người dùng từ bước 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Khi chỉ có đúng một chủ sở hữu, bạn có thể bỏ tên người dùng, và lệnh sẽ đặt lại cho chủ sở hữu đó. Nếu tên người dùng bắt đầu bằng `-`, hãy đặt `--` trước nó: `reset-password -- -alice`.

    Lệnh in mật khẩu mới ra một lần.

3. Nếu có thể người khác đã truy cập được tài khoản, hãy khởi động lại container UI ngay bây giờ (`docker restart cashpilot-ui`). Các trình duyệt vẫn đang đăng nhập bằng người dùng đó chỉ bị đăng xuất sau khi khởi động lại. Nếu bạn chỉ quên mật khẩu, việc khởi động lại là tùy chọn.
4. Đăng nhập bằng mật khẩu mới, rồi đổi nó từ menu ảnh đại diện (góc trên bên phải), **Change password** (Đổi mật khẩu).

Tên container phụ thuộc vào cách bạn cài CashPilot:

| Cách cài | Container UI |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | một tên được tạo tự động; `docker ps` hiển thị nó |

Portainer, Unraid và CasaOS cũng có nút console cho mỗi container. Lệnh này không cần nhập gì từ terminal, nên nó cũng chạy được ở đó.

Để đổi tên người dùng:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

Tên mới tuân theo quy tắc đăng ký: 3 đến 32 ký tự gồm chữ cái, chữ số, `_` hoặc `-`. Đăng xuất rồi đăng nhập lại để thấy nó.

**Sau khi nghi ngờ bị xâm nhập**, ví dụ mất một bản sao lưu có chứa `/data/.secret_key`, chỉ đặt lại mật khẩu là không đủ. Bất kỳ ai có khóa đó đều có thể ký một cookie đăng nhập hợp lệ, và việc đặt lại không ngăn được điều đó. Hãy thay khóa, rồi khởi động lại container UI. `&&` chỉ khởi động lại nó khi khóa mới đã vào chỗ; nếu lệnh in ra lỗi, hãy sửa lỗi đó trước:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Sau khi khởi động lại, mọi trình duyệt đều bị đăng xuất, và mọi người đăng nhập lại bằng mật khẩu của mình. Thông tin đăng nhập đã lưu không bị ảnh hưởng. Nếu bạn tự đặt `CASHPILOT_SECRET_KEY`, lệnh sẽ từ chối: thay vào đó hãy đặt một giá trị ngẫu nhiên mới vào biến đó và tạo lại container. Một lệnh `docker run` từ image không thấy biến đó và không thể từ chối, nên hãy dùng `docker exec` trên container UI.

Khóa mới chấm dứt các cookie giả mạo, nhưng không xóa được những gì kẻ tấn công đã làm khi còn ở bên trong. Thêm hai bước nữa:

1. Chạy `docker exec cashpilot-ui python -m app.users list`. Xóa mọi tài khoản bạn không nhận ra từ bảng điều khiển.
2. Nếu bản sao bị mất chứa toàn bộ `/data`, hãy đổi mật khẩu các tài khoản nhà cung cấp của bạn. `.fernet_key` và `cashpilot.db` cùng nhau giải mã được mọi thông tin đăng nhập đã lưu.

Nếu sau này bạn khôi phục một bản sao lưu được tạo trước khi thay khóa, hãy bỏ `.secret_key` của nó ra ([Sao lưu và khôi phục](backup-restore.md#restore)), hoặc thay khóa và khởi động lại một lần nữa. Nếu không, khóa cũ sẽ quay lại. Cơ sở dữ liệu được khôi phục cũng mang lại các tài khoản và mật khẩu mà nó chứa, nên hãy lặp lại việc kiểm tra tài khoản và mọi lần đặt lại mật khẩu.

**Nếu container UI không khởi động**, hãy chạy lệnh từ cùng image trên cùng dữ liệu. Trước tiên hãy tìm thư mục trên máy chủ chứa `/data` của UI. Cách này dùng được cho container đã dừng, và cho cả volume có tên lẫn bind mount (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Sau đó mount thư mục đó và dùng tag image bạn đang chạy:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Kiểm tra rằng danh sách hiển thị các tài khoản của bạn, rồi chạy cùng dòng lệnh đó với `reset-password alice` thay cho `list`.

Một đường dẫn không có cơ sở dữ liệu sẽ báo lỗi "no database", và lệnh không tạo ra hay thay đổi gì ở đó. Docker vẫn có thể để lại một thư mục hoặc volume trống mang tên đó; hãy xóa nó.

**Đừng** xóa volume dữ liệu: việc đó xóa `/data/.fernet_key` và cùng với nó là mọi thông tin đăng nhập đã lưu. Cũng **đừng** xóa các hàng khỏi bảng `users`.

**Làm sao để gỡ bỏ hoàn toàn CashPilot?**

`docker compose down -v` chỉ xóa các container của chính CashPilot. Các dịch vụ nó đã triển khai vẫn tiếp tục chạy, và dữ liệu của chúng, mạng có hàng rào và một bảng tường lửa vẫn còn đó. [Gỡ bỏ hoàn toàn CashPilot](uninstall.md) xóa tất cả những thứ đó, cho biết những gì sẽ mất vĩnh viễn, và chỉ cách kiểm tra rằng không còn gì sót lại.

**Còn về bảo mật thì sao?**

Mọi dịch vụ CashPilot triển khai đều chạy trong container riêng với mọi capability của Linux bị loại bỏ (một vài dịch vụ chỉ thêm lại những capability mà chúng khai báo) và có đặt `--security-opt no-new-privileges`, nên một tiến trình bên trong không thể giành thêm đặc quyền. Container không thể thấy hệ thống file của máy chủ ngoài các volume mà một dịch vụ khai báo. Trên bản cài mới, worker cũng dựng hàng rào ngăn chúng khỏi LAN, máy chủ, tailnet và metadata đám mây của bạn, nên chúng chỉ ra được internet và không chạm tới gì cục bộ ([Cách ly mạng](isolation.md)). Trên Podman không có hàng rào: các ứng dụng kiếm tiền chạy trên mạng mặc định của Podman, mạng này có thể truy cập LAN của bạn, và trang **Fleet** (Đội máy) có ghi rõ điều đó ([Cách ly mạng](isolation.md) liệt kê các lựa chọn). Một bản cài được nâng cấp từ bản phát hành trước 1.70 giữ các ứng dụng kiếm tiền trên bridge mặc định của Docker, bridge này có thể truy cập LAN của bạn, cho đến khi bạn nhấn **Turn on isolation** (Bật cách ly) trên trang **Fleet** (Đội máy). Từ 2.0.7, Mysterium cũng chạy sau hàng rào; một nút được triển khai bằng 2.0.6 trở về trước vẫn ở trên mạng của máy chủ cho đến khi bạn triển khai lại nó ([Đưa nút Mysterium của bạn vào sau hàng rào](mysterium-fence.md)). [Bảo vệ mạng gia đình](home-network-security.md) trình bày cách tự dựng tường lửa cho bridge của riêng bạn thay vào đó. Thông tin đăng nhập của dịch vụ được mã hóa khi lưu trữ bằng mã hóa đối xứng Fernet. UI không có quyền truy cập Docker. Với các file compose được phát hành, worker không bao giờ được cấp Docker socket gốc: nó kết nối tới Docker qua `cashpilot-socket-proxy`, thành phần từ chối các container đặc quyền và các bind của `/` hoặc socket (trừ khi bạn đặt một trong số chúng, hoặc một thư mục chứa socket, vào `CASHPILOT_PROXY_BIND_MOUNTS` hoặc `CASHPILOT_COMPOSE_DIR`: proxy coi những thứ đó là đã được cho phép), và giới hạn worker trong các container, volume và mạng mang nhãn chủ sở hữu của nó ([mặc định bảo mật](security-defaults.md)). Các template Unraid và ứng dụng TrueNAS vẫn mount socket gốc vào worker, điều tương đương quyền root trên máy chủ ([kho ứng dụng](app-stores.md)).

Dù vậy, không có thiết lập nào là tuyệt đối an toàn. Bạn vẫn đang chạy phần mềm của bên thứ ba định tuyến lưu lượng bên ngoài qua mạng của bạn. Cách ly bằng Docker giảm đáng kể bề mặt tấn công so với chạy trực tiếp các dịch vụ này trên máy chủ, nhưng không loại bỏ mọi rủi ro. Chúng tôi khuyên bạn chạy CashPilot trên một máy hoặc VLAN riêng, cập nhật Docker và hệ điều hành của máy chủ thường xuyên, và xem mã nguồn mở của mọi dịch vụ trước khi triển khai nó.

**Điều gì xảy ra nếu một container dịch vụ bị sập?**

CashPilot liên tục giám sát sức khỏe container. Nếu một container dịch vụ thoát bất ngờ, nó sẽ được tự động khởi động lại. Bảng điều khiển hiển thị thời gian hoạt động và trạng thái sức khỏe của mọi dịch vụ đang chạy.

**Nút Mysterium của tôi không khởi động sau khi triển khai lại. Vì sao?**

Nguyên nhân phổ biến nhất là một cổng trong dải UDP của nó đã bị một chương trình khác trên máy chủ chiếm. Docker phải giữ chỗ mọi cổng trong dải, nên chỉ một cổng bận cũng làm việc khởi động thất bại. [Chọn dải cổng UDP](mysterium-fence.md#choosing-the-udp-port-range) giải thích cách chọn một dải luôn trống.

**Bản sao qua proxy của tôi đang chạy nhưng không kiếm được gì. Vì sao?**

Proxy có thể từ chối kết nối tới máy chủ của ứng dụng kiếm tiền đó, hoặc chỉ cho phép cổng 80 và 443. **Test** (Kiểm tra) của CashPilot chỉ kiểm tra rằng proxy ra được internet. [Thăm dò máy chủ của một ứng dụng kiếm tiền qua proxy](proxies.md#probe-an-earners-servers-through-the-proxy) chỉ cách kiểm tra máy chủ và cổng của chính ứng dụng kiếm tiền đó.

**Dịch vụ nào nặng, và nên chạy chúng ở đâu?**

Các nút lưu trữ, relay và điểm thoát VPN, và tác vụ GPU dùng nhiều tài nguyên nhất. [Tính toán tài nguyên cho một máy nhỏ](fleet.md#budgeting-a-small-box) liệt kê chúng và chỉ cách đo từng container trước khi bạn quyết định.

<a id="worker-lost-docker"></a>

### Worker mất kết nối Docker sau khi cập nhật Docker { #the-worker-lost-docker-after-a-docker-update }

**Những gì bạn thấy.** Worker vẫn trực tuyến trên trang **Fleet** (Đội máy), nhưng CashPilot không thể khởi động, dừng hay cập nhật các container của nó. Trang **Fleet** (Đội máy) hiển thị **Docker unreachable** (Không kết nối được Docker) cạnh worker. Sau 10 phút, healthcheck của worker thất bại (`docker ps` hiển thị worker là `unhealthy`). Sau 30 phút, chuông thông báo và các thông báo của bạn cho biết worker không thể kết nối tới Docker. `docker logs cashpilot-socket-proxy` hiển thị `upstream Docker socket unreachable`, và với file compose hiện tại, `docker ps` hiển thị proxy là `unhealthy` trong vòng khoảng 3 phút. Các ứng dụng kiếm tiền của bạn vẫn tiếp tục chạy.

**Nguyên nhân.** Các file compose được phát hành bind file socket `/var/run/docker.sock` vào `cashpilot-socket-proxy`. Một bind file giữ đúng file đó. Một lần cập nhật Docker (ví dụ `unattended-upgrades` cài một `docker-ce` mới) khởi động lại Docker, và Docker tạo một file socket mới ở cùng đường dẫn. Khi bật live-restore của Docker, proxy vẫn chạy qua lần khởi động lại đó và giữ file cũ. Không có gì trả lời trên file cũ.

**Cách sửa nhanh.** Trên máy đó, hãy khởi động lại proxy:

```bash
docker restart cashpilot-socket-proxy
```

Việc khởi động lại bind socket mới, và worker tìm lại được Docker ở tín hiệu hoạt động tiếp theo. Bạn không cần khởi động lại worker. Trên Unraid và TrueNAS, worker tự giữ socket, nên hãy khởi động lại worker.

**Cách sửa lâu dài.** Bind thư mục chứa socket, không phải file socket. Một bind thư mục thấy ngay socket đã được thay. Trong dịch vụ `cashpilot-socket-proxy` của file compose, hãy thay dòng `- /var/run/docker.sock:/var/run/docker.sock:ro` bằng bind bên dưới, và thêm dòng `SOCKGUARD_UPSTREAM_SOCKET` vào `environment` của nó:

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

Sau đó chạy `docker compose up -d`. Thay đổi tương tự dùng được trong `docker-compose.worker.yml` và `docker-compose.fleet.yml`. Compose chỉ đọc các file đó khi bạn chỉ định tên chúng, nên hãy chạy `docker compose -f docker-compose.worker.yml up -d` hoặc `docker compose -f docker-compose.fleet.yml up -d`, trừ khi `COMPOSE_FILE` đã chỉ định file đó.

- `recursive: disabled` là bắt buộc. `/var/run` chứa các mount khác, ví dụ các network namespace của Docker dưới `/run/docker/netns` và `/run/user/...`. Một bind đệ quy đưa tất cả chúng vào proxy. Một bind không đệ quy chỉ hiển thị chính thư mục đó.
- `SOCKGUARD_UPSTREAM_SOCKET` hướng proxy tới đường dẫn mới. Khối chính sách và dấu vân tay của nó giữ nguyên, vì biến môi trường ghi đè `upstream.socket` trong chính sách. Không có biến này, proxy không khởi động (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` có thể giữ bind file của nó. Nó khởi động lại ở mỗi lần `docker compose up`, nên nó luôn nhận socket hiện tại. Nếu bạn cho nó cùng bind thư mục, hãy thêm `DOCKER_HOST=unix:///host-run/docker.sock` vào `environment` của nó. Worker 2.8.4 trở lên đọc biến đó. Đừng bao giờ trỏ nó vào socket của proxy: trình di chuyển dữ liệu cần socket của chính máy chủ.
- Bind thư mục cho proxy mọi socket trong `/var/run`, không chỉ của Docker. Trên một máy chủ thông thường, điều đó bao gồm socket của chính systemd, D-Bus, và socket của các công cụ như Tailscale hoặc snapd. `read_only` không ngăn một chương trình kết nối tới socket, và proxy chạy với quyền root. Quyền truy cập Docker socket vốn đã tương đương quyền root trên máy chủ, nên một proxy bị xâm nhập cũng không có thêm bao nhiêu so với trước. Nếu bạn muốn proxy chỉ giữ Docker socket, hãy giữ bind file và khởi động lại proxy sau mỗi lần cập nhật Docker: cảnh báo ở trên sẽ cho bạn biết khi nào.
- Nó cần Docker Compose 2.30.0 trở lên. Các bản cũ hơn từ chối toàn bộ file với `Additional property recursive is not allowed`. Chạy `docker compose version` để kiểm tra. Debian 13 đóng gói Compose 2.26.1, nên trên Debian hãy cài Compose từ kho riêng của Docker. Bản cập nhật trong ứng dụng dùng Compose 2.33 của riêng nó, nên nó đọc được file đã sửa.
- Nó chỉ hoạt động trên Linux. Docker Desktop trên macOS và Windows chỉ ánh xạ `/var/run/docker.sock` vào máy ảo của nó. Ở đó, `/var/run` là một thư mục trên máy Mac hoặc PC của bạn, không có Docker socket nào bên trong.
- Với Docker rootless, socket nằm trong `/run/user/<your uid>`, đây là một mount riêng. Hãy dùng thư mục đó làm `source`.
- Trên Podman, hãy giữ bind file. Chúng tôi chưa thử nghiệm bind thư mục ở đó.

Các file được phát hành giữ bind file, vì bind thư mục cần Compose 2.30 và Linux, trong khi CashPilot còn hỗ trợ các bản Compose cũ hơn và Docker Desktop. Một file compose mới hơn mà bạn tải về sẽ không có thay đổi của bạn, nên hãy làm lại thay đổi đó sau khi thay file.
