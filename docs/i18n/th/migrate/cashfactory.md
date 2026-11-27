---
source_hash: 7f8476aeb8b6
---

# ย้ายมาจาก CashFactory { #moving-from-cashfactory }

CashPilot อ่าน `.env` ของ CashFactory และนำข้อมูลเข้าสู่ระบบของบริการต่าง ๆ มาได้
จึงไม่ต้องพิมพ์ใหม่ คุณตรวจสอบทุกอย่างก่อนที่ CashPilot จะบันทึก

## ก่อนเริ่ม { #before-you-start }

ต้องมีบัญชีเจ้าของของ CashPilot และเวิร์กเกอร์ของ CashPilot อย่างน้อยหนึ่งตัว

หยุด CashFactory บนเครื่องนั้นก่อนติดตั้งใช้งานบริการเดียวกันที่นั่นจาก
CashPilot สองสำเนาที่อยู่หลังการเชื่อมต่อเดียวกันหารายได้ได้เท่ากับสำเนาเดียว และ id อุปกรณ์
ของ EarnApp เดียวกันต้องไม่รันสองครั้ง รัน `docker compose down` ในโฟลเดอร์
CashFactory
[ไฟล์ compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
ของ CashFactory ยังเริ่มคอนเทนเนอร์อีกสามตัวที่ mount Docker socket ได้แก่ Portainer (บรรทัด 31)
และคอนเทนเนอร์ Watchtower สองตัว (บรรทัด 141 และ 264) ตรวจสอบให้แน่ใจว่าคอนเทนเนอร์เหล่านี้หายไปแล้วด้วย: `docker ps` ต้อง
ไม่แสดงตัวใดเลย

## ใช้ไฟล์ใด { #which-file-to-use }

ใช้ไฟล์ `.env` ในโฟลเดอร์ CashFactory ซึ่งเป็นไฟล์ที่กรอกจาก
[ตัวอย่าง](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env)

Docker Compose อ่านไฟล์นั้น และขยาย `$` ในค่าที่ไม่ได้อยู่ใน
เครื่องหมายคำพูดเดี่ยว ค่าแบบนั้นไม่ใช่สิ่งที่ไฟล์แสดง CashPilot จึงขอให้
พิมพ์ใหม่แทนที่จะเดา

## วิธีนำเข้า { #how-to-import }

1. เปิด **Settings** (การตั้งค่า) แล้วไปที่ **Import from another tool** (นำเข้าจากเครื่องมืออื่น) (หรือไปที่ `/import`)
2. เพิ่มไฟล์ `.env` หรือวางข้อความของไฟล์ ปล่อยเครื่องมือไว้ที่ **Tell from the
   files** (ระบุจากไฟล์) หรือเลือก CashFactory
3. ตรวจสอบตาราง ติ๊กบริการที่ต้องการ และกรอกค่าที่ระบุว่า
   ขาดหายไป
4. กด **Save the ticked services** (บันทึกบริการที่ติ๊กไว้) แล้วติดตั้งใช้งานบริการเหล่านั้นไปยังเวิร์กเกอร์จาก
   หน้าเดียวกัน

## สิ่งที่นำมาได้ { #what-comes-over }

| แอปของ CashFactory | คีย์ที่อ่าน | บริการของ CashPilot | สิ่งที่นำมาได้ |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | id อุปกรณ์ อุปกรณ์ที่ลิงก์ไว้จึงหารายได้ต่อได้ |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | อีเมล, รหัสผ่าน |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | อีเมล, รหัสผ่าน |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | โทเค็น |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | อีเมล, คีย์ API |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | user id |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID ของอุปกรณ์ |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | คีย์ API |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | ไม่มี: ไม่มีให้บริการแล้ว |

ค่าที่ยังเป็นตัวยึดตำแหน่งของตัวอย่าง (`<email>`, `sdk-node-<md5sum>`)
นับว่ายังไม่ได้ตั้งค่า และบริการที่มีเพียงตัวยึดตำแหน่งจะไม่แสดงใน
ตาราง

## สิ่งที่ไม่เคยนำมา { #what-never-comes-over }

- **`DEVICE_NAME`** CashPilot ตั้งชื่ออุปกรณ์แต่ละตัวตามเวิร์กเกอร์ที่รันอยู่
  เวิร์กเกอร์สองตัวจึงไม่รายงานชื่อเดียวกัน อุปกรณ์เก่าจะยังแสดงเป็น
  ออฟไลน์ในแดชบอร์ดของผู้ให้บริการแต่ละรายจนกว่าจะลบออกที่นั่น
- **Bitping** CashFactory เก็บข้อมูลเข้าสู่ระบบของ Bitping ไว้ใน Docker volume ไม่ใช่ใน
  `.env` การนำเข้าจึงไม่มีอะไรให้อ่าน และไม่แสดงแถวของ Bitping ให้พิมพ์
  ข้อมูลเข้าสู่ระบบในแบบฟอร์มติดตั้งใช้งานของ Bitping
- **Portainer และ Watchtower** CashPilot จัดการและอัปเดตคอนเทนเนอร์ของ
  ตัวเอง

## การติดตามรายได้ { #earnings-tracking }

สำหรับ Honeygain และ IPRoyal Pawns ข้อมูลเข้าสู่ระบบของคอนเทนเนอร์เป็นข้อมูลเข้าสู่ระบบของบัญชีด้วย
CashPilot จึงกรอกข้อมูลรับรองสำหรับรายได้ให้ด้วย เว้นแต่จะตั้งไว้แล้ว
ใน **Settings** (การตั้งค่า) สำหรับบริการอื่นทั้งหมด ให้เพิ่มข้อมูลเข้าสู่ระบบสำหรับรายได้ใน
**Settings > Earnings collection** (การตั้งค่า > การเก็บรายได้)

## ความปลอดภัย { #safety }

- ไม่มีสิ่งใดในไฟล์ถูกรันหรือขยาย และไม่มีที่อยู่ใดในไฟล์ถูกดึงข้อมูล
- ไฟล์ถูกอ่านครั้งเดียวและไม่ถูกเก็บไว้ สิ่งที่บันทึกจะจัดเก็บแบบเข้ารหัส เช่นเดียวกับ
  ข้อมูลรับรองอื่นทั้งหมดใน CashPilot
- ความลับแสดงบนหน้าเพียงว่า **set** (ตั้งค่าแล้ว)
- การนำเข้าที่บันทึกไว้จะอยู่ในหน้านำเข้าจนกว่าจะกด **Forget** (ลืม) จึงติดตั้งใช้งาน
  ไปยังเวิร์กเกอร์เพิ่มได้ภายหลัง
