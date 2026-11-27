---
source_hash: b4ae1a3ae496
---
# Dinero pendiente: recordatorios antes de perder ganancias { #money-waiting-reminders-before-you-lose-earnings }

Algunos proveedores recuperan el dinero que pasa demasiado tiempo sin moverse. Un saldo puede caducar tras
meses sin actividad. Un plazo para reclamar puede cerrarse. Un proveedor puede bloquear una
cuenta, dejar de pagar o cerrar mientras tu saldo sigue ahí.
CashPilot ya lee casi todo lo que necesita para verlo venir. El panel
**Money waiting** (Dinero pendiente) del panel principal muestra qué hacer y antes de cuándo, y
tus canales de notificación reciben un aviso push antes de cada fecha límite.

CashPilot nunca reclama ni retira nada por ti. Cada recordatorio enlaza a la
página del propio proveedor, y eres tú quien actúa allí.

## Qué te recuerda { #what-it-reminds-you-about }

**Reglas de las condiciones del propio proveedor.** Cada regla cita las condiciones o la página de ayuda
del proveedor, y la fecha en que alguien la leyó por última vez. El enlace **Source** (Fuente) del
menú **More** (Más) de la fila la abre.

| Servicio | Recordatorio | Cuándo |
|---|---|---|
| Grass | Reclama tus USDC de la Stage 2 | Antes del 22 ene 2027. Grass se queda con lo que no se reclame. |
| MystNodes | Reclama las recompensas del mes pasado | En los 30 días siguientes a cada reparto mensual |
| Honeygain | Retira tu saldo | 24 meses después de que alcanzara por primera vez $20 |
| Honeygain | Mantén un dispositivo compartiendo, o haz un pago | 6 meses después de la última actividad o del último pago |
| Repocket | Mantén un dispositivo compartiendo, o retira | 12 meses después de la última actividad o del último pago |
| Bitping | Retira tu saldo | 12 meses después de la última retirada |
| Salad | Gana algunos Reward Points, o gasta tu saldo | 12 meses después de la última vez que creció el saldo. Gastar una parte no reinicia este plazo. |

**Retirada.** CashPilot te avisa cuando un saldo alcanza el pago mínimo
del proveedor. Esto se aplica a todos los servicios de los que recoge datos, excepto a los que
pagan por sí solos. Además, el saldo debe valer al menos $5, para que un proveedor
con un mínimo de 5 céntimos no te moleste desde el primer céntimo. Cuando el mínimo del proveedor
es mayor, se aplica el mínimo del proveedor. Cuando CashPilot no puede
convertir el mínimo o el saldo, no muestra nada. Nunca supone que
puedes retirar.

**Caducidad de credenciales.** Recibes un aviso push antes de que caduque un token o una cookie guardados.
CashPilot usa la fecha de caducidad que indica la propia credencial. Cuando no indica
ninguna, CashPilot usa la vida habitual de ese tipo de credencial, contada
desde el día en que la guardaste. Los propietarios ya la ven en **Needs attention** (Requiere atención),
con un botón **Renew** (Renovar), así que el panel no la repite. Solo los propietarios reciben
recordatorios de credenciales desde la API, igual que con la comprobación del estado de las credenciales.
Una credencial que el proveedor rechazó ya está en la campana y ya se avisó por push,
así que no se vuelve a avisar.

## Qué servicios cubre { #which-services-it-covers }

Un recordatorio se aplica a un servicio que usas: uno desplegado, uno que configuraste
como externo en Settings (Ajustes) o una app que informa desde un teléfono. Un servicio que eliminaste
sigue contando mientras tenga saldo, porque los plazos de inactividad empiezan
cuando se detiene. Los servicios personalizados y los servicios descontinuados no reciben recordatorios.

## Fechas y «o antes» { #dates-and-or-earlier }

Los plazos de actividad cuentan desde lo que CashPilot registró:

- la última vez que creció el saldo,
- el último pago,
- o la primera lectura igual o superior al mínimo.

