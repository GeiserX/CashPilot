---
source_hash: 374e39e6eac9
---

# ย้ายมาจาก money4band { #moving-from-money4band }

CashPilot อ่านการกำหนดค่าของ money4band และนำข้อมูลเข้าสู่ระบบของบริการต่าง ๆ มาได้
จึงไม่ต้องพิมพ์ใหม่ คุณตรวจสอบทุกอย่างก่อนที่ CashPilot จะบันทึก

## ก่อนเริ่ม { #before-you-start }

ต้องมีบัญชีเจ้าของของ CashPilot และเวิร์กเกอร์ของ CashPilot อย่างน้อยหนึ่งตัว บน
เครื่องที่ money4band รันอยู่ตอนนี้ หรือบนเครื่องอื่น

หยุด money4band บนเครื่องนั้นก่อนติดตั้งใช้งานบริการเดียวกันที่นั่นจาก
CashPilot สองสำเนาที่อยู่หลังการเชื่อมต่อเดียวกันหารายได้ได้เท่ากับสำเนาเดียว และ id อุปกรณ์
ของ EarnApp หรือ ProxyRack เดียวกันต้องไม่รันสองครั้ง ใช้ **Stop apps stack** ในเมนูของ
money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json))
หรือรัน `docker compose down` ในโฟลเดอร์ของ money4band หากตั้งค่าอินสแตนซ์พร็อกซี
เพิ่มไว้ ให้หยุดทุกตัวด้วย

## ใช้ไฟล์ใด { #which-file-to-use }

ใช้ `config/user-config.json` ในโฟลเดอร์ money4band ซึ่ง money4band เขียนไว้
เมื่อรัน **Setup Apps** และเก็บสิ่งที่พิมพ์ไว้ตรงตามจริง `.env`
ที่อยู่ข้างกันสร้างจากไฟล์นั้นและใช้ได้เช่นกัน รวมถึง `.env` ที่แก้ด้วยมือ
ของ money4band 3.x ทั้งสองไฟล์อยู่บนดิสก์ของคุณเท่านั้น:
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
ของ money4band ระบุไฟล์ทั้งสองไว้

ควรใช้ไฟล์ JSON ใน `.env` นั้น Docker Compose จะขยาย `$` ในค่าที่ไม่มีเครื่องหมายคำพูด
รหัสผ่านที่มี `$` จึงไม่ใช่สิ่งที่ไฟล์แสดง CashPilot ไม่เดา
แต่จะขอให้พิมพ์ค่านั้นใหม่

## วิธีนำเข้า { #how-to-import }

1. เปิด **Settings** (การตั้งค่า) แล้วไปที่ **Import from another tool** (นำเข้าจากเครื่องมืออื่น) (หรือไปที่ `/import`)
2. เพิ่ม `user-config.json` หรือวางข้อความของไฟล์ ปล่อยเครื่องมือไว้ที่ **Tell from the
   files** (ระบุจากไฟล์) หรือเลือก money4band
3. ตรวจสอบตาราง ติ๊กบริการที่ต้องการ และกรอกค่าที่ระบุว่า
   ขาดหายไป
4. กด **Save the ticked services** (บันทึกบริการที่ติ๊กไว้) แล้วติดตั้งใช้งานบริการเหล่านั้นไปยังเวิร์กเกอร์จาก
   หน้าเดียวกัน

## สิ่งที่นำมาได้ { #what-comes-over }

