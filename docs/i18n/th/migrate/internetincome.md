---
source_hash: ca9dd25d45ca
---

# ย้ายมาจาก InternetIncome { #moving-from-internetincome }

CashPilot อ่าน `properties.conf` ของ InternetIncome และไฟล์ที่
InternetIncome เก็บ id อุปกรณ์ของ EarnApp และ ProxyRack ไว้ แล้วนำข้อมูลเหล่านั้นมาได้ คุณตรวจสอบ
ทุกอย่างก่อนที่ CashPilot จะบันทึก

## ก่อนเริ่ม { #before-you-start }

ต้องมีบัญชีเจ้าของของ CashPilot และเวิร์กเกอร์ของ CashPilot อย่างน้อยหนึ่งตัว

หยุด InternetIncome บนเครื่องนั้นก่อนติดตั้งใช้งานบริการเดียวกันที่นั่นจาก
CashPilot สองสำเนาที่อยู่หลังการเชื่อมต่อเดียวกันหารายได้ได้เท่ากับสำเนาเดียว และ id อุปกรณ์เดียวกัน
ต้องไม่รันสองครั้ง ในโฟลเดอร์ InternetIncome ให้รัน:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` ลบคอนเทนเนอร์และเก็บ `earnapp.txt`, `proxyrack.txt` และ
โฟลเดอร์ข้อมูลของ Mysterium ไว้ ส่วน `--deleteBackup` ลบสิ่งเหล่านั้นด้วย
([internetIncome.sh บรรทัด 61 ถึง 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
และ [บรรทัด 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562))
จึงต้องนำเข้าก่อน

## ใช้ไฟล์ใด { #which-files-to-use }

จากโฟลเดอร์ InternetIncome:

- `properties.conf` การตั้งค่าของคุณ
- `earnapp.txt` หากเคยรัน EarnApp แต่ละบรรทัดเก็บลิงก์ของอุปกรณ์
  ([บรรทัด 1250 ถึง 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261))
- `proxyrack.txt` หากเคยรัน ProxyRack UUID ของอุปกรณ์หนึ่งรายการต่อบรรทัด
  ([บรรทัด 817 ถึง 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827))

CashPilot ใช้อุปกรณ์แรกในแต่ละไฟล์ ซึ่งเป็นอุปกรณ์ที่คอนเทนเนอร์หลัก
ใช้และเป็นอุปกรณ์ที่ลิงก์กับบัญชีไว้ บรรทัดอื่นเป็นของสำเนาที่ผ่าน
พร็อกซี และหน้านั้นจะบอกว่าข้ามไปกี่รายการ

InternetIncome ส่งทุกค่าผ่าน shell
([บรรทัด 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375))
ค่าในเครื่องหมายคำพูดเดี่ยวจะถูกใช้ตามที่เขียนไว้ ตามที่ความคิดเห็นใน
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)
แนะนำ ค่าที่อยู่นอกเครื่องหมายคำพูดเดี่ยวและมี `$` backtick ช่องว่าง หรือ
อักขระอื่นที่ shell จะเปลี่ยน ไม่ใช่สิ่งที่ไฟล์แสดง
CashPilot จึงขอให้พิมพ์ใหม่แทนที่จะรัน shell เพื่อหาค่า

## วิธีนำเข้า { #how-to-import }

1. เปิด **Settings** (การตั้งค่า) แล้วไปที่ **Import from another tool** (นำเข้าจากเครื่องมืออื่น) (หรือไปที่ `/import`)
2. เพิ่ม `properties.conf` รวมถึง `earnapp.txt` และ `proxyrack.txt` หากมี
   ปล่อยเครื่องมือไว้ที่ **Tell from the files** (ระบุจากไฟล์) หรือเลือก InternetIncome
3. ตรวจสอบตาราง ติ๊กบริการที่ต้องการ และกรอกค่าที่ระบุว่า
   ขาดหายไป Repocket ต้องใช้อีเมลของบัญชี ซึ่ง InternetIncome ไม่เคยถาม
4. กด **Save the ticked services** (บันทึกบริการที่ติ๊กไว้) แล้วติดตั้งใช้งานบริการเหล่านั้นไปยังเวิร์กเกอร์จาก
   หน้าเดียวกัน

## สิ่งที่นำมาได้ { #what-comes-over }

| แอปของ InternetIncome | คีย์ที่อ่าน | บริการของ CashPilot | สิ่งที่นำมาได้ |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | คีย์ API (เพิ่มอีเมลของคุณ) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | โทเค็น |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | คีย์ API, UUID ของอุปกรณ์ |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | อีเมล, รหัสผ่าน |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | อีเมล, รหัสผ่าน |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | user id |
| `earnfm` | `EARN_FM_API` | Earn.fm | คีย์ API |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | id อุปกรณ์ |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | อีเมล, รหัสผ่าน |
| `mysterium` | `MYSTERIUM=true` | Mysterium | เปิดใช้ ดูหมายเหตุเรื่อง Mysterium ด้านล่าง |

ค่าที่ว่างหมายความว่าแอปนั้นปิดอยู่ และจะไม่แสดงในรายการ

แอปต่อไปนี้แสดงในรายการแต่ไม่ได้นำมา:

| แอปของ InternetIncome | เหตุผล |
|---|---|
| `urnetwork` | InternetIncome ใช้โทเค็นเซสชัน ส่วน CashPilot เข้าสู่ระบบ URnetwork ด้วยอีเมลและรหัสผ่าน |
| `grass` | Grass รันเป็นส่วนขยายเบราว์เซอร์ CashPilot เพียงติดตามด้วย access token จากแดชบอร์ดของ Grass |
| `titan`, `ebesucher`, `wipter` | CashPilot ติดตามบริการเหล่านี้ แต่ไม่มีคอนเทนเนอร์ให้ติดตั้งใช้งาน |
| `peer2profit` | ไม่มีให้บริการแล้ว |

การตั้งค่าของแอปที่ CashPilot ไม่มี (antGain, Adnade และอื่น ๆ) จะ
แสดงตามชื่อว่าไม่ได้อ่าน

## สิ่งที่ไม่เคยนำมา { #what-never-comes-over }

- **`DEVICE_NAME`** CashPilot ตั้งชื่ออุปกรณ์แต่ละตัวตามเวิร์กเกอร์ที่รันอยู่
  เวิร์กเกอร์สองตัวจึงไม่รายงานชื่อเดียวกัน อุปกรณ์เก่าจะยังแสดงเป็น
  ออฟไลน์ในแดชบอร์ดของผู้ให้บริการแต่ละรายจนกว่าจะลบออกที่นั่น
- **พร็อกซี** (`USE_PROXIES`, `proxies.txt`) เพิ่มพร็อกซีแต่ละตัวในส่วน **Proxies** (พร็อกซี)
  ของหน้า **Fleet** (กลุ่มเครื่อง) แล้วรันสำเนาของบริการผ่านพร็อกซีนั้น การเพิ่ม
  พร็อกซีไม่ได้เริ่มอะไรด้วยตัวเอง เมื่อตั้ง `USE_PROXIES=true` InternetIncome รัน
  บริการผ่านพร็อกซีเท่านั้น การบันทึกการนำเข้าก็ไม่ได้เริ่มอะไรเช่นกัน
  สำเนาผ่านพร็อกซีต้องมีบริการเดียวกันติดตั้งใช้งานบนเวิร์กเกอร์ก่อน และ
  การติดตั้งใช้งานบริการนั้นจะรันบนการเชื่อมต่อของเวิร์กเกอร์เอง บริการที่ต้อง
  ไม่ใช้การเชื่อมต่อนั้นเลยจึงควรปล่อยไว้โดยไม่ติ๊ก ดู
  [สำเนาผ่านพร็อกซี](../proxies.md)
- **`BROWSER_USERNAME` และ `BROWSER_PASSWORD`** ข้อมูลเข้าสู่ระบบเบราว์เซอร์
  ของ InternetIncome เอง

## การติดตามรายได้ { #earnings-tracking }

สำหรับ Honeygain, IPRoyal Pawns และ Bitping ข้อมูลเข้าสู่ระบบของคอนเทนเนอร์เป็น
ข้อมูลเข้าสู่ระบบของบัญชีด้วย CashPilot จึงกรอกข้อมูลรับรองสำหรับรายได้ให้ด้วย เว้นแต่
จะตั้งไว้แล้วใน **Settings** (การตั้งค่า) สำหรับบริการอื่นทั้งหมด ให้เพิ่มข้อมูลเข้าสู่ระบบสำหรับรายได้
ใน **Settings > Earnings collection** (การตั้งค่า > การเก็บรายได้)

## Mysterium { #mysterium }

การนำเข้าจะเปิดใช้ Mysterium แต่ CashPilot จะเริ่มโหนดใหม่พร้อม
ข้อมูลระบุตัวตนใหม่ keystore ของโหนดเก่าและรายได้ที่ยังไม่ได้ชำระบัญชียังอยู่ใน
โฟลเดอร์ `mysterium-data` ของ InternetIncome ให้ชำระบัญชีก่อน หรือทำตาม
[คู่มือ Mysterium](../guides/mysterium.md) เพื่อย้ายข้อมูลระบุตัวตนมา

## ความปลอดภัย { #safety }

- ไม่มีสิ่งใดในไฟล์ถูกรันหรือขยาย และไม่มีที่อยู่ใดในไฟล์ถูกดึงข้อมูล
- ไฟล์ถูกอ่านครั้งเดียวและไม่ถูกเก็บไว้ สิ่งที่บันทึกจะจัดเก็บแบบเข้ารหัส เช่นเดียวกับ
  ข้อมูลรับรองอื่นทั้งหมดใน CashPilot
- ความลับแสดงบนหน้าเพียงว่า **set** (ตั้งค่าแล้ว)
- การนำเข้าที่บันทึกไว้จะอยู่ในหน้านำเข้าจนกว่าจะกด **Forget** (ลืม) จึงติดตั้งใช้งาน
  ไปยังเวิร์กเกอร์เพิ่มได้ภายหลัง
