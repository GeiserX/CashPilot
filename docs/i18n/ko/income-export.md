---
source_hash: 38029ca1a5d6
---
# 세금 신고용 소득 내보내기 { #income-export-for-taxes }

**Payouts** (지급)을 열고 **Income for taxes** (세금 신고용 소득)를 찾은 다음, 기간과 통화를 선택하십시오. **This year** (올해)는 오늘까지이고, **Last year** (작년)는 직전 역년 전체입니다. 날짜를 비워 두면 오늘까지 남아 있는 기록 전체를 내보냅니다. CashPilot은 UTC 날짜를 사용하며 기간의 시작일과 종료일을 모두 포함합니다.

CashPilot은 수익 측정값을 기록한 지 400일이 지나면 삭제합니다. CSV는 남아 있는 기록을 사용하므로, 지난 연도에는 그해의 적립 소득이나 발생 소득 중 일부만 들어 있을 수 있습니다.

## 회계 기준 선택하기 { #choose-an-accounting-basis }

- **현금주의.** payout 행을 사용하십시오. 이 행은 서비스가 지급한 돈을 기록합니다. CashPilot은 확인된 지급만 포함합니다.
- **발생주의.** earned 행과 accrued 행을 사용하십시오. earned 행은 서비스 약관에 따라 인출할 수 있는 적립액을 보여 줍니다. accrued 행은 풀이 끝내 지급하지 않을 수도 있는 미지급 풀 적립액을 보여 줍니다.

같은 소득에는 한 가지 기준만 사용하십시오. earned 행과 accrued 행에 payout 행을 더하면 같은 돈을 두 번 셀 수 있습니다. 신고에 어느 기준이 적용되는지 확인하십시오.

## CSV 열 { #csv-columns }

| 열 | 의미 |
|---|---|
| date | 나중 측정값 또는 지급의 UTC 날짜. 지급은 직접 입력한 날짜나 CashPilot이 지급을 감지한 날을 사용합니다. |
| period_start | 이 서비스와 출처의 이전 측정값의 UTC 날짜. 지급에서는 비어 있습니다. 측정값 사이에 간격이 있으면 금액이 그 간격 전체를 포함한다는 뜻입니다. |
| kind | earned, accrued 또는 payout. |
| service | CashPilot 서비스 ID. |
| coin | CashPilot이 기록한 통화 또는 토큰 코드. |
| amount | 그 통화 또는 토큰으로 된 금액. |
| usd_rate | coin 1단위당 미국 달러 수. |
| usd_value | 미국 달러로 평가한 금액. |
| local_currency | 내보내기에 선택한 법정 화폐. |
| local_rate | 미국 달러 1달러당 선택한 통화의 단위 수. |
| local_value | 선택한 통화로 평가한 금액. |
| method | 기록된 경우 지급 방법. |

평가액이 비어 있으면 환율을 구할 수 없었다는 뜻입니다. 원래 통화 금액은 그대로 있습니다. CashPilot은 수익 측정값에서 Grass 포인트 같은 내부 포인트를 건너뜁니다. 출처별 첫 측정값은 기초 잔액이 됩니다. 이후 행은 증가분을 기록하므로, CSV는 선택한 기간의 가장 오래된 측정값 이후부터 시작할 수 있습니다.

둘 이상의 출처가 같은 계정을 읽으면 CSV가 그 소득을 여러 번 셀 수 있습니다.

USD 환율은 나중 측정값이나 지급 기록에서 가져옵니다. CashPilot이 측정값의 가격을 소급해 채울 때는 그날 00:00 UTC의 CoinGecko 가격을 사용합니다. USD를 선택한 통화로 환산할 때 CashPilot은 행의 날짜 당일 또는 그 이전의 가장 최근 ECB 기준 환율을 사용합니다. 이는 주말, 공휴일, 그리고 ECB가 아직 환율을 발표하지 않은 날에도 적용됩니다. [Frankfurter 일별 환율](https://frankfurter.dev/v1/)

Frankfurter는 내보내기에 사용할 수 있는 다음 통화를 제공합니다. [지원 통화](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR, ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD, ZAR.

사용하는 통화가 이 목록에 없거나 Frankfurter를 사용할 수 없으면 USD를 선택하십시오.

## 다른 도구로 가져오기 { #import-into-another-tool }

가져오기 전에 CSV를 해당 도구의 형식으로 변환하십시오. 먼저 회계 기준에 맞는 행을 고르십시오. 도구가 이미 동기화하는 지갑의 payout 행은 건너뛰십시오.

### rotki { #rotki }

다음 헤더로 Generic Events를 사용하십시오.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Type은 Income으로, Location은 external로 설정하십시오. rotki는 이벤트를 설명하는 데 맞는 경우 Deposit, Withdrawal, Loss, Spend, Staking도 받아들입니다. coin은 Currency에, amount는 Amount에, service는 Description에 대응시키십시오. coin 코드와 다른 경우 rotki의 자산 식별자를 사용하십시오. date는 밀리초 단위의 UTC Unix 타임스탬프로 변환하십시오. 두 수수료 필드는 비워 두십시오. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Universal 템플릿의 필수 열을 사용하십시오.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Date는 UTC 기준 YYYY-MM-DD HH:mm:ss 형식으로 쓰십시오. Received Amount는 amount에서, Received Currency는 coin에서 설정하십시오. 두 Sent 필드는 비워 두십시오. 값을 아는 경우 local_value와 local_currency를 선택 열인 Net Worth Amount와 Net Worth Currency에 대응시키십시오. 적절한 경우 Tag 열에 mining 또는 reward를 사용하십시오. Description과 TxHash는 선택 사항입니다. [Koinly Universal 템플릿](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

아직 Koinly 계정이 없습니까? 여기에서 가입할 수 있습니다: https://koinly.io/?via=FFF185D5 이 링크는 추천 링크이며, 사용자에게 비용이 들지 않습니다.

### CoinTracking { #cointracking }

소득 행을 CoinTracking의 일반 CSV 형식으로 변환하십시오. Custom Importer는 양쪽 모두에 거래 필드를 요구하는데, 소득 행에는 매수 쪽만 있습니다. [CoinTracking Custom Importer 요구 사항](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Type은 상황에 맞게 Income 또는 Mining으로 설정하십시오. amount는 Buy Amount에, coin은 Buy Currency에, service는 Comment에 대응시키십시오. Sell 필드는 비워 두십시오. Date는 DD.MM.YYYY HH:MM:SS 형식으로 쓰십시오. 내보내기는 UTC 날짜만 제공하므로 시간에는 00:00:00을 사용하십시오. 계정 언어에 맞는 유형 레이블을 사용하십시오. [CoinTracking 일반 CSV 형식](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

아직 CoinTracking 계정이 없습니까? 이 가입 링크를 쓰면 모든 유료 요금제가 10% 할인됩니다: https://cointracking.info?ref=G962413 이 링크는 추천 링크입니다. CoinTracking은 사용자가 지불하는 금액의 20%를 CashPilot 프로젝트에 지급하며, 사용자가 더 많이 내지는 않습니다.
