---
source_hash: 915470497dbc
---
# Preguntas frecuentes { #faq }

**¿Es seguro compartir ancho de banda?**

Los servicios para compartir ancho de banda suelen dirigir por tu conexión tráfico legítimo (estudios de mercado, verificación de anuncios, comparación de precios, distribución de contenidos). Aun así, compartes tu dirección IP, así que lee con atención las condiciones del servicio y la política de privacidad de cada uno antes de registrarte. En algunos servicios es posible ejecutarlos en un VPS en lugar de con una IP residencial. **Esto no es asesoramiento legal: consulta con los servicios concretos que piensas usar y, si hace falta, busca asesoramiento legal independiente sobre tu jurisdicción.**

**¿Cuánto puedo ganar?**

Las ganancias varían mucho según la ubicación, el proveedor de internet, el número de dispositivos y los servicios que ejecutes. El panel sigue tus ganancias reales a lo largo del tiempo para que puedas optimizar tu configuración. Como orientación aproximada, y no como promesa, un servidor doméstico con 10 a 15 servicios gana unos $30 a $100 al mes, y puede ganar menos, hasta cero. Más servidores, o el cómputo con GPU, suman a eso.

**¿Puedo ejecutarlo en un VPS o en un servidor en la nube?**

Algunos servicios necesitan una IP residencial y no pagan (o bloquean) las IP de VPS o de centros de datos. El catálogo indica «residential IP» (IP residencial) entre lo que necesitan. Los servicios que funcionan en un VPS son una buena forma de crecer sin más hardware en casa.

**¿Cómo se guardan las credenciales?**

Todas las credenciales de los servicios se cifran en reposo en la base de datos SQLite con una clave Fernet guardada en `/data/.fernet_key`, que se genera automáticamente en el primer arranque. El archivo de la base de datos está en el volumen de Docker montado (`cashpilot_data:/data`). Las credenciales nunca se envían a ningún sitio, salvo a los propios contenedores de los servicios.

Ten en cuenta que esta clave es distinta de `CASHPILOT_SECRET_KEY`, que solo firma las sesiones de inicio de sesión.

### Copia de seguridad de la clave de cifrado { #backing-up-the-encryption-key }

Tus credenciales solo se pueden recuperar si conservas `/data/.fernet_key`. Si pierdes ese archivo, tendrás que volver a introducir todas las credenciales, porque sin él no hay forma de descifrar los valores guardados.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

El archivo siempre tiene prioridad sobre la variable de entorno, así que configurar `CASHPILOT_ENCRYPTION_KEY` en una instancia que ya tiene clave no cambia nada y es seguro. Solo se adopta cuando no existe ningún archivo de clave, que es justo el caso de una restauración.

Si CashPilot no puede escribir la clave en el disco de ninguna manera, porque `/data` no admite escritura o no está montado, se niega a arrancar antes que cifrar tus credenciales con una clave que desaparecería en el siguiente reinicio. Configura `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` si de verdad es lo que quieres.

<a id="forgot-password"></a>

### He olvidado la contraseña o el nombre de usuario { #forgot-password-or-username }

CashPilot no tiene restablecimiento por correo electrónico. Quien administra el servidor restablece la contraseña desde la consola del contenedor de la UI de CashPilot. Tus servicios, tus ganancias y tus credenciales guardadas no se ven afectados: están cifrados con `/data/.fernet_key`, no con tu contraseña.

