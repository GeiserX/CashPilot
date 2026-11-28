---
source_hash: 5a764f1d0f5a
---
# Migrar desde money4band { #moving-from-money4band }

CashPilot puede leer la configuración de money4band y traer tus inicios de sesión de los servicios, para
que no tengas que volver a escribirlos. Tú lo revisas todo antes de que CashPilot lo guarde.

## Antes de empezar { #before-you-start }

Necesitas la cuenta de propietario de CashPilot y al menos un worker de CashPilot en la
máquina donde ahora se ejecuta money4band, o en otra máquina.

Detén money4band en una máquina antes de desplegar allí los mismos servicios desde
CashPilot. Dos copias detrás de una misma conexión ganan como una sola, y el mismo id de dispositivo de EarnApp
o ProxyRack no debe ejecutarse dos veces. Usa **Stop apps stack** en el
menú de money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
o ejecuta `docker compose down` en su carpeta. Si configuraste instancias de proxy
adicionales, detén también cada una de ellas.

## Qué archivo usar { #which-file-to-use }

Usa `config/user-config.json` de tu carpeta de money4band. Cómo lo llevas a
CashPilot depende de tu versión de money4band.

En money4band 4.x, money4band escribe el archivo cuando ejecutas **Setup Apps**, y
contiene exactamente lo que escribiste. El `.env`
que está a su lado se genera a partir de ese archivo y también funciona, igual que el `.env`
editado a mano de money4band 3.x. Los dos se quedan solo en tu disco: el
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
de money4band los incluye.

