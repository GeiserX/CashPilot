---
source_hash: 38029ca1a5d6
---

# การส่งออกรายได้สำหรับภาษี { #income-export-for-taxes }

เปิด **Payouts** (การจ่ายเงิน) หา **Income for taxes** (รายได้สำหรับภาษี) แล้วเลือกช่วงวันที่และสกุลเงิน **This year** (ปีนี้) ครอบคลุมจนถึงวันนี้ และ **Last year** (ปีที่แล้ว) ครอบคลุมปีปฏิทินก่อนหน้า เว้นวันที่ว่างไว้เพื่อส่งออกประวัติที่มีอยู่จนถึงวันนี้ CashPilot ใช้วันที่แบบ UTC และรวมทั้งวันเริ่มต้นและวันสิ้นสุดของช่วง

CashPilot ลบค่ารายได้ที่อ่านได้หลังจากบันทึกไว้ 400 วัน ไฟล์ CSV ใช้ประวัติที่ยังเหลืออยู่ ดังนั้นปีที่ผ่านมาอาจมีรายได้ที่หาได้หรือที่ค้างรับเพียงบางส่วน

## เลือกเกณฑ์ทางบัญชี { #choose-an-accounting-basis }

- **เกณฑ์เงินสด** ใช้แถว payout ซึ่งบันทึกเงินที่บริการจ่ายออกมาแล้ว CashPilot รวมเฉพาะการจ่ายเงินที่ยืนยันแล้ว
- **เกณฑ์คงค้าง** ใช้แถว earned และ accrued แถว earned แสดงเครดิตที่ถอนได้ตามเงื่อนไขของบริการ แถว accrued แสดงเครดิตของพูลที่ยังไม่ได้จ่าย ซึ่งพูลอาจไม่จ่ายเลย

ใช้เกณฑ์เดียวสำหรับรายได้เดียวกัน การเพิ่มแถว payout เข้ากับแถว earned และ accrued อาจนับเงินก้อนเดียวกันสองครั้ง ตรวจสอบว่าการยื่นภาษีของคุณใช้เกณฑ์ใด

## คอลัมน์ของ CSV { #csv-columns }

| คอลัมน์ | ความหมาย |
|---|---|
| date | วันแบบ UTC ของค่าที่อ่านได้ครั้งหลังหรือของการจ่ายเงิน การจ่ายเงินใช้วันที่ที่ป้อนไว้หรือวันที่ CashPilot ตรวจพบ |
| period_start | วันแบบ UTC ของค่าที่อ่านได้ครั้งก่อนสำหรับบริการและแหล่งข้อมูลนี้ เว้นว่างสำหรับการจ่ายเงิน ช่องว่างระหว่างค่าที่อ่านได้หมายความว่าจำนวนเงินครอบคลุมทั้งช่วงนั้น |
| kind | earned, accrued หรือ payout |
| service | ID บริการของ CashPilot |
| coin | รหัสสกุลเงินหรือโทเค็นตามที่ CashPilot บันทึกไว้ |
| amount | จำนวนในสกุลเงินหรือโทเค็นนั้น |
| usd_rate | จำนวนดอลลาร์สหรัฐต่อหนึ่งหน่วยของ coin |
| usd_value | มูลค่าของจำนวนนั้นเป็นดอลลาร์สหรัฐ |
| local_currency | สกุลเงินทั่วไปที่เลือกสำหรับการส่งออก |
| local_rate | จำนวนหน่วยของสกุลเงินที่เลือกต่อหนึ่งดอลลาร์สหรัฐ |
| local_value | มูลค่าของจำนวนนั้นเป็นสกุลเงินที่เลือก |
| method | วิธีการจ่ายเงิน หากมีการบันทึกไว้ |

มูลค่าที่ว่างหมายความว่าไม่มีอัตราแลกเปลี่ยน แต่จำนวนในสกุลเงินต้นทางยังอยู่ CashPilot ข้ามแต้มภายใน เช่น แต้ม Grass ในค่ารายได้ที่อ่านได้ ค่าที่อ่านได้ครั้งแรกของแต่ละแหล่งข้อมูลให้ยอดยกมา แถวต่อมาบันทึกส่วนที่เพิ่มขึ้น ดังนั้น CSV อาจเริ่มหลังค่าที่อ่านได้เก่าที่สุดในช่วงที่เลือก

หากมีแหล่งข้อมูลมากกว่าหนึ่งแหล่งอ่านบัญชีเดียวกัน CSV อาจนับรายได้นั้นมากกว่าหนึ่งครั้ง

