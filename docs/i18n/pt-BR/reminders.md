---
source_hash: b4ae1a3ae496
---
# Dinheiro à espera: lembretes antes de você perder ganhos { #money-waiting-reminders-before-you-lose-earnings }

Alguns provedores tomam de volta o dinheiro que fica parado por tempo demais. Um saldo pode expirar depois
de meses sem atividade. Uma janela de resgate pode se fechar. Um provedor pode banir uma
conta, parar de pagar ou encerrar as atividades enquanto o seu saldo ainda está lá.
O CashPilot já lê quase tudo de que precisa para ver isso chegando. O
quadro **Money waiting** (Dinheiro à espera) no painel mostra o que fazer e até quando, e
os seus canais de notificação recebem um push antes de cada prazo.

O CashPilot nunca resgata nem saca nada por você. Cada lembrete leva à
página do próprio provedor, e é lá que você age.

## Do que ele lembra você { #what-it-reminds-you-about }

**Regras dos próprios termos do provedor.** Cada regra cita os termos ou a página de ajuda
do provedor, e a data em que alguém os leu pela última vez. O link **Source** (Fonte) no
menu **More** (Mais) da linha abre essa página.

| Serviço | Lembrete | Quando |
|---|---|---|
| Grass | Resgate o seu USDC da Stage 2 | Até 22 de jan. de 2027. A Grass fica com o que não for resgatado. |
| MystNodes | Resgate as recompensas do mês passado | Dentro de 30 dias após cada distribuição mensal |
| Honeygain | Saque o seu saldo | 24 meses depois de ele chegar a $20 pela primeira vez |
| Honeygain | Mantenha um dispositivo compartilhando ou faça um pagamento | 6 meses após a última atividade ou pagamento |
| Repocket | Mantenha um dispositivo compartilhando ou saque | 12 meses após a última atividade ou pagamento |
| Bitping | Saque o seu saldo | 12 meses após o último saque |
| Salad | Ganhe alguns Reward Points ou gaste o seu saldo | 12 meses depois da última vez que o saldo cresceu. Gastar parte dele não reinicia esse prazo. |

**Saque.** O CashPilot avisa quando um saldo atinge o mínimo
do provedor. Isso vale para todos os serviços dos quais ele coleta, exceto os serviços que
pagam sozinhos. O saldo também precisa valer pelo menos $5, para que um provedor
com mínimo de 5 centavos não incomode já no primeiro centavo. Quando o mínimo do provedor
é maior, vale o mínimo do provedor. Quando o CashPilot não consegue
converter o mínimo ou o saldo, ele não mostra nada. Ele nunca supõe que
você pode sacar.

**Expiração de credenciais.** Você recebe um push antes que um token ou cookie salvo expire.
O CashPilot usa a data de expiração que a própria credencial informa. Quando ela não informa
nenhuma, o CashPilot usa a vida útil habitual desse tipo de credencial, contada
a partir do dia em que você a salvou. Os proprietários já veem isso em **Needs attention** (Precisa de atenção),
com um botão **Renew** (Renovar), então o quadro não repete o aviso. Só os proprietários recebem
lembretes de credenciais pela API, assim como na verificação de saúde das credenciais.
Uma credencial que o provedor rejeitou já está no sino e já foi enviada por push,
então não gera outro push.

## Quais serviços ele cobre { #which-services-it-covers }

Um lembrete se aplica a um serviço que você usa: um que está implantado, um que você configurou
como externo em **Settings** (Configurações) ou um app que um celular informa. Um serviço que você removeu
continua contando enquanto tiver saldo, porque os relógios de inatividade começam
quando ele para. Serviços personalizados e serviços descontinuados não recebem lembretes.

## Datas e "ou antes" { #dates-and-or-earlier }

Os relógios de atividade contam a partir do que o CashPilot registrou:

- a última vez que o saldo cresceu,
- o último pagamento,
- ou a primeira leitura igual ou acima do mínimo.

Às vezes o relógio começou antes da primeira leitura do CashPilot. Nesse caso, o prazo real
pode ser anterior ao que o CashPilot consegue ver, e a linha diz
"até 3 de out. de 2027 ou antes".