money4band 5.0 cifra `config/user-config.json` en el disco
([notas de seguridad](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)),
y borra su `.env` después de cada arranque
([generador del env](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot no puede leer el archivo cifrado. En tu carpeta de money4band, ejecuta
su comando `config edit`. Para el binario publicado, usa el archivo de tu sistema, por ejemplo `./Money4Band-linux-amd64 config edit`, o `.\Money4Band-windows-amd64.exe config edit` en Windows.
Desde el código fuente, ejecuta `python run.py config edit`.
Este arranca money4band con uv, o con un entorno de pip si no tienes uv ([run.py](https://github.com/MRColorR/money4band/blob/eebbdd410131e4b0fd4c9f9d49f84dc60e6a0e3d/run.py#L48-L69)).
El comando abre el archivo descifrado en tu editor ([referencia de la CLI](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Copia todo su texto, pégalo en la página **Import from another tool** (Importar desde otra herramienta) y después cierra el editor.

Es preferible el archivo JSON. En un `.env`, Docker Compose expande `$` en los valores
sin comillas, así que una contraseña que contiene `$` no es lo que muestra el archivo. CashPilot no
lo adivina: te pide que vuelvas a escribir ese valor.

## Cómo importar { #how-to-import }

1. Abre **Settings** (Ajustes) y después **Import from another tool** (Importar desde otra herramienta), o ve a `/import`.
2. Añade `user-config.json` o pega su texto. Deja la herramienta en «Tell from the
   files» (deducir de los archivos) o elige money4band.
3. Revisa la tabla. Marca los servicios que quieras y rellena cualquier valor marcado
   como faltante.
4. Pulsa **Save the ticked services** (Guardar los servicios marcados) y después despliégalos en tus workers desde la
   misma página.

## Qué se trae { #what-comes-over }

Los nombres de los campos salen de la
[plantilla de user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
de money4band, y los nombres del `.env`, de los que escribe su
[generador](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
(`<APP>_<FLAG>`, por ejemplo `REPOCKET_APIKEY`). money4band 5.0 mantiene
los mismos nombres de campo en su
[catálogo de apps](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported).

| App de money4band | Servicio de CashPilot | Qué se trae |
|---|---|---|
| `earnapp` | EarnApp | id del dispositivo (`uuid`), para que tu dispositivo vinculado siga ganando |
| `honeygain` | Honeygain | correo, contraseña |
| `iproyalpawns` | IPRoyal Pawns | correo, contraseña |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | token |
| `repocket` | Repocket | correo, clave de API |
| `earnfm` | Earn.fm | clave de API |
| `proxyrack` | ProxyRack | clave de API, UUID del dispositivo |
| `proxylite` | ProxyLite | id de usuario |
| `bitping` | Bitping | correo, contraseña |
| `mystnode` | Mysterium | activado; consulta la nota sobre Mysterium de abajo |

Una app que desactivaste en money4band aparece sin marcar. Una app que está desactivada y
no contiene más que los marcadores de la plantilla (`yourHONEYGAINMail`) y listas de puertos
se omite, así que un `user-config.json` sin tocar da una tabla vacía.

Estas apps aparecen en la lista, pero no se traen:

| App de money4band | Por qué |
|---|---|
| `proxybase` | money4band ejecuta el cliente antiguo de ProxyBase con un id de usuario. CashPilot ejecuta el actual, que necesita el Access Token de proxybase.org. |
| `urnetwork` | money4band guarda un token de sesión. CashPilot inicia sesión en URnetwork con tu correo y tu contraseña. |
| `grass` | Grass funciona como extensión de navegador. CashPilot solo lo sigue, con el token de acceso del panel de Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot los sigue, pero no hay ningún contenedor que desplegar. |
| `packetshare`, `peer2profit`, `speedshare` | Ya no están disponibles. |

Cualquier otra app aparece como «CashPilot has no such service» (CashPilot no tiene ese servicio).

## Qué no se trae nunca { #what-never-comes-over }

- **Nombre del dispositivo.** CashPilot da a cada dispositivo el nombre del worker en el que se ejecuta, para
  que dos workers nunca informen con el mismo nombre. Tus dispositivos antiguos siguen apareciendo como
  desconectados en el panel de cada proveedor hasta que los elimines allí.
- **Proxies.** Añade cada uno en la sección Proxies de la página Fleet (Flota) y después ejecuta
  copias de tus servicios a través de él; añadir un proxy no arranca nada por sí solo.
  Guardar una importación tampoco arranca nada. Una copia por proxy necesita antes el mismo servicio
  desplegado en el worker, y desplegarlo lo ejecuta en la conexión propia del worker, así que un servicio que nunca debe usar esa conexión debería quedarse
  sin marcar. Consulta [Copias por proxy](../proxies.md).
- **Watchtower y las notificaciones.** CashPilot actualiza sus propios contenedores.
- **El panel de money4band y sus puertos.**

## Seguimiento de ganancias { #earnings-tracking }

En Honeygain, IPRoyal Pawns y Bitping, el inicio de sesión del contenedor es también el de la
cuenta, así que CashPilot rellena también sus credenciales de ganancias, salvo que
ya las hayas configurado en Settings. Para cualquier otro servicio, añade el inicio de sesión de ganancias
en **Settings > Earnings collection** (Ajustes > Recolección de ganancias).

## Mysterium { #mysterium }

Al importar se activa Mysterium, pero CashPilot arranca un nodo nuevo con una
identidad nueva. El almacén de claves del nodo antiguo y las ganancias sin liquidar se quedan en la carpeta
`.data/mysterium-node` de money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Liquídalas primero, o sigue la
[guía de Mysterium](../guides/mysterium.md) para traer la identidad.

Un `.env` de la 3.x no permite saber si ejecutabas Mysterium: su plantilla siempre
incluye el puerto del panel. Desde un archivo de la 3.x no se importa Mysterium, así que añádelo
desde el catálogo si lo ejecutabas.

## Seguridad { #safety }

- Nada del archivo se ejecuta ni se expande, y no se accede a ninguna dirección que contenga.
- El archivo se lee una vez y no se conserva. Lo que guardas se almacena cifrado, como
  cualquier otra credencial en CashPilot.
- En la página, los secretos solo aparecen como «set» (configurado).
- Las importaciones guardadas se quedan en la página de importación hasta que pulses **Forget** (Olvidar), para que puedas
  desplegarlas en más workers más adelante.
