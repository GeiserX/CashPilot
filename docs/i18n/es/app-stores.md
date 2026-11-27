---
source_hash: e99e2c0c80bb
---
# Tiendas de apps { #app-stores }

Puedes instalar CashPilot desde la tienda de apps de varios sistemas para servidores domésticos.
Cada ficha instala el panel (`drumsergio/cashpilot`) y el worker
(`drumsergio/cashpilot-worker`), que arranca y detiene los contenedores
de los servicios. Solo los paquetes de CasaOS y Runtipi de este repositorio instalan además
el proxy del socket de Docker de `docker-compose.yml`, así que su worker
nunca tiene el socket de Docker directo. Las plantillas de Unraid, la app de TrueNAS y
el paquete del pull request abierto en la tienda de apps de CasaOS siguen montando el socket
de Docker directamente en el worker.

Uses la tienda que uses, mantén el panel en tu LAN o tu VPN. Puede dar órdenes
al worker, y el worker controla Docker en el host. Cuando el propio worker tiene
el socket, eso equivale a root en el host.

## Disponible hoy { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Busca **CashPilot** en la pestaña Apps e instala las dos plantillas:
`cashpilot` (el panel) y `cashpilot-worker`. Pon la misma
`CASHPILOT_API_KEY` en las dos.

Las plantillas vienen de https://github.com/GeiserX/docker-templates y siguen
la etiqueta de imagen `latest`, así que los usuarios de Community Applications reciben cada versión
sin ningún cambio en la plantilla.

### TrueNAS SCALE { #truenas-scale }

CashPilot está en el train **community** de TrueNAS. Abre Apps, después Discover Apps,
y busca **CashPilot**.

La definición de la app se mantiene en
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot y fija
un digest de imagen exacto. Los propios bots de TrueNAS la mueven a las versiones nuevas, así que puede
ir unas cuantas versiones por detrás del CashPilot más reciente.

## En espera de revisión { #waiting-for-review }

### CasaOS { #casaos }

Hay un pull request abierto en la tienda de apps de CasaOS:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Hasta que se fusione, instálalo como app personalizada: en CasaOS elige App Store,
después Custom Install, después Import, y pega el contenido de
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Necesita CasaOS 0.4.5 o posterior: desde esa versión, su gestor de apps se basa en
Docker Compose 2.23, que lee del archivo la política del proxy del socket.
Las versiones anteriores la descartan, y entonces el worker no puede llegar a Docker.

Ese archivo fija una versión exacta. Antes de importarlo, pon las dos etiquetas de imagen
(`drumsergio/cashpilot` y `drumsergio/cashpilot-worker`) en la versión más reciente
de https://github.com/GeiserX/CashPilot/releases. La política del proxy
del archivo sigue a `main`; si la página de estado del worker dice que su política está
desactualizada, vuelve a importar el archivo.

## Preparado, aún no enviado { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

El paquete está listo en
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
pero todavía no está en la tienda de apps de Runtipi. Para usarlo ya, añádelo a una tienda de apps
personalizada que controles, siguiendo la documentación de Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## No disponible { #not-offered }

Umbrel necesita otro diseño de worker, porque las apps de Umbrel llegan a Docker
a través de un contenedor Docker-in-Docker y no del socket del host. No lo hemos
probado, así que todavía no hay paquete para Umbrel.

Para cualquier otro sistema, usa `docker-compose.yml` del repositorio, como en
[Primeros pasos](getting-started.md).
