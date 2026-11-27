---
source_hash: 1a93abea95d7
---

# CashPilot เทียบกับเครื่องมืออื่น { #how-cashpilot-compares }

หน้านี้เปรียบเทียบ CashPilot กับโปรเจกต์เปิดอื่น ๆ ที่รันแอปรายได้แบบพาสซีฟหลายตัวใน Docker เราตรวจสอบทุกโปรเจกต์เมื่อวันที่ 2026-11-04 ทุกช่องที่เกี่ยวกับโปรเจกต์อื่นลิงก์ไปยังไฟล์ที่เป็นที่มา ณ commit ที่ระบุแน่นอน เพื่อให้ตรวจสอบเองได้ หากช่องใดผิดหรือล้าสมัย โปรด [เปิด issue](https://github.com/GeiserX/CashPilot/issues)

## โปรเจกต์ที่เปรียบเทียบ { #projects-compared }

| โปรเจกต์ | สิ่งที่เราตรวจสอบ | ดาว ณ 2026-11-04 | สัญญาอนุญาต |
|---|---|---|---|
| [money4band][m4b-tree] | รุ่น 5.0.0, commit ของแท็ก `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` ที่ `65e900d` (2026-10-20) รวมถึงสิ่งที่ README อ้างเกี่ยวกับไบนารี 3.0.0-beta.9 | 238 | กรรมสิทธิ์เฉพาะ, [สัญญาอนุญาตของตัวเอง v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` ที่ `db9338a` (2026-11-03) | 257 | ไม่มีไฟล์ LICENSE [README][ii-license] อนุญาตให้คัดลอกต้นฉบับ แต่ห้ามแจกจ่ายสำเนาที่แก้ไข |
| [CashFactory][cf-tree] | `main` ที่ `0ff4bd0` (2025-04-08) | 410 | ไฟล์ [LICENSE][cf-license-file] เป็น GPL-3.0 แต่ [README][cf-license] ห้ามแจกจ่ายสำเนาที่แก้ไข |
| [home-assistant-passive-income][ha-tree] (HA add-ons) | รุ่น 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | รุ่น v1.64.0, `main` ที่ `c7a12bd` (2026-11-04) | 77 | GPL-3.0 |

money4band มีโค้ดสองสาย branch เริ่มต้น `main` (`3bfafb1`) ยังเป็นโค้ด 4.x และมีการเปลี่ยนโค้ดครั้งสุดท้ายที่นั่นเมื่อ 2026-03-03 รุ่น 5.0.0 สร้างจากประวัติที่แยกต่างหาก เราเปรียบเทียบ 5.0.0 เพราะเป็นสิ่งที่รุ่นล่าสุดเผยแพร่

เว็บ UI การจัดการกลุ่มเครื่อง และไบนารีตัวติดตั้งของ IGM เป็นโค้ดปิดและไม่อยู่ในที่เก็บโค้ด ช่องใดที่ขึ้นอยู่กับส่วนเหล่านี้จะระบุว่า "README อ้าง" และลิงก์ไปยังบรรทัดใน README ส่วนอื่นทั้งหมดในคอลัมน์ของ IGM มาจาก shell script และไฟล์ compose ในที่เก็บโค้ด

ที่ไม่ได้รวมไว้: [earning-machine](https://github.com/jf-m/earning-machine) และ [passiveMachine](https://github.com/Xpl0itU/passiveMachine) ไม่มี commit เลยตั้งแต่ปี 2024 การค้นหาบน GitHub ไม่พบโปรเจกต์อื่นที่ยังดูแลอยู่และรันแอปมากกว่าหนึ่งตัว มีเพียงอิมเมจแอปเดี่ยว

## ฉบับย่อ { #short-version }

- **InternetIncome, money4band, IGM และ CashPilot ตั้งแต่ v1.69.0 หารายได้จากหลาย IP ผ่านพร็อกซีได้** สามโปรเจกต์แรกรันแต่ละแอปหนึ่งครั้งต่อหนึ่งพร็อกซี และพร็อกซีเป็นฟีเจอร์หลักของ InternetIncome ส่วน CashPilot รันสำเนาเพิ่มของบริการที่ติดตั้งใช้งานบนเวิร์กเกอร์อยู่แล้ว แต่ละสำเนาผ่านพร็อกซี SOCKS5, HTTP CONNECT หรือ Tailscale exit node ([สำเนาผ่านพร็อกซี](proxies.md))
- **InternetIncome (23) เริ่มแอปได้มากกว่าเวิร์กเกอร์ของ CashPilot (<!-- n:docker -->21<!-- /n -->) ส่วน IGM เริ่มได้ 20** CashPilot ติดตามบริการโดยรวมได้มากกว่า (<!-- n:live -->50<!-- /n -->) เพราะติดตามบริการแบบส่วนขยายเบราว์เซอร์ เดสก์ท็อป และ GPU ที่ไม่ได้รันเองด้วย ตั้งแต่ v1.64.0 ยังรันอิมเมจใดก็ได้ที่ระบุเป็น [บริการแบบกำหนดเอง](custom-services.md)
- **money4band และ IGM เคลมรางวัลรายวันให้ และอัปเดตอิมเมจแอปด้วย Watchtower** CashPilot ไม่ทำทั้งสองอย่าง จะดึงอิมเมจใหม่เฉพาะเมื่อติดตั้งใช้งานหรือติดตั้งใช้งานใหม่
- **CashPilot เป็นโปรเจกต์เดียวในที่นี้ที่อ่านยอดคงเหลือจากบัญชีผู้ให้บริการและเก็บประวัติไว้** money4band 5.0.0 แสดงค่าประมาณจากแคตตาล็อกของตัวเอง ไม่ใช่จากบัญชี ส่วนโปรเจกต์อื่นลิงก์ไปยังแดชบอร์ดของผู้ให้บริการแต่ละราย
- **CashPilot เป็นโปรเจกต์โอเพนซอร์สเดียวในที่นี้ที่มี UI เดียวสำหรับหลายเซิร์ฟเวอร์** README ของ IGM อ้างว่ามีการจัดการกลุ่มเครื่อง แต่โค้ดนั้นอยู่ในไบนารีปิด
- **ตั้งแต่ v1.70.0 CashPilot เป็นโปรเจกต์เดียวในที่นี้ที่กันคอนเทนเนอร์แอปหารายได้ออกจาก LAN เป็นค่าเริ่มต้น โดยมีข้อจำกัด** เปิดใช้สำหรับการติดตั้งใหม่ และสำหรับการติดตั้งที่อัปเกรดแล้วซึ่งไม่มีแอปหารายได้อยู่บน bridge เริ่มต้นของ Docker การติดตั้งที่อัปเกรดแล้วซึ่งแอปหารายได้อยู่บน bridge นั้นอยู่แล้วจะยังอยู่ที่นั่นจนกว่าจะเปิดการแยก และเครือข่ายที่ระบุใน `CASHPILOT_CONTAINER_NETWORK` จะไม่ได้รับรั้วกั้นจาก CashPilot ([การแยก](isolation.md#modes)) ตั้งแต่ 2.0.7 Mysterium ก็รันหลังรั้วกั้นด้วย โหนดที่ติดตั้งใช้งานด้วย 2.0.6 หรือก่อนหน้าจะอยู่บนเครือข่ายของโฮสต์โดยไม่มีรั้วกั้น จนกว่าจะติดตั้งใช้งานใหม่ ([Mysterium หลังรั้วกั้น](mysterium-fence.md))

## เทียบกันทีละด้าน { #side-by-side }

คอลัมน์ของ CashPilot อธิบาย v1.64.0 ยกเว้นแถวพร็อกซี Docker socket และการแยก LAN ซึ่งอธิบาย v1.71.1 (`0170dee`, 2026-11-06) และเครือข่ายของ Mysterium ในแถวการตั้งค่าคอนเทนเนอร์และการแยก LAN ซึ่งอธิบายรุ่นถัดจาก 2.0.6 (`01e7310`) แถวการเรียกออกภายนอกรวมการเรียก explorer ใน [คู่มือบนเชนฉบับปัจจุบัน](onchain.md) ด้วย คอลัมน์อื่นอธิบาย commit ในตารางด้านบน

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA add-ons |
|---|---|---|---|---|---|---|
| แอปที่เริ่มได้ (ดู [วิธีที่เรานับ](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> รันโดยเวิร์กเกอร์ รวมถึง [อิมเมจแบบกำหนดเอง](custom-services.md) ติดตามทั้งหมด <!-- n:live -->50<!-- /n --> | 15 ([แคตตาล็อก][m4b-catalog]) README ระบุ 35 ซึ่ง [รวม][m4b-readme-35] แอปของชุมชนและแอปที่เลิกใช้แล้ว | 20 ([apps.json][igm-apps]) | 23 ([สคริปต์][ii-script]) | 11 ([ไฟล์ compose][cf-compose]) | 10 ([โฟลเดอร์ add-on][ha-tree]) |
| วิธีติดตั้ง | Docker Compose: UI หนึ่งตัวและเวิร์กเกอร์บนแต่ละเซิร์ฟเวอร์ เวิร์กเกอร์เริ่มแอปหารายได้ผ่าน Docker API ([กลุ่มเครื่อง](fleet.md)) | Python CLI หรือไบนารีที่ build ไว้แล้วซึ่งเขียนไฟล์ compose ([รุ่น][m4b-tree]) | ตัวติดตั้ง `curl \| sh` ([README][igm-install]) ที่ดาวน์โหลดไบนารีปิด ซึ่งตรวจสอบกับไฟล์ SHA256SUMS จากรุ่นเดียวกันเท่านั้น ([ตัวติดตั้ง][igm-installer-sums]) | bash script ไฟล์เดียวยาว 1,608 บรรทัดที่เรียก `sudo docker run` ([สคริปต์][ii-script]) | ไฟล์ compose แบบคงที่ และ `setup.sh` ที่รันด้วย sudo ([setup][cf-setup]) | ที่เก็บ add-on ของ Home Assistant ต้องใช้ Home Assistant OS หรือ Supervised |
| หลายเซิร์ฟเวอร์ มุมมองเดียว | ได้ ([กลุ่มเครื่อง](fleet.md)) | ไม่ได้ หนึ่ง stack ต่อหนึ่งอุปกรณ์ | README อ้างว่าได้ อยู่ในไบนารีปิด ([README][igm-features]) | ไม่ได้ | ไม่ได้ | ไม่ได้ |
| หลายพร็อกซีหรือหลาย IP | ได้ ตั้งแต่ v1.69.0: สำเนาเพิ่มของบริการที่ติดตั้งใช้งานแล้ว แต่ละสำเนาผ่านพร็อกซี SOCKS5, HTTP CONNECT หรือ Tailscale exit node โดย SOCKS5 และ HTTP CONNECT ส่งได้เฉพาะ TCP (ทันเนลปล่อยออกเฉพาะ TCP ไปยังพอร์ตของพร็อกซี การ relay UDP ของ SOCKS5 จึงถูกทิ้ง) ส่วน Tailscale exit node ส่ง UDP ได้ด้วย แอปหารายได้ใช้ network namespace ร่วมกับคอนเทนเนอร์ทันเนล ซึ่งไฟร์วอลล์ปล่อยออกเฉพาะ loopback ทันเนล และการเชื่อมต่อของทันเนลเองไปยังพร็อกซี (TCP ไปยังที่อยู่และพอร์ตของพร็อกซี หรือแพ็กเก็ตที่ tailscaled ทำเครื่องหมายไว้) พร็อกซีที่ใช้งานไม่ได้จึงหยุดแอปแทนที่จะรั่ว ([สำเนาผ่านพร็อกซี](proxies.md#how-it-works), [โค้ด][cp-proxy-deploy], [ไฟร์วอลล์ของทันเนล][cp-tunnel-fw]) บริการที่ต้องใช้ host networking พอร์ตที่เผยแพร่ volume อุปกรณ์ หรือ `NET_ADMIN`, `NET_RAW` หรือ `SYS_ADMIN` จะรันผ่านพร็อกซีไม่ได้ ([สำเนาผ่านพร็อกซี](proxies.md#what-cannot-run-through-a-proxy)) | ได้ ([README][m4b-features], [โค้ด][m4b-multiproxy]) | ได้ ([README][igm-features], [compose][igm-proxy]) | ได้ เป็นฟีเจอร์หลัก ([README][ii-readme-top]) | ไม่ได้ | ไม่ได้ |
| รายได้ | ตัวเก็บข้อมูล <!-- n:collectors -->20<!-- /n --> ตัวอ่านยอดคงเหลือจากบัญชีผู้ให้บริการและเก็บประวัติไว้ บางตัวต้องใช้คุกกี้หรือโทเค็นที่คัดลอกจากเบราว์เซอร์ และบางรายการหมดอายุ (ดูคู่มือของแต่ละบริการ) | ค่าประมาณจากช่วงในแคตตาล็อก ไม่ใช่ข้อมูลบัญชี ([โค้ด][m4b-earnings]) | ไม่พบในสคริปต์ | ไม่มี | ไม่มี | ไม่มี |
| การจ่ายเงิน | เสนอรายการจ่ายเงินเมื่อยอดคงเหลือลดลง และบันทึกเมื่อยืนยัน ([schema][cp-payouts]) | ไม่มี | ไม่มี | ไม่มี | ไม่มี | ไม่มี |
| การเคลมรางวัลรายวัน | ไม่มี | มี ใช้ sidecar ([README][m4b-features]) | มี ([README][igm-features], [compose][igm-sidecars]) | ไม่มี | ไม่มี | ไม่มี |
| ข้อมูลรับรองขณะจัดเก็บ | เข้ารหัส (Fernet) ในฐานข้อมูลของ UI ไฟล์คีย์อยู่ใน data volume เดียวกัน ([โค้ด][cp-fernet]) ข้อมูลรับรองของแอปหารายได้ไปถึงเวิร์กเกอร์แต่ละตัวเป็นตัวแปรสภาพแวดล้อมของคอนเทนเนอร์ จึงเป็นข้อความธรรมดาในการกำหนดค่า Docker ของเวิร์กเกอร์นั้น (`docker inspect`) | เข้ารหัส (Fernet) ไฟล์คีย์อยู่ในไดเรกทอรีข้อมูล ([โค้ด][m4b-crypto]) | เข้ารหัส (AES-256 ด้วย openssl) ไฟล์คีย์อยู่ข้าง vault ([โค้ด][igm-encryptor]) | ข้อความธรรมดาใน `properties.conf` รหัสผ่านบางรายการส่งเป็นอาร์กิวเมนต์ของ `docker run` ([สคริปต์][ii-password-arg]) | ข้อความธรรมดาใน `.env` ([ไฟล์][cf-env]) | ตัวเลือกของ add-on ซึ่ง Supervisor จัดเก็บใน `/data/options.json` ([เอกสาร HA][ha-options]) |
| การตั้งค่าคอนเทนเนอร์แอปหารายได้ | ตัด capability ทั้งหมดออก แล้วแคตตาล็อกเพิ่มกลับเฉพาะที่บริการต้องการ, `no-new-privileges`, จำกัดจำนวน pids, ปฏิเสธ privileged ([โค้ด][cp-hardening], [โค้ด][cp-privileged]) Mysterium รันใน network namespace ของตัวเองบน bridge ที่มีรั้วกั้น พร้อม `NET_ADMIN`, `SETUID` และ `SETGID` บนอิมเมจที่ปักหมุดด้วย digest ([แคตตาล็อก][cp-myst]) | `no-new-privileges` ในทุกบริการที่ไม่ใช่ privileged ([โค้ด][m4b-nnp]) คอนเทนเนอร์พร็อกซีเป็น privileged พร้อม `NET_ADMIN` ([เทมเพลต][m4b-tun]) | ไม่ได้ตั้งค่าใดในบริการแอป Mysterium ได้ `NET_ADMIN` ([compose][igm-hosting-myst]) คอนเทนเนอร์พร็อกซีได้ `NET_ADMIN` พร้อม `no-new-privileges` และจำกัดจำนวน pids ([compose][igm-proxy]) | Ebesucher รันด้วย `seccomp=unconfined` ([สคริปต์][ii-seccomp]) คอนเทนเนอร์พร็อกซีและ Mysterium ได้ `NET_ADMIN` | ไม่ได้ตั้งค่าใด | ไม่มี add-on ใดขอ privileged, host network หรือการเข้าถึง Docker API ([ตัวอย่างการกำหนดค่า][ha-config]) |
| Docker socket ถูก mount เข้า | ตั้งแต่ v1.71.0 เข้า socket proxy (sockguard 2.4.5 ปักหมุดด้วย digest) แบบอ่านอย่างเดียว เวิร์กเกอร์ได้สำเนาที่กรองแล้ว ซึ่งปฏิเสธคอนเทนเนอร์แบบ privileged การ bind `/` หรือ socket และ capability หรืออุปกรณ์ที่อยู่นอกแคตตาล็อก ([compose][cp-sock], [รายละเอียด](security-defaults.md)) ไม่เคยเข้าแอปหารายได้ ([โค้ด][cp-mounts]) | Watchtower ([เทมเพลต][m4b-watchtower]) | Watchtower ซึ่งเป็นแบบอ่านอย่างเดียวพร้อม `no-new-privileges` ([compose][igm-watchtower]) | คอนเทนเนอร์ผู้ช่วยรีสตาร์ตห้าตัว ([สคริปต์][ii-sock-helper]) และ Watchtower ([สคริปต์][ii-watchtower]) | Portainer ซึ่งเผยแพร่บนพอร์ต 8000, 9000 และ 9443 บนทุกอินเทอร์เฟซ ([compose][cf-portainer]) และ Watchtower สองตัว ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | ไม่มี |
| แท็กอิมเมจ | อิมเมจแอปหารายได้ 9 จาก <!-- n:docker -->21<!-- /n --> ปักหมุดกับเวอร์ชันหรือ digest ที่เหลือเปลี่ยนตามแท็ก | อิมเมจแอปทั้ง 15 ใช้ `:latest` ([ตัวอย่าง][m4b-image]) คอนเทนเนอร์พร็อกซีปักหมุดที่ v2.6.0, Watchtower ที่ `:1` | ไม่มีแท็ก Docker จึงใช้ `latest` ([compose][igm-hosting]) ตั้งแท็กเฉพาะบาง build สำหรับ ARM | ส่วนใหญ่ `:latest` ([ตัวอย่าง][ii-seccomp]) EarnApp `:lite`, Honeygain ปักหมุดที่ 0.6.6 เมื่อผ่านพร็อกซีบน amd64 ([สคริปต์][ii-honeygain]) Traffmonetizer ใช้แท็กแยกตามสถาปัตยกรรมบน ARM, Watchtower `:nightly` | `:latest` หรือไม่มีแท็ก ยกเว้น EarnApp `:lite` ([compose][cf-compose]) | หนึ่งเวอร์ชันต่อ add-on ปรับขึ้นโดยงาน CI รายวัน ([workflow][ha-bump], [ตัวอย่าง][ha-dockerfile]) |
| การอัปเดตอิมเมจแอป | ดึงใหม่ทุกครั้งที่ติดตั้งใช้งานหรือติดตั้งใช้งานใหม่ ไม่มีตัวอัปเดตอัตโนมัติ | Watchtower ([เทมเพลต][m4b-watchtower]) | Watchtower ทุก 4 ชั่วโมง ([compose][igm-watchtower]) | Watchtower วันละครั้ง หากเปิดใช้ ([สคริปต์][ii-watchtower]) | Watchtower สองตัว แต่ละตัวจำกัดไว้กับแอปเดียว คือ PacketStream ([compose][cf-watchtower-ps]) และ EarnFM ([compose][cf-watchtower-efm]) แอปอีก 9 ตัวไม่ได้รับการอัปเดต | การอัปเดต add-on ของ Home Assistant |
| การแยก LAN | เปิดเป็นค่าเริ่มต้นตั้งแต่ v1.70.0 สำหรับการติดตั้งใหม่ และสำหรับการติดตั้งที่อัปเกรดแล้วซึ่งไม่มีแอปหารายได้อยู่บน bridge เริ่มต้นของ Docker: เวิร์กเกอร์วางแอปหารายได้ไว้บน bridge ของตัวเอง และเขียนตารางไฟร์วอลล์ที่ทิ้งช่วง IP ส่วนตัว ช่วงของ tailnet, cloud metadata, subnet ที่เชื่อมต่อกับโฮสต์ ตัวโฮสต์เอง และเมื่อเปิดการตรวจหา IP สาธารณะไว้ ก็รวม IP สาธารณะของบ้านด้วย ([การแยก](isolation.md#lan-isolation-by-default), [โค้ด][cp-fence]) การติดตั้งที่อัปเกรดแล้วซึ่งแอปหารายได้อยู่บน bridge เริ่มต้นอยู่แล้วจะยังอยู่ที่นั่นจนกว่าจะกด **Turn on isolation** (เปิดการแยก) `CASHPILOT_ISOLATION=off` ปิดการแยก เมื่อตั้งค่า `CASHPILOT_CONTAINER_NETWORK` ไว้ CashPilot จะไม่เขียนรั้วกั้นให้เครือข่ายนั้น และกฎไฟร์วอลล์เป็นหน้าที่ของคุณ ([การแยก](isolation.md#modes), [โค้ด][cp-fence-mode]) ตั้งแต่ 2.0.7 Mysterium ก็มีรั้วกั้นด้วย โหนดที่ติดตั้งใช้งานด้วย 2.0.6 หรือก่อนหน้าจะอยู่บนเครือข่ายของโฮสต์จนกว่าจะติดตั้งใช้งานใหม่ ([Mysterium หลังรั้วกั้น](mysterium-fence.md)) มีการตรวจสอบที่แสดงว่าแอปหารายได้เข้าถึงอะไรได้บ้าง ([การตรวจสอบ](isolation-check.md)) | subnet ของ bridge ของตัวเอง ([การกำหนดค่า][m4b-subnet]) ซึ่งไม่ได้กั้น LAN | ยังไม่ได้ merge | ไม่พบ | ไม่พบ | ไม่พบ |
| ARM | UI และเวิร์กเกอร์สำหรับ arm64 ตรวจสอบแพลตฟอร์มของแต่ละบริการก่อนติดตั้งใช้งาน ([ARM](arm.md)) | ไบนารี arm64 และ armv7 ([รุ่น][m4b-release]) | README อ้างว่ารองรับ amd64 และ arm64, arm32 แบบมีข้อจำกัด และตั้งค่า QEMU ให้ ([README][igm-arch]) | ต้องใช้การจำลอง binfmt สำหรับอิมเมจที่มีเฉพาะ amd64 ([README][ii-arm]) | README ระบุว่าใช้กับ Raspberry Pi ไม่ได้ ([README][cf-raspberry]) | แยกตาม add-on ProxyRack มีเฉพาะ amd64 ([การกำหนดค่า][ha-proxyrack]) |
| UI | เว็บ UI รวมถึงไคลเอนต์ Desktop, Android, MCP และ Home Assistant | CLI เมนู และแดชบอร์ดเว็บในเครื่องที่ผูกกับ 127.0.0.1 เป็นค่าเริ่มต้น ([โค้ด][m4b-bind]) | CLI เมนู และตาม README มีเว็บ UI บนพอร์ต 4747 ที่เข้าถึงได้จาก LAN ([README][igm-webui]) | ไม่มี เป็นสคริปต์ | หน้าบุ๊กมาร์กบนพอร์ต 80 รวมถึง Portainer ([README][cf-ui]) | แผง add-on ของ Home Assistant |
| commit บน branch เริ่มต้น 2026-08-06 ถึง 2026-11-04 | 286 | 6 เป็นเอกสารทั้งหมด (5.0.0 อยู่บนประวัติที่แยกต่างหาก) | 6 | 31 | 0 | 23 |
| รุ่นล่าสุด | v1.64.0, 2026-11-04 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | ไม่มีรุ่นที่มีเวอร์ชัน | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| การเรียกออกภายนอกนอกเหนือจากแอป | GitHub releases วันละครั้ง (`CASHPILOT_UPDATE_CHECK=off` หยุดได้, [โค้ด][cp-update]) `api.ipify.org`, `ifconfig.me` หรือ `icanhazip.com` ชั่วโมงละครั้งจากแต่ละเวิร์กเกอร์ เพื่อหา IP สาธารณะ (`CASHPILOT_EGRESS_DETECT=off` หยุดได้, [โค้ด][cp-egress]) CoinGecko และ Frankfurter สำหรับอัตราแลกเปลี่ยน ([โค้ด][cp-rates]) mempool.space, api.kaspa.org และโหนด RPC สาธารณะของ Ethereum, Polygon และ Solana สำหรับ [ยอดคงเหลือบนเชน](onchain.md) และผู้ให้บริการแต่ละรายสำหรับตัวเก็บข้อมูล เบราว์เซอร์โหลด Google Fonts ([เทมเพลต][cp-cdn]) และ Chart.js จาก jsDelivr ([เทมเพลต][cp-chartjs]) | GitHub releases สำหรับการตรวจหาอัปเดต ([โค้ด][m4b-updater]) Docker Hub และ ghcr.io เพื่อตรวจสอบแท็กอิมเมจ ([โค้ด][m4b-registry]) เมื่อรันการตรวจสอบ IP จะใช้ `api.ipify.org`, `ifconfig.me` หรือ `icanhazip.com` เพื่อหา IP สาธารณะ และ `ip-api.com` ผ่าน HTTP ธรรมดาเพื่อหาคะแนน IP ([โค้ด][m4b-ipscore]) | GitHub releases ([โค้ด][igm-version]) `api.ipify.org`, `ifconfig.me` หรือ `icanhazip.com` เพื่อหา IP สาธารณะ ([โค้ด][igm-ifconfig]) `ip-api.com` ผ่าน HTTP ธรรมดาเพื่อหาคะแนน IP ([โค้ด][igm-ipscore]) ไม่ได้ตรวจสอบไบนารีปิด | ไม่พบ | ไม่พบ | ไม่พบ |

ไม่มีโปรเจกต์ใดส่งข้อมูลการใช้งาน (telemetry) ในโค้ดที่เราอ่าน ส่วนไบนารีปิดของ IGM อ่านไม่ได้

ทุกโปรเจกต์ในที่นี้ส่งข้อมูลรับรองของแอปให้คอนเทนเนอร์เป็นตัวแปรสภาพแวดล้อม และ InternetIncome ส่งบางรายการเป็นอาร์กิวเมนต์ของคำสั่งด้วย ดังนั้นบนโฮสต์ที่รันแอป ข้อมูลเหล่านี้จึงเป็นข้อความธรรมดาในการกำหนดค่าคอนเทนเนอร์ของ Docker (`Env` และ `Args` ใน `docker inspect`) ซึ่งใครก็ตามที่เข้าถึง Docker ได้ก็อ่านได้ แถว "ข้อมูลรับรองขณะจัดเก็บ" อธิบายเฉพาะสำเนาที่จัดเก็บไว้เท่านั้น

## วิธีที่เรานับ { #how-we-counted }

- **CashPilot** บริการในแคตตาล็อกที่มีสถานะ active หรือ beta และมีอิมเมจ Docker ไม่นับการประมวลผลด้วย GPU หรือพูลการขุด ตัวเลขในหน้านี้มาจาก `scripts/generate_readme_tables.py` และ CI จะล้มเหลวหากคลาดเคลื่อน
- **money4band 5.0.0** ไฟล์ JSON หนึ่งไฟล์ต่อแอปใน `config/catalog/supported/`: 15 "35 apps" ใน README นับแคตตาล็อกของชุมชนซึ่งปิดไว้เป็นค่าเริ่มต้นด้วย ([การกำหนดค่า][m4b-community]) รวมถึงแอปที่ไม่มีอิมเมจ Docker และแอปที่เลิกใช้แล้ว
- **IGM** รายการใน `apps.json`: 20 เปิดใช้ทั้งหมด ไม่นับคอนเทนเนอร์พร็อกซี Watchtower และ sidecar สำหรับเคลม
- **InternetIncome** บล็อกความคิดเห็น `# Starting ... container` แต่ละบล็อกใน `internetIncome.sh` ยกเว้นบล็อกพร็อกซีและ Watchtower: 24 บล็อก Chrome และ Firefox ของ Ebesucher นับเป็นแอปเดียว EarnFM และ EarnFM Fleetshare ซึ่งใช้บัญชี EarnFM เดียวกันก็นับเป็นแอปเดียวเช่นกัน บล็อกส่วนขยาย Depin เริ่ม Grass และ Gradient ([สคริปต์][ii-depin]) ซึ่งเป็นสองแอป รวม 23 ตารางใน README แสดง 27 แอป บางแอปมีเพียงลิงก์สมัคร
- **CashFactory** บริการหารายได้ใน `docker-compose.yml`: 11 ไม่นับ Portainer เว็บเซิร์ฟเวอร์ และ Watchtower สองตัว มีบริการหนึ่งที่ถูกคอมเมนต์ไว้
- **HA add-ons** โฟลเดอร์ add-on ที่มีไฟล์การกำหนดค่า: 10

เราไม่ได้ตรวจสอบว่าแต่ละแอปในแต่ละรายการยังจ่ายเงินอยู่หรือไม่

## จุดที่ CashPilot ยังตามหลัง { #where-cashpilot-is-behind }

- บริการที่ต้องใช้ host networking พอร์ตที่เผยแพร่ volume อุปกรณ์ หรือ capability ด้านเครือข่ายเพิ่มเติม จะรันผ่านพร็อกซีไม่ได้ ดังนั้น 10 จาก <!-- n:docker -->21<!-- /n --> (EarnApp, URnetwork, ProxyBase Markets, Bitping, Mysterium, Storj, Sia, Anyone Protocol, SRBMiner-Multi และ Kryptex Pool (Pearl)) หารายได้ได้จาก IP ของเซิร์ฟเวอร์เองเท่านั้น ([สำเนาผ่านพร็อกซี](proxies.md#what-cannot-run-through-a-proxy))
- แอปที่เริ่มเองได้มีน้อยกว่า InternetIncome
- ไม่มีการเคลมรางวัลรายวัน และไม่มีการอัปเดตอิมเมจอัตโนมัติ
- อิมเมจแอปหารายได้ 12 จาก <!-- n:docker -->21<!-- /n --> เปลี่ยนตามแท็ก latest ของผู้เผยแพร่
- socket proxy ยังไม่ใช่ขอบเขตระดับ root: เวิร์กเกอร์ที่ถูกเจาะยังสร้างคอนเทนเนอร์ภายในนโยบายของตัวเองได้ และการหลบหนีแบบสองขั้น (การเข้าร่วม process namespace ของคอนเทนเนอร์อื่น, symlink ในโฟลเดอร์ที่อนุญาต) ยังไม่ถูกปฏิเสธ ([รายละเอียด](security-defaults.md))
- คีย์เข้ารหัสของข้อมูลรับรองที่จัดเก็บไว้อยู่ใน volume เดียวกับข้อมูล และบนเวิร์กเกอร์แต่ละตัว ข้อมูลรับรองของแอปหารายได้เป็นข้อความธรรมดาในการกำหนดค่าคอนเทนเนอร์ของ Docker
- ตัวเก็บข้อมูลบางตัวต้องใช้คุกกี้หรือโทเค็นที่คัดลอกจากเบราว์เซอร์ และบางรายการหมดอายุ การติดตามรายได้ของบริการเหล่านั้นจึงต้องดูแลอยู่เรื่อย ๆ
- UI โหลดฟอนต์และ Chart.js จาก CDN ของบุคคลที่สาม
- การแยก LAN ยังปิดอยู่ในการติดตั้งที่อัปเกรดแล้วซึ่งแอปหารายได้อยู่บน bridge เริ่มต้นของ Docker จนกว่าจะเปิดเอง ไม่มีรั้วกั้นให้เครือข่ายที่ระบุใน `CASHPILOT_CONTAINER_NETWORK` ([การแยก](isolation.md#modes)) และโหนด Mysterium ที่ติดตั้งใช้งานด้วย 2.0.6 หรือก่อนหน้าจะอยู่บนเครือข่ายของโฮสต์โดยไม่มีรั้วกั้น จนกว่าจะติดตั้งใช้งานใหม่ ([Mysterium หลังรั้วกั้น](mysterium-fence.md))
- ชุมชนเล็กกว่าของ money4band มาก
- ออกรุ่นใหม่บ่อย บางครั้งหลายครั้งต่อวัน

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

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L515-L531
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L48
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/orchestrator.py#L745-L752
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L1244
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L992-L1040
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/01e7310cf1d923ba35523d8944ebaf2478f39079/services/bandwidth/mysterium.yml#L19-L113
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/docker-compose.yml#L69-L106
[cp-update]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/update_check.py#L80
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/exchange_rates.py#L101-L119
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L313
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L254
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/proxy_tunnel.py#L336-L350
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/tunnel/cp-tunnel#L48-L99
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L83-L100
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L630-L646
