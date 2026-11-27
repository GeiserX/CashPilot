---
source_hash: e99e2c0c80bb
---

# ร้านแอป { #app-stores }

ติดตั้ง CashPilot ได้จากร้านแอปของระบบโฮมเซิร์ฟเวอร์หลายระบบ
แต่ละรายการจะติดตั้งแดชบอร์ด (`drumsergio/cashpilot`) และเวิร์กเกอร์
(`drumsergio/cashpilot-worker`) ซึ่งเริ่มและหยุดคอนเทนเนอร์ของบริการ
มีเพียงแพ็กเกจ CasaOS และ Runtipi ในที่เก็บโค้ดนี้เท่านั้นที่ติดตั้ง
Docker socket proxy จาก `docker-compose.yml` ด้วย เวิร์กเกอร์ของแพ็กเกจเหล่านี้จึง
ไม่เคยถือ Docker socket ดิบ ส่วนเทมเพลต Unraid แอป TrueNAS และ
แพ็กเกจใน pull request ที่เปิดอยู่ของร้านแอป CasaOS ยังคง mount Docker
socket เข้าเวิร์กเกอร์โดยตรง

ไม่ว่าจะใช้ร้านแอปใด ให้เก็บแดชบอร์ดไว้ใน LAN หรือ VPN เท่านั้น แดชบอร์ดสั่งงาน
เวิร์กเกอร์ได้ และเวิร์กเกอร์ควบคุม Docker บนโฮสต์ หากเวิร์กเกอร์ถือ
socket เอง นั่นเท่ากับเป็น root บนโฮสต์

## มีให้ติดตั้งแล้ว { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

ค้นหา **CashPilot** ในแท็บ Apps แล้วติดตั้งทั้งสองเทมเพลต:
`cashpilot` (แดชบอร์ด) และ `cashpilot-worker` ตั้งค่า
`CASHPILOT_API_KEY` เดียวกันทั้งสองตัว

เทมเพลตมาจาก https://github.com/GeiserX/docker-templates และใช้
แท็กอิมเมจ `latest` ผู้ใช้ Community Applications จึงได้ทุกรุ่นใหม่
โดยไม่ต้องเปลี่ยนเทมเพลต

### TrueNAS SCALE { #truenas-scale }

CashPilot อยู่ใน train **community** ของ TrueNAS เปิด Apps แล้วไปที่ Discover Apps
และค้นหา **CashPilot**

นิยามแอปดูแลอยู่ที่
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot และปักหมุด
digest ของอิมเมจที่แน่นอน บอตของ TrueNAS เองจะย้ายไปรุ่นใหม่ จึงอาจ
ตามหลัง CashPilot รุ่นล่าสุดอยู่สองสามรุ่น

## รอการตรวจสอบ { #waiting-for-review }

### CasaOS { #casaos }

มี pull request ที่เปิดอยู่ในร้านแอป CasaOS:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

ระหว่างที่ยังไม่ถูก merge ให้ติดตั้งเป็นแอปแบบกำหนดเอง: ใน CasaOS เลือก App Store
แล้ว Custom Install แล้ว Import และวางเนื้อหาของ
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

ต้องใช้ CasaOS 0.4.5 ขึ้นไป ตั้งแต่รุ่นนั้น ตัวจัดการแอปสร้างบน
Docker Compose 2.23 ซึ่งอ่านนโยบายของ socket proxy จากไฟล์ได้
รุ่นที่เก่ากว่าจะทิ้งนโยบายนี้ไป แล้วเวิร์กเกอร์จะเข้าถึง Docker ไม่ได้

ไฟล์นั้นปักหมุดรุ่นที่แน่นอนไว้ ก่อน import ให้ตั้งแท็กอิมเมจทั้งสอง
(`drumsergio/cashpilot` และ `drumsergio/cashpilot-worker`) เป็นรุ่นล่าสุด
จาก https://github.com/GeiserX/CashPilot/releases นโยบายของ proxy
ในไฟล์ตาม `main` หากหน้าสถานะของเวิร์กเกอร์แจ้งว่านโยบาย
ล้าสมัย ให้ import ไฟล์อีกครั้ง

## เตรียมไว้แล้ว ยังไม่ได้ส่ง { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

แพ็กเกจพร้อมแล้วใน
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
แต่ยังไม่อยู่ในร้านแอป Runtipi หากต้องการใช้ตอนนี้ ให้เพิ่มเข้าร้านแอปแบบกำหนดเอง
ที่ควบคุมเอง ตามเอกสารของ Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## ไม่มีให้ติดตั้ง { #not-offered }

Umbrel ต้องใช้การออกแบบเวิร์กเกอร์แบบอื่น เพราะแอปของ Umbrel เข้าถึง Docker
ผ่านคอนเทนเนอร์ Docker-in-Docker ไม่ใช่ socket ของโฮสต์ เรายังไม่ได้
ทดสอบเรื่องนี้ จึงยังไม่มีแพ็กเกจสำหรับ Umbrel

สำหรับระบบอื่น ให้ใช้ `docker-compose.yml` จากที่เก็บโค้ด ตามที่อธิบายใน
[เริ่มต้นใช้งาน](getting-started.md)
