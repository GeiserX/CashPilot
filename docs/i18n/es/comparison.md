---
source_hash: 4b8d25fab777
---
# Cómo se compara CashPilot { #how-cashpilot-compares }

Esta página compara CashPilot con los demás proyectos abiertos que ejecutan varias apps de ingresos pasivos en Docker. Revisamos cada proyecto el 2026-11-04, y CashPilot de nuevo el 2026-11-28. Cada celda sobre otro proyecto enlaza al archivo del que sale, en un commit fijo, para que puedas comprobarlo tú. Si una celda es incorrecta o está desactualizada, [abre una incidencia](https://github.com/GeiserX/CashPilot/issues).

## Proyectos comparados { #projects-compared }

| Proyecto | Qué revisamos | Estrellas el 2026-11-04 | Licencia |
|---|---|---|---|
| [money4band][m4b-tree] | Versión 5.0.0, commit de la etiqueta `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` en `65e900d` (2026-10-20), más lo que afirma el README sobre su binario 3.0.0-beta.9 | 238 | Propietaria, [licencia propia v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` en `db9338a` (2026-11-03) | 257 | Sin archivo LICENSE. El [README][ii-license] permite copiar el original y prohíbe distribuir copias modificadas |
| [CashFactory][cf-tree] | `main` en `0ff4bd0` (2025-04-08) | 410 | El archivo [LICENSE][cf-license-file] es GPL-3.0, pero el [README][cf-license] prohíbe distribuir copias modificadas |
| [home-assistant-passive-income][ha-tree] (complementos de HA) | Versión 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Versión v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

money4band tiene dos líneas de código. Su rama por defecto, `main` (`3bfafb1`), sigue teniendo el código 4.x, y su último cambio de código ahí fue el 2026-03-03. La versión 5.0.0 se construye a partir de un historial aparte. Comparamos la 5.0.0 porque es lo que distribuye su última versión.

La interfaz web, la gestión de flota y el binario instalador de IGM son de código cerrado y no están en su repositorio. Cuando una celda depende de ellos, dice «el README afirma» y enlaza la línea del README. Todo lo demás de la columna de IGM sale de los scripts de shell y los archivos compose del repositorio.

Quedan fuera: [earning-machine](https://github.com/jf-m/earning-machine) y [passiveMachine](https://github.com/Xpl0itU/passiveMachine), que no tienen commits desde 2024. Una búsqueda en GitHub no encontró nada más con mantenimiento que ejecute más de una app, solo imágenes de una sola app.

## Versión corta { #short-version }

- **InternetIncome, money4band, IGM y, desde la v1.69.0, CashPilot pueden ganar en muchas IP a través de proxies.** Los tres primeros ejecutan cada app una vez por proxy, y los proxies son la función principal de InternetIncome. CashPilot ejecuta copias adicionales de un servicio ya desplegado en un worker, cada una a través de un proxy SOCKS5, HTTP CONNECT o un exit node de Tailscale ([copias por proxy](proxies.md)).
- **InternetIncome arranca 23 apps, IGM arranca 20 y el worker de CashPilot arranca <!-- n:docker -->21<!-- /n -->.** CashPilot sigue más servicios en total (<!-- n:live -->50<!-- /n -->) porque también sigue servicios de extensión de navegador, de escritorio y de GPU que no ejecuta. Desde la v1.64.0 también puede ejecutar cualquier imagen que indiques como [servicio personalizado](custom-services.md).
- **money4band e IGM reclaman por ti las recompensas diarias y mantienen actualizadas las imágenes de las apps con Watchtower.** CashPilot no hace ninguna de las dos cosas. Solo vuelve a descargar una imagen cuando despliegas o vuelves a desplegar.
- **CashPilot es el único de esta lista que lee los saldos de tus cuentas en los proveedores y guarda un historial.** money4band 5.0.0 muestra estimaciones de su propio catálogo, no de tus cuentas. Los demás enlazan al panel de cada proveedor.
- **CashPilot es el único de código abierto de esta lista con una sola interfaz para muchos servidores.** El README de IGM afirma tener gestión de flota, pero ese código está en su binario cerrado.
- **Desde la v1.70.0, CashPilot es el único de esta lista que mantiene por defecto los contenedores de las apps de ingresos fuera de tu LAN, con límites.** Está activado en las instalaciones nuevas y en las actualizadas que no tienen ninguna app de ingresos en el bridge por defecto de Docker. Una instalación actualizada cuyas apps de ingresos ya están en ese bridge las deja ahí hasta que actives el aislamiento, y una red que indiques en `CASHPILOT_CONTAINER_NETWORK` no recibe barrera de CashPilot ([aislamiento](isolation.md#modes)). Desde la 2.0.7, Mysterium también se ejecuta tras la barrera; un nodo desplegado hasta la 2.0.6 sigue en la red del host, sin barrera, hasta que lo vuelvas a desplegar ([Mysterium detrás de la barrera](mysterium-fence.md)).

## Cara a cara { #side-by-side }

La columna de CashPilot describe la v3.0.1. Cada una de sus celdas es breve, y las [notas bajo la tabla](#cashpilot-notes) recogen los detalles y los enlaces al código. Las demás columnas describen los commits de la tabla de arriba.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | Complementos de HA |
|---|---|---|---|---|---|---|
| Apps que puede arrancar (consulta [cómo contamos](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> ejecutadas por el worker, más [imágenes personalizadas](custom-services.md); <!-- n:live -->50<!-- /n --> seguidas en total | 15 ([catálogo][m4b-catalog]). El README dice 35, lo que [incluye][m4b-readme-35] apps de la comunidad y apps retiradas | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([archivo compose][cf-compose]) | 10 ([carpetas de complementos][ha-tree]) |
| Cómo se instala | Docker Compose: una UI, más un worker en cada servidor ([flota](fleet.md)) | CLI de Python o un binario ya compilado que escribe un archivo compose ([versión][m4b-tree]) | Instalador `curl \| sh` ([README][igm-install]) que descarga un binario cerrado, verificado solo con un archivo SHA256SUMS de la misma versión ([instalador][igm-installer-sums]) | Un único script de bash de 1608 líneas que llama a `sudo docker run` ([script][ii-script]) | Un archivo compose estático más `setup.sh` ejecutado con sudo ([setup][cf-setup]) | Un repositorio de complementos de Home Assistant; necesita Home Assistant OS o Supervised |
| Muchos servidores, una sola vista | Sí ([flota](fleet.md)) | No, una pila por dispositivo | El README afirma que sí, en el binario cerrado ([README][igm-features]) | No | No | No |
| Muchos proxies o IP | Sí, a través de proxies SOCKS5, HTTP CONNECT o exit nodes de Tailscale ([copias por proxy](proxies.md), [notas](#cashpilot-notes)) | Sí ([README][m4b-features], [código][m4b-multiproxy]) | Sí ([README][igm-features], [compose][igm-proxy]) | Sí, es su función principal ([README][ii-readme-top]) | No | No |
| Ganancias | <!-- n:collectors -->20<!-- /n --> recolectores leen los saldos de tus cuentas en los proveedores y guardan un historial | Estimaciones a partir de rangos del catálogo, no datos de la cuenta ([código][m4b-earnings]) | No se encontró nada en los scripts | Ninguna | Ninguna | Ninguna |
| Pagos | Propone un pago cuando baja un saldo y lo registra en cuanto lo confirmas ([esquema][cp-payouts]) | Ninguno | Ninguno | Ninguno | Ninguno | Ninguno |
| Reclamación de recompensas diarias | No | Sí, con sidecars ([README][m4b-features]) | Sí ([README][igm-features], [compose][igm-sidecars]) | No | No | No |
| Credenciales en reposo | Cifradas (Fernet) en la base de datos de la UI ([notas](#cashpilot-notes)) | Cifradas (Fernet); el archivo de clave está en el directorio de datos ([código][m4b-crypto]) | Cifradas (AES-256 con openssl); el archivo de clave está junto al almacén ([código][igm-encryptor]) | Texto plano en `properties.conf`; algunas contraseñas se pasan como argumentos de `docker run` ([script][ii-password-arg]) | Texto plano en `.env` ([archivo][cf-env]) | Opciones del complemento, que el Supervisor guarda en `/data/options.json` ([documentación de HA][ha-options]) |
| Ajustes de los contenedores de las apps de ingresos | Se quitan las capabilities, salvo las que concede el catálogo; `no-new-privileges`, un límite de pids; se rechaza el modo privilegiado ([notas](#cashpilot-notes)) | `no-new-privileges` en todos los servicios no privilegiados ([código][m4b-nnp]); el contenedor del proxy es privilegiado y tiene `NET_ADMIN` ([plantilla][m4b-tun]) | Nada configurado en los servicios de las apps; Mysterium recibe `NET_ADMIN` ([compose][igm-hosting-myst]); el contenedor del proxy recibe `NET_ADMIN`, con `no-new-privileges` y un límite de pids ([compose][igm-proxy]) | Ebesucher se ejecuta con `seccomp=unconfined` ([script][ii-seccomp]); los contenedores de proxy y Mysterium reciben `NET_ADMIN` | Nada configurado | Ningún complemento pide modo privilegiado, red del host ni acceso a la API de Docker ([configuración de ejemplo][ha-config]) |
| Dónde se monta el socket de Docker | El proxy del socket, en solo lectura, y un contenedor de migración de un solo uso ([notas](#cashpilot-notes)) | Watchtower ([plantilla][m4b-watchtower]) | Watchtower, en solo lectura y con `no-new-privileges` ([compose][igm-watchtower]) | Cinco contenedores auxiliares de reinicio ([script][ii-sock-helper]) y Watchtower ([script][ii-watchtower]) | Portainer, publicado en los puertos 8000, 9000 y 9443 en todas las interfaces ([compose][cf-portainer]), y dos Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Ninguno |
| Etiquetas de imagen | <!-- n:pinned -->9<!-- /n --> de las <!-- n:docker -->21<!-- /n --> imágenes de apps de ingresos fijadas a una versión o un digest; el resto son móviles | Las 15 imágenes de apps usan `:latest` ([ejemplo][m4b-image]); el contenedor del proxy está fijado a la v2.6.0 y Watchtower a `:1` | Sin etiqueta, así que Docker usa `latest` ([compose][igm-hosting]); solo hay etiqueta en algunas compilaciones para ARM | Sobre todo `:latest` ([ejemplo][ii-seccomp]); EarnApp `:lite`, Honeygain fijado a la 0.6.6 cuando va por proxy en amd64 ([script][ii-honeygain]), Traffmonetizer con etiquetas por arquitectura en ARM; Watchtower `:nightly` | `:latest` o sin etiqueta, excepto EarnApp `:lite` ([compose][cf-compose]) | Una versión por complemento, que sube un trabajo diario de CI ([workflow][ha-bump], [ejemplo][ha-dockerfile]) |
| Actualización de las imágenes de las apps | Se vuelven a descargar en cada despliegue o nuevo despliegue; sin actualizador automático | Watchtower ([plantilla][m4b-watchtower]) | Watchtower cada 4 horas ([compose][igm-watchtower]) | Watchtower una vez al día, si lo activas ([script][ii-watchtower]) | Dos Watchtower, cada uno limitado a una app, PacketStream ([compose][cf-watchtower-ps]) y EarnFM ([compose][cf-watchtower-efm]); las otras 9 apps no se actualizan | Las actualizaciones de complementos de Home Assistant |
| Aislamiento de la LAN | Activado por defecto en las instalaciones nuevas ([aislamiento](isolation.md#lan-isolation-by-default), [notas](#cashpilot-notes)) | Subred de bridge propia ([configuración][m4b-subnet]), que no bloquea la LAN | Nada fusionado | No se encontró nada | No se encontró nada | No se encontró nada |
| ARM | UI y worker para arm64, con una comprobación de plataforma antes de cada despliegue ([ARM](arm.md)) | Binarios para arm64 y armv7 ([versión][m4b-release]) | El README afirma amd64 y arm64, arm32 con limitaciones, y configura QEMU ([README][igm-arch]) | Necesita emulación binfmt para las imágenes solo de amd64 ([README][ii-arm]) | El README dice que no funciona en una Raspberry Pi ([README][cf-raspberry]) | Según el complemento; ProxyRack es solo amd64 ([configuración][ha-proxyrack]) |
| Interfaz | Interfaz web, más clientes de escritorio, Android, MCP y Home Assistant | CLI, menús y un panel web local enlazado a 127.0.0.1 por defecto ([código][m4b-bind]) | CLI, menús y, según el README, una interfaz web en el puerto 4747 accesible desde la LAN ([README][igm-webui]) | Ninguna, es un script | Una página de marcadores en el puerto 80 más Portainer ([README][cf-ui]) | El panel de complementos de Home Assistant |
| Última versión | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Sin versiones numeradas | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Llamadas salientes además de las apps | Comprobación de actualizaciones, consulta de la IP pública, tipos de cambio y saldos on-chain; fuentes y Chart.js desde CDN ([notas](#cashpilot-notes)) | Versiones de GitHub, para su comprobación de actualizaciones ([código][m4b-updater]); Docker Hub y ghcr.io, para comprobar etiquetas de imagen ([código][m4b-registry]); cuando ejecutas la comprobación de IP, `api.ipify.org`, `ifconfig.me` o `icanhazip.com` para tu IP pública e `ip-api.com` por HTTP sin cifrar para las puntuaciones de IP ([código][m4b-ipscore]) | Versiones de GitHub ([código][igm-version]); `api.ipify.org`, `ifconfig.me` o `icanhazip.com` para tu IP pública ([código][igm-ifconfig]); `ip-api.com` por HTTP sin cifrar para las puntuaciones de IP ([código][igm-ipscore]). El binario cerrado no se revisó | No se encontró nada | No se encontró nada | No se encontró nada |

### Notas sobre la columna de CashPilot { #cashpilot-notes }

- **Muchos proxies o IP.** Desde la v1.69.0, CashPilot ejecuta copias adicionales de un servicio ya desplegado en un worker, cada una a través de su propio proxy. SOCKS5 y HTTP CONNECT solo transportan TCP: el túnel solo deja salir TCP hacia el puerto del proxy, así que los relays UDP de SOCKS5 se descartan. Un exit node de Tailscale también transporta UDP. La app de ingresos comparte el espacio de nombres de red de un contenedor de túnel ([código][cp-proxy-deploy]). Ese espacio de nombres solo deja salir el loopback, el túnel y la propia conexión del túnel con el proxy: TCP hacia su dirección y su puerto, o los paquetes marcados de tailscaled ([firewall del túnel][cp-tunnel-fw]). Así, un proxy caído detiene la app de ingresos en lugar de dejar escapar su tráfico ([cómo funciona](proxies.md#how-it-works)). Un servicio no puede funcionar a través de un proxy cuando necesita red del host, puertos publicados, volúmenes, dispositivos, una GPU o `NET_ADMIN`, `NET_RAW` o `SYS_ADMIN`, o cuando sus condiciones prohíben los proxies. Por eso, <!-- n:noproxy -->10<!-- /n --> de las <!-- n:docker -->21<!-- /n --> apps de ingresos solo ganan desde la IP propia del servidor ([qué no puede](proxies.md#what-cannot-run-through-a-proxy)).
- **Ganancias.** Algunos recolectores necesitan una cookie o un token copiados de tu navegador, y algunos de ellos caducan. La guía de cada servicio dice cuáles.
- **Credenciales en reposo.** La UI guarda el archivo de la clave de cifrado en el mismo volumen de datos que la base de datos ([código][cp-fernet]). Las credenciales de las apps de ingresos llegan a cada worker como variables de entorno del contenedor, así que están en texto plano en la configuración de Docker de ese worker (`docker inspect`).
- **Ajustes de los contenedores de las apps de ingresos.** El worker quita todas las capabilities y después devuelve las que el catálogo indica para el servicio. Pone `no-new-privileges` y un límite de pids, y rechaza los contenedores privilegiados ([código][cp-hardening], [código][cp-privileged], [ajustes de seguridad por defecto](security-defaults.md)). Mysterium se ejecuta en su propio espacio de nombres de red en el bridge con barrera, con `NET_ADMIN`, `SETUID` y `SETGID`, en una imagen fijada por digest ([catálogo][cp-myst]). Un runtime gVisor opcional puede añadir un kernel en espacio de usuario ([runtimes](security-defaults.md#container-runtimes-gvisor-where-it-works)).
- **Socket de Docker.** Desde la v1.71.0, el worker no tiene socket. Lo tiene el proxy del socket: sockguard 2.4.7, fijado por digest, en solo lectura ([compose][cp-sock]). El worker recibe una copia filtrada que rechaza contenedores privilegiados, montajes de `/` o del socket, y capabilities o dispositivos fuera de los del catálogo ([proxy del socket](security-defaults.md#docker-socket-proxy)). El contenedor de un solo uso `cashpilot-migrate` también monta el socket. Pone la etiqueta de propietario a los volúmenes y a la red de la barrera que crearon las versiones anteriores, y vuelve a crear sus contenedores sobre ellos, para que el aislamiento por propietario del proxy los cubra. Termina antes de que arranque el proxy ([compose][cp-migrate]). Una app de ingresos nunca recibe el socket ([código][cp-mounts]). El proxy todavía no es una frontera de root. Con `CASHPILOT_COMPOSE_DIR` o `CASHPILOT_PROXY_BIND_MOUNTS` configuradas, un worker comprometido puede colocar un enlace simbólico en una carpeta permitida con un contenedor y llegar al `/` del host con un segundo ([detalles](security-defaults.md#docker-socket-proxy)). Las fichas de Unraid y TrueNAS siguen montando el socket sin filtrar en el worker ([tiendas de apps](app-stores.md)).
- **Aislamiento de la LAN.** Activado por defecto desde la v1.70.0, en las instalaciones nuevas y en las actualizadas sin ninguna app de ingresos en el bridge por defecto de Docker. El worker pone las apps de ingresos en su propio bridge y escribe una tabla de firewall para él ([código][cp-fence]). La tabla descarta los rangos privados, el rango de la tailnet, los metadatos de la nube, las subredes conectadas del host y el propio host. Con la detección de IP pública activada, también descarta la IP pública de la casa ([aislamiento](isolation.md#lan-isolation-by-default)). Una instalación actualizada cuyas apps de ingresos ya están en el bridge por defecto se queda ahí hasta que pulses **Turn on isolation** (Activar aislamiento). `CASHPILOT_ISOLATION=off` lo desactiva. Con `CASHPILOT_CONTAINER_NETWORK` configurada, CashPilot no escribe ninguna barrera para esa red, y las reglas del firewall son cosa tuya. En Podman no hay barrera, y la página de la flota lo indica ([modos](isolation.md#modes), [código][cp-fence-mode]). Desde la 2.0.7, Mysterium también queda tras la barrera. Un nodo desplegado hasta la 2.0.6 sigue en la red del host hasta que lo vuelvas a desplegar ([Mysterium detrás de la barrera](mysterium-fence.md)). Una comprobación muestra a qué pueden llegar las apps de ingresos ([comprobación](isolation-check.md)).
- **Llamadas salientes.** Además de las propias apps, CashPilot llama a:
    - las versiones de GitHub, una vez al día, para su comprobación de actualizaciones (`CASHPILOT_UPDATE_CHECK=off` lo detiene, [código][cp-update]).
    - `api.ipify.org`, `ifconfig.me` o `icanhazip.com` una vez por hora desde cada worker, para su IP pública (`CASHPILOT_EGRESS_DETECT=off` lo detiene, [código][cp-egress]).
    - CoinGecko y Frankfurter, para los tipos de cambio ([código][cp-rates]).
    - mempool.space, api.kaspa.org y nodos RPC públicos de Ethereum, Ethereum Classic, Polygon y Solana, para los [saldos on-chain](onchain.md).
    - iptoasn.com, para la tabla de nombres de red de CashPilot, como mucho una vez por semana y solo mientras un worker tiene la [actividad](activity.md#network-names-and-countries) activada ([código][cp-ipgeo]).
    - cada proveedor, para los recolectores.

    El navegador carga Google Fonts ([plantilla][cp-cdn]) y Chart.js desde jsDelivr ([plantilla][cp-chartjs]).

Ninguno de los proyectos envía telemetría de uso en el código que leímos. El binario cerrado de IGM no se pudo leer.

Todos los proyectos de esta lista pasan las credenciales de las apps a los contenedores como variables de entorno, e InternetIncome pasa además algunas como argumentos de comando, así que en el host que ejecuta las apps están en texto plano en la configuración del contenedor de Docker (`Env` y `Args` en `docker inspect`), legibles para cualquiera con acceso a Docker. La fila «Credenciales en reposo» describe solo la copia guardada.

## Cómo contamos { #how-we-counted }

- **CashPilot.** Servicios del catálogo con estado activo o beta y una imagen de Docker, sin contar el cómputo con GPU ni los pools de minería. El número de esta página sale de `scripts/generate_readme_tables.py`, y la CI falla si se desvía.
- **money4band 5.0.0.** Un archivo JSON por app en `config/catalog/supported/`: 15. Las «35 apps» del README cuentan también el catálogo de la comunidad, que está desactivado por defecto ([configuración][m4b-community]), apps sin imagen de Docker y apps retiradas.
- **IGM.** Entradas de `apps.json`: 20, todas activadas. No se cuentan el contenedor del proxy, Watchtower ni los sidecars de reclamación.
- **InternetIncome.** Cada bloque de comentario `# Starting ... container` de `internetIncome.sh`, salvo los bloques del proxy y de Watchtower: 24. Los bloques de Chrome y Firefox de Ebesucher son una sola app, igual que EarnFM y EarnFM Fleetshare, que usan la misma cuenta de EarnFM. El bloque de extensiones Depin arranca Grass y Gradient ([script][ii-depin]), dos apps. Total: 23. La tabla del README enumera 27 apps, algunas solo con un enlace de registro.
- **CashFactory.** Servicios que generan ingresos en `docker-compose.yml`: 11. No se cuentan Portainer, el servidor web ni los dos Watchtower. Un servicio está comentado.
- **Complementos de HA.** Carpetas de complementos con un archivo de configuración: 10.

No comprobamos si cada app de cada lista sigue pagando.

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L541-L557
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L51
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/orchestrator.py#L1534-L1541
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1977-L1978
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1586-L1631
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/services/bandwidth/mysterium.yml#L25-L27
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L125-L180
[cp-update]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/update_check.py#L46-L56
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/exchange_rates.py#L125-L145
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L373-L380
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L292
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/proxy_tunnel.py#L1145
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/tunnel/cp-tunnel#L1-L27
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L103-L125
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L29-L52
[cp-ipgeo]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/ipgeo.py#L1-L40
[cp-migrate]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L91-L101