ชื่อฟิลด์มาจาก
[เทมเพลต user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
ของ money4band และชื่อใน `.env` ที่
[ตัวสร้าง](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
เขียนไว้ (`<APP>_<FLAG>` เช่น `REPOCKET_APIKEY`)

| แอปของ money4band | บริการของ CashPilot | สิ่งที่นำมาได้ |
|---|---|---|
| `earnapp` | EarnApp | id อุปกรณ์ (`uuid`) อุปกรณ์ที่ลิงก์ไว้จึงหารายได้ต่อได้ |
| `honeygain` | Honeygain | อีเมล, รหัสผ่าน |
| `iproyalpawns` | IPRoyal Pawns | อีเมล, รหัสผ่าน |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | โทเค็น |
| `repocket` | Repocket | อีเมล, คีย์ API |
| `earnfm` | Earn.fm | คีย์ API |
| `proxyrack` | ProxyRack | คีย์ API, UUID ของอุปกรณ์ |
| `proxylite` | ProxyLite | user id |
| `bitping` | Bitping | อีเมล, รหัสผ่าน |
| `mystnode` | Mysterium | เปิดใช้ ดูหมายเหตุเรื่อง Mysterium ด้านล่าง |

แอปที่ปิดไว้ใน money4band จะแสดงโดยไม่ได้ติ๊ก แอปที่ปิดอยู่และ
มีเพียงค่าตัวยึดตำแหน่งของเทมเพลต (`yourHONEYGAINMail`) และรายการพอร์ต
จะไม่ถูกแสดง `user-config.json` ที่ไม่ได้แก้ไขเลยจึงให้ตารางว่าง

แอปต่อไปนี้แสดงในรายการแต่ไม่ได้นำมา:

| แอปของ money4band | เหตุผล |
|---|---|
| `proxybase` | money4band รันไคลเอนต์เก่าของ ProxyBase ด้วย user id ส่วน CashPilot รันไคลเอนต์ปัจจุบัน ซึ่งต้องใช้ Access Token จาก proxybase.org |
| `urnetwork` | money4band เก็บโทเค็นเซสชันไว้ ส่วน CashPilot เข้าสู่ระบบ URnetwork ด้วยอีเมลและรหัสผ่าน |
| `grass` | Grass รันเป็นส่วนขยายเบราว์เซอร์ CashPilot เพียงติดตามด้วย access token จากแดชบอร์ดของ Grass |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot ติดตามบริการเหล่านี้ แต่ไม่มีคอนเทนเนอร์ให้ติดตั้งใช้งาน |
| `packetshare`, `peer2profit`, `speedshare` | ไม่มีให้บริการแล้ว |

แอปอื่นใดจะแสดงเป็น **CashPilot has no such service** (CashPilot ไม่มีบริการนี้)

## สิ่งที่ไม่เคยนำมา { #what-never-comes-over }

- **ชื่ออุปกรณ์** CashPilot ตั้งชื่ออุปกรณ์แต่ละตัวตามเวิร์กเกอร์ที่รันอยู่
  เวิร์กเกอร์สองตัวจึงไม่รายงานชื่อเดียวกัน อุปกรณ์เก่าจะยังแสดงเป็น
  ออฟไลน์ในแดชบอร์ดของผู้ให้บริการแต่ละรายจนกว่าจะลบออกที่นั่น
- **พร็อกซี** เพิ่มพร็อกซีแต่ละตัวในส่วน **Proxies** (พร็อกซี) ของหน้า **Fleet** (กลุ่มเครื่อง) แล้วรัน
  สำเนาของบริการผ่านพร็อกซีนั้น การเพิ่มพร็อกซีไม่ได้เริ่มอะไรด้วยตัวเอง
  การบันทึกการนำเข้าก็ไม่ได้เริ่มอะไรเช่นกัน สำเนาผ่านพร็อกซีต้องมีบริการเดียวกัน
  ติดตั้งใช้งานบนเวิร์กเกอร์ก่อน และการติดตั้งใช้งานบริการนั้นจะรันบนการเชื่อมต่อของเวิร์กเกอร์เอง
  บริการที่ต้องไม่ใช้การเชื่อมต่อนั้นเลยจึงควรปล่อยไว้โดยไม่ติ๊ก
  ดู [สำเนาผ่านพร็อกซี](../proxies.md)
- **Watchtower และการแจ้งเตือน** CashPilot อัปเดตคอนเทนเนอร์ของตัวเอง
- **แดชบอร์ดของ money4band และพอร์ตของแดชบอร์ด**

## การติดตามรายได้ { #earnings-tracking }

สำหรับ Honeygain, IPRoyal Pawns และ Bitping ข้อมูลเข้าสู่ระบบของคอนเทนเนอร์เป็น
ข้อมูลเข้าสู่ระบบของบัญชีด้วย CashPilot จึงกรอกข้อมูลรับรองสำหรับรายได้ให้ด้วย เว้นแต่
จะตั้งไว้แล้วใน **Settings** (การตั้งค่า) สำหรับบริการอื่นทั้งหมด ให้เพิ่มข้อมูลเข้าสู่ระบบสำหรับรายได้
ใน **Settings > Earnings collection** (การตั้งค่า > การเก็บรายได้)

## Mysterium { #mysterium }

การนำเข้าจะเปิดใช้ Mysterium แต่ CashPilot จะเริ่มโหนดใหม่พร้อม
ข้อมูลระบุตัวตนใหม่ keystore ของโหนดเก่าและรายได้ที่ยังไม่ได้ชำระบัญชียังอยู่ใน
โฟลเดอร์ `.data/mysterium-node` ของ money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)) ให้ชำระบัญชีก่อน หรือทำตาม
[คู่มือ Mysterium](../guides/mysterium.md) เพื่อย้ายข้อมูลระบุตัวตนมา

`.env` ของ 3.x บอกไม่ได้ว่าเคยรัน Mysterium หรือไม่ เพราะเทมเพลตของไฟล์นี้
ระบุพอร์ตแดชบอร์ดไว้เสมอ จากไฟล์ 3.x จึงไม่นำเข้า Mysterium หากเคยรัน
ให้เพิ่มจากแคตตาล็อกเอง

## ความปลอดภัย { #safety }

- ไม่มีสิ่งใดในไฟล์ถูกรันหรือขยาย และไม่มีที่อยู่ใดในไฟล์ถูกดึงข้อมูล
- ไฟล์ถูกอ่านครั้งเดียวและไม่ถูกเก็บไว้ สิ่งที่บันทึกจะจัดเก็บแบบเข้ารหัส เช่นเดียวกับ
  ข้อมูลรับรองอื่นทั้งหมดใน CashPilot
- ความลับแสดงบนหน้าเพียงว่า **set** (ตั้งค่าแล้ว)
- การนำเข้าที่บันทึกไว้จะอยู่ในหน้านำเข้าจนกว่าจะกด **Forget** (ลืม) จึงติดตั้งใช้งาน
  ไปยังเวิร์กเกอร์เพิ่มได้ภายหลัง
