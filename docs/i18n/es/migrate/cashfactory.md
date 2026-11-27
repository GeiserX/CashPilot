---
source_hash: 7f8476aeb8b6
---
# Migrar desde CashFactory { #moving-from-cashfactory }

CashPilot puede leer el `.env` de CashFactory y traer tus inicios de sesión de los servicios, para
que no tengas que volver a escribirlos. Tú lo revisas todo antes de que CashPilot lo guarde.

## Antes de empezar { #before-you-start }

Necesitas la cuenta de propietario de CashPilot y al menos un worker de CashPilot.

Detén CashFactory en una máquina antes de desplegar allí los mismos servicios desde
CashPilot. Dos copias detrás de una misma conexión ganan como una sola, y el mismo id de dispositivo
de EarnApp no debe ejecutarse dos veces. Ejecuta `docker compose down` en la carpeta de
CashFactory. Su
[archivo compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
también arranca tres contenedores que montan el socket de Docker: Portainer (línea 31)
y dos contenedores de Watchtower (líneas 141 y 264). Asegúrate de que también han desaparecido: `docker ps` no debería
mostrar ninguno de ellos.

## Qué archivo usar { #which-file-to-use }

Usa el archivo `.env` de tu carpeta de CashFactory, el que rellenaste a partir del
[ejemplo](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Docker Compose lee ese archivo y expande `$` en los valores que no están entre
comillas simples. Un valor así no es lo que muestra el archivo, así que CashPilot te pide
que lo vuelvas a escribir en lugar de adivinarlo.

## Cómo importar { #how-to-import }

1. Abre **Settings** (Ajustes) y después **Import from another tool** (Importar desde otra herramienta), o ve a `/import`.
2. Añade el archivo `.env` o pega su texto. Deja la herramienta en «Tell from the
   files» (deducir de los archivos) o elige CashFactory.
3. Revisa la tabla. Marca los servicios que quieras y rellena cualquier valor marcado
   como faltante.
4. Pulsa **Save the ticked services** (Guardar los servicios marcados) y después despliégalos en tus workers desde la
   misma página.

## Qué se trae { #what-comes-over }

| App de CashFactory | Claves que se leen | Servicio de CashPilot | Qué se trae |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | id del dispositivo, para que tu dispositivo vinculado siga ganando |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | correo, contraseña |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | correo, contraseña |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | correo, clave de API |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id de usuario |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID del dispositivo |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | clave de API |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | nada: ya no está disponible |

Un valor que todavía muestra el marcador del ejemplo (`<email>`, `sdk-node-<md5sum>`)
cuenta como no configurado, y un servicio que solo tiene marcadores se omite de
la tabla.

## Qué no se trae nunca { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot da a cada dispositivo el nombre del worker en el que se ejecuta, para
  que dos workers nunca informen con el mismo nombre. Tus dispositivos antiguos siguen apareciendo como
  desconectados en el panel de cada proveedor hasta que los elimines allí.
- **Bitping.** CashFactory guarda el inicio de sesión de Bitping en un volumen de Docker, no en
  `.env`, así que la importación no tiene nada que leer y no muestra ninguna fila de Bitping. Escribe el
  inicio de sesión en el formulario de despliegue de Bitping.
- **Portainer y Watchtower.** CashPilot gestiona y actualiza sus propios
  contenedores.

## Seguimiento de ganancias { #earnings-tracking }

En Honeygain e IPRoyal Pawns, el inicio de sesión del contenedor es también el de la cuenta,
así que CashPilot rellena también sus credenciales de ganancias, salvo que ya
las hayas configurado en Settings. Para cualquier otro servicio, añade el inicio de sesión de ganancias en
**Settings > Earnings collection** (Ajustes > Recolección de ganancias).

## Seguridad { #safety }

- Nada del archivo se ejecuta ni se expande, y no se accede a ninguna dirección que contenga.
- El archivo se lee una vez y no se conserva. Lo que guardas se almacena cifrado, como
  cualquier otra credencial en CashPilot.
- En la página, los secretos solo aparecen como «set» (configurado).
- Las importaciones guardadas se quedan en la página de importación hasta que pulses **Forget** (Olvidar), para que puedas
  desplegarlas en más workers más adelante.