A veces el plazo empezó antes de la primera lectura de CashPilot. Entonces la fecha
límite real puede ser anterior a la que CashPilot puede ver, y la fila dice
«by 3 Oct 2027 or earlier» (como tarde el 3 oct 2027, o antes).

CashPilot borra el historial de ganancias pasados 400 días, y el plazo de Honeygain
dura 730 días. Por eso CashPilot guarda el inicio de cada plazo la primera vez que
lo ve, y lo conserva después de que desaparezca el historial que había detrás. Un pago reinicia
el plazo, salvo cuando el proveedor solo cuenta lo que se gana. Salad es uno de ellos: un
pago que deja saldo no reinicia sus 12 meses.

Una fecha fija desaparece al día siguiente de pasar, porque el dinero ya se ha perdido.
Un plazo vencido se queda y dice que puede que el proveedor ya haya dado el
dinero por perdido. Se queda hasta que lo marques como hecho o lo silencies, o hasta que un pago
lo reinicie.

## Qué puedes hacer con un recordatorio { #what-you-can-do-with-a-reminder }

Los propietarios y los editores ven los botones. Los lectores solo ven los recordatorios. Solo los propietarios
pueden actuar sobre un recordatorio de credenciales.

- **Done** (Hecho), o **Requested** (Solicitado) en una retirada, oculta este recordatorio. Un plazo
  mensual vuelve el mes siguiente. Una retirada vuelve una vez pasados 14 días si
  el saldo sigue ahí, y pregunta si ha llegado el pago. Eso queda
  dentro del plazo de reclamación de 60 días que dan la mayoría de los proveedores.
- **Snooze** (Posponer) lo oculta un día o una semana y retiene sus avisos push. Posponer nunca
  pasa del último aviso antes de una fecha límite.
- **Not for me** (No es para mí), en el menú **More**, silencia un recordatorio, o todos los recordatorios
  de un servicio. Un ejemplo: Honeygain en modo JumpTask, donde es normal que el saldo
  no cambie. Los recordatorios silenciados aparecen al pie del panel, con
  **Unmute** (Reactivar).

Todo el hogar comparte estas decisiones. Cuando una persona marca un recordatorio como hecho,
queda hecho para todos. Cada decisión se registra en el registro de auditoría con el nombre de
la persona que la tomó.

## Avisos push { #pushes }

Los recordatorios van a los canales que configuraste para las alertas: ntfy, un webhook o Telegram
([configuración](configuration.md)). Si no hay ningún canal configurado, el panel es el único
sitio donde aparecen.

- Un aviso push por cada umbral de aviso. Por ejemplo, Grass avisa 60, 30, 7 y 1 día antes
  de su fecha. Un recordatorio que aparece por primera vez 5 días antes de su fecha avisa una vez, con 5
  días por delante.
- Los avisos push solo salen entre las 09:00 y las 21:00. CashPilot usa la zona horaria
  del primer propietario en Settings, después el `TZ` del contenedor y después UTC. Un aviso
  que toca de madrugada sale en la primera comprobación después de las 09:00.
- Cuando tocan más de 3 avisos push a la vez, recibes un solo resumen. Esto
  pasa el día que actualizas, cuando todos los saldos por encima de su mínimo aparecen
  juntos.
- Un aviso push incluye el servicio, qué hacer, qué perderías, la fecha y el
  enlace del proveedor. Nunca incluye un saldo, una dirección, un id de dispositivo ni el
  nombre de un worker. Los temas de ntfy pueden ser públicos.
- Las cargas de los webhooks llevan `kind: "obligation"`, para que Home Assistant y herramientas
  similares puedan enrutarlas.

## Para quienes contribuyen al catálogo { #for-catalog-contributors }

Las reglas están en el archivo YAML de cada servicio, bajo `obligations:`.
`services/_schema.yml` documenta los campos. Añade una regla solo cuando las
condiciones o la documentación del propio proveedor la indiquen, y cuando CashPilot pueda ver la señal
de la que depende. El enlace de una regla debe estar en el dominio del propio servicio, porque existen
sitios falsos para reclamar precisamente de estos servicios. La CI falla con una regla no válida, y
con una regla con fecha pasada hace más de 30 días.