อัตรา USD มาจากค่าที่อ่านได้ครั้งหลังหรือจากบันทึกการจ่ายเงิน เมื่อ CashPilot เติมราคาย้อนหลังให้ค่าที่อ่านได้ จะใช้ราคาของ CoinGecko เวลา 00:00 UTC ของวันนั้น CashPilot ใช้อัตราอ้างอิงล่าสุดของ ECB ในหรือก่อนวันของแถวนั้น เพื่อแปลง USD เป็นสกุลเงินที่เลือก ซึ่งครอบคลุมวันหยุดสุดสัปดาห์ วันหยุดนักขัตฤกษ์ และวันที่ ECB ยังไม่ได้เผยแพร่อัตรา [อัตรารายวันของ Frankfurter](https://frankfurter.dev/v1/)

Frankfurter มีสกุลเงินต่อไปนี้สำหรับการส่งออก [สกุลเงินที่รองรับ](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR และ ISK
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD และ ZAR

เลือก USD หากสกุลเงินของคุณไม่อยู่ในรายการนี้ หรือ Frankfurter ใช้งานไม่ได้

## นำเข้าไปยังเครื่องมืออื่น { #import-into-another-tool }

แปลง CSV เป็นรูปแบบของเครื่องมือนั้นก่อนนำเข้า เลือกแถวตามเกณฑ์ทางบัญชีที่ใช้ก่อน ข้ามแถว payout ของกระเป๋าเงินที่เครื่องมือนั้นซิงค์อยู่แล้ว

### rotki { #rotki }

ใช้ Generic Events พร้อมส่วนหัวต่อไปนี้

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

ตั้ง Type เป็น Income และ Location เป็น external rotki ยังรับ Deposit, Withdrawal, Loss, Spend และ Staking เมื่อประเภทเหล่านั้นตรงกับเหตุการณ์ แมป coin ไปที่ Currency, amount ไปที่ Amount และ service ไปที่ Description ใช้ตัวระบุสินทรัพย์ของ rotki เมื่อต่างจากรหัสเหรียญ แปลง date เป็น Unix timestamp แบบ UTC หน่วยมิลลิวินาที เว้นฟิลด์ค่าธรรมเนียมทั้งสองว่างไว้ [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

ใช้คอลัมน์ที่จำเป็นของเทมเพลต Universal

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

จัดรูปแบบ Date เป็น YYYY-MM-DD HH:mm:ss แบบ UTC ตั้ง Received Amount จาก amount และ Received Currency จาก coin เว้นฟิลด์ Sent ทั้งสองว่างไว้ สำหรับค่าที่ทราบ ให้แมป local_value และ local_currency ไปที่ Net Worth Amount และ Net Worth Currency ซึ่งไม่บังคับ ใช้คอลัมน์ Tag สำหรับ mining หรือ reward ตามความเหมาะสม Description และ TxHash ไม่บังคับ [เทมเพลต Universal ของ Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

ยังไม่มีบัญชี Koinly ใช่ไหม สมัครได้ที่นี่: https://koinly.io/?via=FFF185D5 นี่คือลิงก์แนะนำ และไม่มีค่าใช้จ่ายเพิ่มสำหรับคุณ

### CoinTracking { #cointracking }

แปลงแถวรายได้เป็นรูปแบบ CSV ปกติของ CoinTracking เพราะ Custom Importer ต้องมีฟิลด์การซื้อขายทั้งสองฝั่ง แต่แถวรายได้มีเพียงฝั่งซื้อ [ข้อกำหนดของ Custom Importer ของ CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

ตั้ง Type เป็น Income หรือ Mining ตามความเหมาะสม แมป amount ไปที่ Buy Amount, coin ไปที่ Buy Currency และ service ไปที่ Comment เว้นฟิลด์ Sell ว่างไว้ จัดรูปแบบ Date เป็น DD.MM.YYYY HH:MM:SS การส่งออกให้เพียงวันแบบ UTC จึงใช้ 00:00:00 เป็นเวลา ใช้ป้ายประเภทตามภาษาของบัญชี [รูปแบบ CSV ปกติของ CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

ยังไม่มีบัญชี CoinTracking ใช่ไหม ลิงก์สมัครนี้ให้ส่วนลด 10% สำหรับแพ็กเกจแบบชำระเงินทุกแพ็กเกจ: https://cointracking.info?ref=G962413 นี่คือลิงก์แนะนำ CoinTracking จ่ายให้โปรเจกต์ CashPilot 20% ของยอดที่คุณจ่าย และคุณไม่ต้องจ่ายเพิ่ม