El comando `python -m app.users` necesita CashPilot 2.3 o posterior. En la 2.2 o anteriores falla con `No module named app.users`. Actualiza primero: con Docker Compose, cambia las etiquetas `drumsergio/cashpilot` y `drumsergio/cashpilot-worker` a `2.3` o posterior (una fijación como `2.2` o `2.2.9` se queda en esa versión) y después ejecuta `docker compose up -d` ([Actualizar CashPilot](getting-started.md#updating-cashpilot)). En Unraid, actualiza el contenedor.

1. Lista las cuentas. Esto también muestra un nombre de usuario que hayas olvidado. Los nombres de usuario distinguen entre mayúsculas y minúsculas.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Pon una nueva contraseña aleatoria a la cuenta. Sustituye `alice` por el nombre de usuario del paso 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Si hay exactamente un propietario, puedes omitir el nombre de usuario y el comando restablece la de ese propietario. Si el nombre de usuario empieza por `-`, pon `--` delante: `reset-password -- -alice`.

    El comando muestra la nueva contraseña una sola vez.

3. Si otra persona pudo tener acceso a la cuenta, reinicia ahora el contenedor de la UI (`docker restart cashpilot-ui`). Los navegadores que seguían con la sesión iniciada como ese usuario solo se cierran tras un reinicio. Si solo olvidaste la contraseña, el reinicio es opcional.
4. Inicia sesión con la nueva contraseña y después cámbiala desde el menú del avatar (arriba a la derecha), **Change password** (Cambiar contraseña).

El nombre del contenedor depende de cómo instalaste CashPilot:

| Instalación | Contenedor de la UI |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | un nombre generado; `docker ps` lo muestra |

Portainer, Unraid y CasaOS también tienen un botón de consola para cada contenedor. El comando no necesita entrada por terminal, así que también funciona ahí.

Para cambiar un nombre de usuario:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

El nombre nuevo sigue la regla del registro: de 3 a 32 letras, dígitos, `_` o `-`. Cierra la sesión y vuelve a entrar para verlo.

**Tras una sospecha de intrusión**, por ejemplo una copia de seguridad perdida que contiene `/data/.secret_key`, restablecer la contraseña no basta. Quien tenga esa clave puede firmar una cookie de inicio de sesión válida, y un restablecimiento no lo impide. Sustituye la clave y después reinicia el contenedor de la UI. El `&&` lo reinicia solo cuando la nueva clave está en su sitio; si el comando muestra un error, resuélvelo primero:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Tras el reinicio se cierra la sesión en todos los navegadores, y todo el mundo vuelve a entrar con su contraseña. Las credenciales guardadas no se ven afectadas. Si configuraste tú `CASHPILOT_SECRET_KEY`, el comando se niega: en su lugar, pon un nuevo valor aleatorio en esa variable y vuelve a crear el contenedor. Un `docker run` desde la imagen no ve esa variable y no puede negarse, así que usa `docker exec` sobre el contenedor de la UI.

Una clave nueva acaba con las cookies falsificadas, pero no con lo que el atacante hizo mientras estuvo dentro. Dos pasos más:

1. Ejecuta `docker exec cashpilot-ui python -m app.users list`. Elimina desde el panel cualquier cuenta que no reconozcas.
2. Si la copia perdida contenía todo `/data`, cambia las contraseñas de tus cuentas en los proveedores. `.fernet_key` y `cashpilot.db` juntos descifran todas las credenciales guardadas.

Si más adelante restauras una copia de seguridad hecha antes de la rotación, deja fuera su `.secret_key` ([Copia de seguridad y restauración](backup-restore.md#restore)), o vuelve a rotar y reiniciar. Si no, vuelve la clave antigua. La base de datos restaurada también recupera las cuentas y contraseñas que contenía, así que repite la comprobación de cuentas y cualquier restablecimiento de contraseña.

**Si el contenedor de la UI no arranca**, ejecuta el comando desde la misma imagen sobre los mismos datos. Primero busca la carpeta del host que contiene el `/data` de la UI. Esto funciona con un contenedor detenido, y tanto con un volumen con nombre como con un bind mount (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Después monta esa carpeta y usa la etiqueta de imagen que ejecutas:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Comprueba que la lista muestra tus cuentas y después ejecuta la misma línea con `reset-password alice` en lugar de `list`.

Una ruta sin base de datos da un error «no database», y el comando no crea ni cambia nada ahí. Aun así, puede que Docker deje una carpeta o un volumen vacío con ese nombre; elimínalo.

**No** borres el volumen de datos: eso borra `/data/.fernet_key` y, con él, todas las credenciales guardadas. **Tampoco** borres filas de la tabla `users`.

**¿Cómo elimino CashPilot por completo?**

`docker compose down -v` elimina solo los contenedores propios de CashPilot. Los servicios que desplegó siguen en marcha, y se quedan sus datos, la red con barrera y una tabla del firewall. [Eliminar CashPilot por completo](uninstall.md) lo elimina todo, explica qué se pierde para siempre y muestra cómo comprobar que no queda nada.

**¿Y la seguridad?**

Cada servicio que despliega CashPilot se ejecuta en su propio contenedor, sin ninguna capability de Linux (algunos servicios recuperan solo las que declaran) y con `--security-opt no-new-privileges`, para que un proceso de dentro no pueda obtener privilegios. Los contenedores no ven el sistema de archivos del host más allá de los volúmenes que declara un servicio. En una instalación nueva, el worker además los separa con una barrera de tu LAN, del host, de tu tailnet y de los metadatos de la nube, para que lleguen a internet y a nada local ([Aislamiento de red](isolation.md)). En Podman la barrera no está disponible: las apps de ingresos se ejecutan en la red por defecto de Podman, que puede llegar a tu LAN, y la página Fleet (Flota) lo indica ([Aislamiento de red](isolation.md) enumera las opciones). Una instalación actualizada desde una versión anterior a la 1.70 mantiene sus apps de ingresos en el bridge por defecto de Docker, que puede llegar a tu LAN, hasta que hagas clic en **Turn on isolation** (Activar aislamiento) en la página Fleet. Desde la 2.0.7, Mysterium también funciona detrás de la barrera; un nodo desplegado con la 2.0.6 o anteriores se queda en la red del host hasta que lo vuelvas a desplegar ([Mover tu nodo de Mysterium detrás de la barrera](mysterium-fence.md)). [Proteger tu red doméstica](home-network-security.md) explica, como alternativa, cómo poner un firewall a tu propio bridge. Las credenciales de los servicios se cifran en reposo con cifrado simétrico Fernet. La UI no tiene acceso a Docker. Con los archivos compose que se distribuyen, el worker nunca recibe el socket de Docker directo: llega a Docker a través de `cashpilot-socket-proxy`, que rechaza contenedores privilegiados y montajes de `/` o del socket (salvo que pongas uno de ellos, o una carpeta por encima del socket, en `CASHPILOT_PROXY_BIND_MOUNTS` o `CASHPILOT_COMPOSE_DIR`: el proxy los da por buenos), y limita el worker a los contenedores, volúmenes y redes con su etiqueta de propietario ([valores de seguridad por defecto](security-defaults.md)). Las plantillas de Unraid y la app de TrueNAS siguen montando el socket directo en el worker, lo que equivale a root en el host ([tiendas de apps](app-stores.md)).

Dicho esto, ninguna configuración es infalible. Sigues ejecutando software de terceros que dirige tráfico externo por tu red. El aislamiento de Docker reduce mucho la superficie de ataque en comparación con ejecutar estos servicios directamente en tu host, pero no elimina todo el riesgo. Te recomendamos ejecutar CashPilot en una máquina o VLAN dedicada, mantener al día Docker y el sistema operativo del host, y revisar el código abierto de cualquier servicio antes de desplegarlo.

**¿Qué pasa si el contenedor de un servicio se cae?**

CashPilot supervisa la salud de los contenedores de forma continua. Si el contenedor de un servicio termina de forma inesperada, se reinicia automáticamente. El panel muestra el tiempo en marcha y el estado de salud de cada servicio en ejecución.

**Mi nodo de Mysterium no arranca después de volver a desplegarlo. ¿Por qué?**

La causa más habitual es un puerto de su rango UDP que ya ocupa otro programa del host. Docker tiene que reservar todos los puertos del rango, así que un solo puerto ocupado impide el arranque. [Elegir el rango de puertos UDP](mysterium-fence.md#choosing-the-udp-port-range) explica cómo elegir un rango que quede libre.

**Mi copia por proxy está en marcha pero no gana nada. ¿Por qué?**

Puede que el proxy se niegue a conectar con los servidores de esa app de ingresos, o que solo permita los puertos 80 y 443. El botón **Test** (Probar) de CashPilot solo comprueba que el proxy llega a internet. [Comprobar los servidores de una app de ingresos a través del proxy](proxies.md#probe-an-earners-servers-through-the-proxy) muestra cómo comprobar el host y el puerto de la propia app de ingresos.

**¿Qué servicios son pesados y dónde conviene ejecutarlos?**

Los nodos de almacenamiento, los relays y las salidas de VPN, y el trabajo con GPU son los que más consumen. [Presupuestar un equipo pequeño](fleet.md#budgeting-a-small-box) los enumera y muestra cómo medir cada contenedor antes de decidir.

<a id="worker-lost-docker"></a>

### El worker perdió Docker tras una actualización de Docker { #the-worker-lost-docker-after-a-docker-update }

**Lo que ves.** El worker sigue en línea en la página Fleet, pero CashPilot no puede arrancar, detener ni actualizar sus contenedores. La página Fleet muestra **Docker unreachable** (Docker inaccesible) junto al worker. Pasados 10 minutos, falla el healthcheck del worker (`docker ps` muestra el worker como `unhealthy`). Pasados 30 minutos, la campana y tus notificaciones dicen que el worker no puede llegar a Docker. `docker logs cashpilot-socket-proxy` muestra `upstream Docker socket unreachable` y, con un archivo compose actual, `docker ps` muestra el proxy como `unhealthy` en unos 3 minutos. Tus apps de ingresos siguen en marcha.

**Causa.** Los archivos compose que se distribuyen montan el archivo del socket `/var/run/docker.sock` en `cashpilot-socket-proxy`. Un montaje de archivo se queda con ese archivo concreto. Una actualización de Docker (por ejemplo, `unattended-upgrades` instalando un `docker-ce` nuevo) reinicia Docker, y Docker crea un archivo de socket nuevo en la misma ruta. Con el live-restore de Docker activado, el proxy sigue en marcha durante ese reinicio y conserva el archivo antiguo. Nadie responde en el archivo antiguo.

**Solución rápida.** En esa máquina, reinicia el proxy:

```bash
docker restart cashpilot-socket-proxy
```

El reinicio monta el socket nuevo, y el worker vuelve a encontrar Docker en su siguiente señal de vida. No hace falta reiniciar el worker. En Unraid y TrueNAS el propio worker tiene el socket, así que reinicia el worker.

**Solución duradera.** Monta la carpeta del socket, no el archivo del socket. Un montaje de carpeta muestra al momento un socket sustituido. En el servicio `cashpilot-socket-proxy` de tu archivo compose, sustituye la línea `- /var/run/docker.sock:/var/run/docker.sock:ro` por el montaje de abajo, y añade la línea `SOCKGUARD_UPSTREAM_SOCKET` a su `environment`:

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

Después ejecuta `docker compose up -d`. El mismo cambio funciona en `docker-compose.worker.yml` y `docker-compose.fleet.yml`. Compose solo lee esos archivos cuando los nombras, así que ejecuta `docker compose -f docker-compose.worker.yml up -d` o `docker compose -f docker-compose.fleet.yml up -d`, salvo que `COMPOSE_FILE` ya nombre el archivo.

- `recursive: disabled` es necesario. `/var/run` contiene otros montajes, por ejemplo los espacios de nombres de red de Docker en `/run/docker/netns` y `/run/user/...`. Un montaje recursivo los mete todos en el proxy. Un montaje no recursivo muestra solo la propia carpeta.
- `SOCKGUARD_UPSTREAM_SOCKET` lleva el proxy a la nueva ruta. El bloque de la política y su huella se quedan como están, porque la variable de entorno sustituye a `upstream.socket` en la política. Sin la variable, el proxy no arranca (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` puede conservar su montaje de archivo. Se vuelve a iniciar en cada `docker compose up`, así que siempre recibe el socket actual. Si le das el mismo montaje de carpeta, añade `DOCKER_HOST=unix:///host-run/docker.sock` a su `environment`. El worker 2.8.4 y posteriores leen esa variable. Nunca la apuntes al socket del proxy: el migrador necesita el del propio host.
- El montaje de carpeta da al proxy todos los sockets de `/var/run`, no solo el de Docker. En un servidor típico eso incluye el socket del propio systemd, D-Bus y los sockets de herramientas como Tailscale o snapd. `read_only` no impide que un programa se conecte a un socket, y el proxy se ejecuta como root. El acceso al socket de Docker ya da root en el host, así que un proxy comprometido gana poco que no tuviera ya. Si quieres que el proxy tenga solo el socket de Docker, conserva el montaje de archivo y reinicia el proxy tras cada actualización de Docker: la alerta de arriba te avisa de cuándo.
- Necesita Docker Compose 2.30.0 o posterior. Las versiones anteriores rechazan el archivo entero con `Additional property recursive is not allowed`. Ejecuta `docker compose version` para comprobarlo. Debian 13 empaqueta Compose 2.26.1, así que en Debian instala Compose desde el repositorio del propio Docker. La actualización desde la app usa su propio Compose 2.33, así que lee el archivo modificado.
- Solo funciona en Linux. Docker Desktop en macOS y Windows solo mapea `/var/run/docker.sock` a su máquina virtual. Ahí, `/var/run` es una carpeta de tu Mac o tu PC, sin ningún socket de Docker dentro.
- Con Docker rootless, el socket está en `/run/user/<your uid>`, que es un montaje aparte. Usa esa carpeta como `source`.
- En Podman, conserva el montaje de archivo. No hemos probado ahí el montaje de carpeta.

Los archivos que se distribuyen conservan el montaje de archivo, porque el montaje de carpeta necesita Compose 2.30 y Linux, y CashPilot también es compatible con versiones anteriores de Compose y con Docker Desktop. Un archivo compose más reciente que descargues no lleva tu cambio, así que vuelve a hacerlo después de sustituir el archivo.