O CashPilot apaga o histórico de ganhos depois de 400 dias, e o relógio da Honeygain
dura 730 dias. Por isso, o CashPilot guarda o início de cada relógio na primeira vez que
o vê e o mantém depois que o histórico por trás dele some. Um pagamento reinicia
o relógio, exceto quando o provedor conta só os ganhos. A Salad é um desses casos: um
pagamento que deixa saldo não reinicia os 12 meses dela.

Uma data fixa sai da lista no dia seguinte ao vencimento, porque o dinheiro já foi perdido.
Um relógio vencido continua lá e avisa que o provedor talvez já tenha dado baixa no
dinheiro. Ele continua até você marcá-lo como feito ou silenciá-lo, ou até um pagamento
o reiniciar.

## O que você pode fazer com um lembrete { #what-you-can-do-with-a-reminder }

Proprietários e editores veem os botões. Leitores veem apenas os lembretes. Só os proprietários
podem agir sobre um lembrete de credencial.

- **Done** (Concluído), ou **Requested** (Solicitado) no caso de um saque, oculta esse lembrete. Uma janela
  mensal volta no mês seguinte. Um saque volta uma vez depois de 14 dias se
  o saldo ainda estiver lá, e pergunta se o pagamento chegou. Isso fica
  dentro da janela de contestação de 60 dias que a maioria dos provedores oferece.
- **Snooze** (Adiar) oculta o lembrete por um dia ou uma semana e segura os pushes dele. Um adiamento nunca
  passa do último aviso antes de um prazo.
- **Not for me** (Não é para mim), no menu **More** (Mais), silencia um lembrete ou todos os lembretes
  de um serviço. Um exemplo: a Honeygain no modo JumpTask, em que um saldo parado
  é normal. Os lembretes silenciados aparecem listados no rodapé do quadro, com
  **Unmute** (Reativar).

A casa toda compartilha essas escolhas. Quando uma pessoa marca um lembrete como feito, ele
fica feito para todos. Cada escolha é registrada no log de auditoria com o nome da
pessoa que a fez.

## Pushes { #pushes }

Os lembretes vão para os canais que você configurou para os alertas: ntfy, um webhook ou Telegram
([configuração](configuration.md)). Sem nenhum canal configurado, o quadro é o único
lugar onde eles aparecem.

- Um push por aviso. Por exemplo, a Grass envia push 60, 30, 7 e 1 dia antes
  da sua data. Um lembrete visto pela primeira vez 5 dias antes da data envia um único push, com 5
  dias restantes.
- Os pushes só saem entre 09:00 e 21:00. O CashPilot usa o fuso horário do primeiro proprietário
  em **Settings** (Configurações), depois o `TZ` do contêiner, depois UTC. Um aviso
  que vence durante a noite sai na primeira verificação depois das 09:00.
- Quando mais de 3 pushes vencem ao mesmo tempo, você recebe um único resumo. Isso
  acontece no dia em que você atualiza, quando todos os saldos acima do mínimo aparecem
  juntos.
- Um push traz o serviço, o que fazer, o que você perderia, a data e o
  link do provedor. Ele nunca traz um saldo, um endereço, um id de dispositivo nem um
  nome de worker. Os tópicos do ntfy podem ser públicos.
- Os payloads de webhook trazem `kind: "obligation"`, para que o Home Assistant e ferramentas
  parecidas possam encaminhá-los.

## Para quem contribui com o catálogo { #for-catalog-contributors }

As regras ficam no arquivo YAML de cada serviço, em `obligations:`.
O `services/_schema.yml` documenta os campos. Adicione uma regra só quando os
próprios termos ou a documentação do provedor a declararem, e quando o CashPilot conseguir ver o sinal de que
ela depende. O link de uma regra precisa estar no próprio domínio do serviço, porque existem sites falsos de
resgate exatamente para esses serviços. O CI falha com uma regra inválida, e
com uma regra datada vencida há mais de 30 dias.
