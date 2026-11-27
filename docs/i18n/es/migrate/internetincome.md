---
source_hash: ca9dd25d45ca
---
# Migrar desde InternetIncome { #moving-from-internetincome }

CashPilot puede leer el `properties.conf` de InternetIncome y los archivos donde
guarda los id de dispositivo de EarnApp y ProxyRack, y traerlos. Tú lo revisas
todo antes de que CashPilot lo guarde.

## Antes de empezar { #before-you-start }

Necesitas la cuenta de propietario de CashPilot y al menos un worker de CashPilot.

Detén InternetIncome en una máquina antes de desplegar allí los mismos servicios desde
CashPilot. Dos copias detrás de una misma conexión ganan como una sola, y el mismo id de dispositivo
no debe ejecutarse dos veces. En la carpeta de InternetIncome, ejecuta:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` elimina los contenedores y conserva `earnapp.txt`, `proxyrack.txt` y
la carpeta de datos de Mysterium. `--deleteBackup` elimina también esos archivos
([internetIncome.sh, líneas 61 a 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
y [línea 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
así que importa primero.

## Qué archivos usar { #which-files-to-use }

De la carpeta de InternetIncome:

- `properties.conf`, tus ajustes.
- `earnapp.txt`, si ejecutabas EarnApp. Cada línea contiene un enlace de dispositivo
  ([líneas 1250 a 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, si ejecutabas ProxyRack. Un UUID de dispositivo por línea
  ([líneas 817 a 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot toma el primer dispositivo de cada archivo: el que usaba tu contenedor
principal y el que vinculaste a tu cuenta. Las demás líneas eran de copias por
proxy, y la página te dice cuántas ha omitido.

InternetIncome pasa cada valor por la shell
([línea 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Un valor entre comillas simples se toma tal como está escrito, como aconsejan los comentarios de
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
Un valor fuera de comillas simples que contiene `$`, una comilla invertida, un espacio u
otro carácter que la shell cambiaría no es lo que muestra el archivo, así que
CashPilot te pide que lo vuelvas a escribir en lugar de ejecutar una shell para averiguarlo.

## Cómo importar { #how-to-import }

1. Abre **Settings** (Ajustes) y después **Import from another tool** (Importar desde otra herramienta), o ve a `/import`.
2. Añade `properties.conf`, y también `earnapp.txt` y `proxyrack.txt` si los
   tienes. Deja la herramienta en «Tell from the files» (deducir de los archivos) o elige InternetIncome.
3. Revisa la tabla. Marca los servicios que quieras y rellena cualquier valor marcado
   como faltante. Repocket necesita el correo de tu cuenta, que InternetIncome nunca te
   pidió.
4. Pulsa **Save the ticked services** (Guardar los servicios marcados) y después despliégalos en tus workers desde la
   misma página.

## Qué se trae { #what-comes-over }

| App de InternetIncome | Claves que se leen | Servicio de CashPilot | Qué se trae |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | clave de API (añade tu correo) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | clave de API, UUID del dispositivo |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | correo, contraseña |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | correo, contraseña |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id de usuario |
| `earnfm` | `EARN_FM_API` | Earn.fm | clave de API |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | id del dispositivo |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | correo, contraseña |
| `mysterium` | `MYSTERIUM=true` | Mysterium | activado; consulta la nota sobre Mysterium de abajo |

Un valor en blanco significa que la app estaba desactivada, y no aparece en la lista.

Estas apps aparecen en la lista, pero no se traen:

| App de InternetIncome | Por qué |
|---|---|
| `urnetwork` | InternetIncome usa un token de sesión. CashPilot inicia sesión en URnetwork con tu correo y tu contraseña. |
| `grass` | Grass funciona como extensión de navegador. CashPilot solo lo sigue, con el token de acceso del panel de Grass. |
| `titan`, `ebesucher`, `wipter` | CashPilot los sigue, pero no hay ningún contenedor que desplegar. |
| `peer2profit` | Ya no está disponible. |

Los ajustes de las apps que CashPilot no tiene (antGain, Adnade y otras) aparecen
por su nombre como no leídos.

## Qué no se trae nunca { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot da a cada dispositivo el nombre del worker en el que se ejecuta, para
  que dos workers nunca informen con el mismo nombre. Tus dispositivos antiguos siguen apareciendo como
  desconectados en el panel de cada proveedor hasta que los elimines allí.
- **Proxies** (`USE_PROXIES`, `proxies.txt`). Añade cada uno en la sección Proxies
  de la página Fleet (Flota) y después ejecuta copias de tus servicios a través de él; añadir
  un proxy no arranca nada por sí solo. Con `USE_PROXIES=true`, InternetIncome ejecutaba
  tus servicios solo a través de proxies. Guardar una importación tampoco arranca nada. Una
  copia por proxy necesita antes el mismo servicio desplegado en el worker, y
  desplegarlo lo ejecuta en la conexión propia del worker, así que un servicio que nunca
  debe usar esa conexión debería quedarse sin marcar. Consulta [Copias por
  proxy](../proxies.md).
- **`BROWSER_USERNAME` y `BROWSER_PASSWORD`**, el inicio de sesión del navegador propio de
  InternetIncome.

## Seguimiento de ganancias { #earnings-tracking }

En Honeygain, IPRoyal Pawns y Bitping, el inicio de sesión del contenedor es también el de la
cuenta, así que CashPilot rellena también sus credenciales de ganancias, salvo que
ya las hayas configurado en Settings. Para cualquier otro servicio, añade el inicio de sesión de ganancias
en **Settings > Earnings collection** (Ajustes > Recolección de ganancias).

## Mysterium { #mysterium }

Al importar se activa Mysterium, pero CashPilot arranca un nodo nuevo con una
identidad nueva. El almacén de claves del nodo antiguo y las ganancias sin liquidar se quedan en la carpeta
`mysterium-data` de InternetIncome. Liquídalas primero, o sigue la
[guía de Mysterium](../guides/mysterium.md) para traer la identidad.

## Seguridad { #safety }

- Nada de los archivos se ejecuta ni se expande, y no se accede a ninguna dirección que contengan.
- Los archivos se leen una vez y no se conservan. Lo que guardas se almacena cifrado, como
  cualquier otra credencial en CashPilot.
- En la página, los secretos solo aparecen como «set» (configurado).
- Las importaciones guardadas se quedan en la página de importación hasta que pulses **Forget** (Olvidar), para que puedas
  desplegarlas en más workers más adelante.
