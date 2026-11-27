---
source_hash: d88e40f8d9a6
---
# 온체인 지급 잔액 { #on-chain-payout-balances }

공개 지급 주소의 잔액을 보려면 **Payouts** (지급)을 여십시오. Bitcoin은
[mempool.space](https://mempool.space/docs/api/rest)를, Kaspa는
[api.kaspa.org](https://api.kaspa.org/docs)를 사용합니다. Ethereum, Polygon, Solana는
공개 RPC 노드를 사용합니다. CashPilot은 키 없이 이 주소들을 읽을 수 있습니다.

| 보이는 것 | 의미 |
|---|---|
| 금액 | 탐색기가 잔액을 보고했습니다. 보고된 0은 0으로 표시됩니다. 금액 위에 마우스를 올리면 출처를 볼 수 있습니다. |
| **Pending** (대기 중) | Bitcoin에서 탐색기가 확인되지 않은 변동을 보고 있습니다. 더하기 기호는 자금이 들어오는 중이라는 뜻입니다. 빼기 기호는 자금이 사용되는 중이라는 뜻입니다. 확인된 금액은 따로 표시됩니다. |
| **Could not check** (확인할 수 없음) | 탐색기가 응답하지 않았거나 CashPilot이 읽을 수 없는 데이터를 보냈습니다. |
| **Address not valid** (유효하지 않은 주소) | 주소가 형식 검사를 통과하지 못했습니다. CashPilot은 요청을 건너뛰었습니다. |
| **Private chain** (비공개 체인) | Monero 잔액을 읽으려면 개인 보기 키가 필요합니다. 지갑에서 잔액을 확인하십시오. CashPilot은 이 키를 절대 요청하지 않습니다. |
| 대시 기호 | 이 행에 주소나 판독기가 없거나, 조회가 꺼져 있습니다. 설정이 조회를 끈 경우, 대시 기호 위에 마우스를 올리면 어느 설정인지 볼 수 있습니다. |

Kaspa의 공개 엔드포인트는 잔액 하나만 보고합니다. 대기 중인 금액을 따로
제공하지 않습니다.

온체인 열은 지금 이 순간 주소에 있는 잔액을 보여 줍니다. 여기에는 다른 출처에서
온 송금이 포함될 수 있습니다. 풀의 미지급 잔액은 풀이 아직 보유하고 있는 금액을
보여 줍니다. Lightning으로 받은 OCEAN 지급은 온체인 잔액에 나타나지 않습니다.
또한 잔액만으로는 어떤 송금이 풀에서 왔는지 알 수 없습니다.

## 조회를 보낼 곳 선택하기 { #choose-where-the-lookup-goes }

각 조회는 공개 지급 주소와 UI 서버의 IP를 탐색기와 공유합니다. 탐색기는 같은
IP에서 확인한 주소들을 서로 연결할 수 있습니다.

직접 노드를 운영한다면 UI 컨테이너의 환경에서 기본 URL을 설정하십시오.
기본값을 쓰려면 변수를 설정하지 않은 채로 두십시오. 해당 체인의 조회를 끄려면
빈 값으로 설정하십시오.

예를 들어, UI 서비스용 Compose 재정의 파일에는 다음과 같은 내용이 들어갈 수 있습니다:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Bitcoin이나 Kaspa를 설정할 때는 Esplora 또는 Kaspa API 기본 URL을 사용하십시오.
Bitcoin 엔드포인트는 Bitcoin 풀의 [예상 수익](fleet.md#running-costs)에 쓰이는
네트워크 난이도와 블록 보상도 제공합니다. 이 조회에는 mempool 백엔드(그
`/v1/mining` API)가 필요합니다. 일반 Esplora 서버는 잔액 조회에만 응답하며, 그러면
풀의 행에 예상 금액이 표시되지 않습니다.
Ethereum, Polygon, Solana의 경우 해당 변수
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` 또는
`CASHPILOT_ONCHAIN_URL_SOLANA`를 노드의 RPC URL로 설정하십시오. 자격 증명, 쿼리
문자열, 프래그먼트가 없는 HTTP 또는 HTTPS URL을 사용하십시오. 새 환경으로 UI
컨테이너를 다시 만들어 변경 사항을 적용하십시오.
