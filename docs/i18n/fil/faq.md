---
source_hash: 915470497dbc
---
# Mga madalas itanong { #faq }

**Ligtas ba ang bandwidth sharing?**

Karaniwang nagruruta ang mga bandwidth sharing service ng lehitimong traffic (market research, ad verification, paghahambing ng presyo, content delivery) sa pamamagitan ng iyong koneksyon. Gayunpaman, ibinabahagi mo ang iyong IP address, kaya basahing mabuti ang terms of service at privacy policy ng bawat serbisyo bago mag-sign up. Para sa ilang serbisyo, opsyon ang pagpapatakbo ng mga ito sa isang VPS sa halip na sa residential IP. **Hindi ito legal na payo -- kumonsulta sa mismong mga serbisyong balak mong gamitin at, kung kailangan, humingi ng hiwalay na legal na payo tungkol sa iyong hurisdiksyon.**

**Magkano ang maaari kong kitain?**

Malaki ang pagkakaiba-iba ng kita ayon sa lokasyon, ISP, bilang ng device, at kung aling mga serbisyo ang pinapatakbo mo. Sinusubaybayan ng dashboard ang aktwal mong kita sa paglipas ng panahon para ma-optimize mo ang iyong setup. Bilang magaspang na gabay, at hindi pangako, ang isang home server na nagpapatakbo ng 10 hanggang 15 serbisyo ay kumikita ng mga $30 hanggang $100 kada buwan, at maaari itong kumita nang mas kaunti, hanggang sa zero. Nadadagdagan iyon ng mas maraming server, o ng GPU compute.

**Maaari ba akong magpatakbo sa isang VPS o cloud server?**

May mga serbisyong nangangailangan ng residential IP at hindi magbabayad sa (o magba-ban ng) mga VPS/datacenter IP. Inililista ng katalogo ang "residential IP" sa ilalim ng kailangan nila. Ang mga serbisyong gumagana sa VPS ay magandang paraan para lumaki nang hindi nagdadagdag ng hardware sa bahay.

**Paano iniimbak ang mga credential?**

Naka-encrypt ang lahat ng credential ng serbisyo sa SQLite database gamit ang Fernet key na nakaimbak sa `/data/.fernet_key`, na awtomatikong ginagawa sa unang takbo. Nakatira ang database file sa naka-mount na Docker volume (`cashpilot_data:/data`). Walang credential na ipinapadala kahit saan maliban sa mismong mga container ng serbisyo.

Tandaan na iba ang key na ito sa `CASHPILOT_SECRET_KEY`, na nagsa-sign lang ng mga login session.

### Pag-backup ng encryption key { #backing-up-the-encryption-key }

Mababawi mo lang ang iyong mga credential hangga't nandiyan ang `/data/.fernet_key`. Kapag nawala mo ang file na iyon, kailangan mong ilagay muli ang bawat credential, dahil walang paraan para i-decrypt ang mga naka-imbak na value kung wala ito.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

Laging nananaig ang file sa environment variable, kaya ang pagtatakda ng `CASHPILOT_ENCRYPTION_KEY` sa isang instance na may key na ay walang binabago at ligtas. Ginagamit lang ito kapag walang key file, na mismong kaso ng pag-restore.

Kung hindi talaga maisulat ng CashPilot ang key sa disk, dahil hindi masusulatan o hindi naka-mount ang `/data`, tumatanggi itong magsimula sa halip na i-encrypt ang iyong mga credential gamit ang key na mawawala sa susunod na restart. Itakda ang `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` kung talagang iyon ang gusto mo.

<a id="forgot-password"></a>

### Nakalimutan ang password o username { #forgot-password-or-username }

Walang reset sa e-mail ang CashPilot. Ang nagpapatakbo ng server ang nagre-reset ng password mula sa console ng container ng CashPilot UI. Hindi naaapektuhan ang iyong mga serbisyo, kita at naka-save na credential: naka-encrypt ang mga ito gamit ang `/data/.fernet_key`, hindi gamit ang iyong password.

Kailangan ng command na `python -m app.users` ang CashPilot 2.3 o mas bago. Sa 2.2 o mas luma, pumapalya ito nang may `No module named app.users`. Mag-update muna: sa Docker Compose, palitan ang mga tag na `drumsergio/cashpilot` at `drumsergio/cashpilot-worker` sa `2.3` o mas bago (ang pin gaya ng `2.2` o `2.2.9` ay nananatili sa release na iyon), pagkatapos patakbuhin ang `docker compose up -d` ([Pag-update ng CashPilot](getting-started.md#updating-cashpilot)). Sa Unraid, i-update ang container.

1. Ilista ang mga account. Ipinapakita rin nito ang username na nakalimutan mo. Case-sensitive ang mga username.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Magtakda ng bagong random na password para sa account. Palitan ang `alice` ng username mula sa hakbang 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Kapag iisa lang ang may-ari, maaari mong alisin ang username, at ire-reset ng command ang may-aring iyon. Kung nagsisimula ang username sa `-`, maglagay ng `--` bago ito: `reset-password -- -alice`.

    Ipinapakita ng command ang bagong password nang isang beses.

3. Kung may ibang taong maaaring nakapasok sa account, i-restart na ngayon ang container ng UI (`docker restart cashpilot-ui`). Ang mga browser na naka-sign in pa bilang user na iyon ay nasa-sign out lang pagkatapos ng restart. Kung nakalimutan mo lang ang password, opsyonal ang restart.
4. Mag-sign in gamit ang bagong password, pagkatapos palitan ito mula sa avatar menu (kanang itaas), **Change password** (Palitan ang password).

Nakadepende ang pangalan ng container sa kung paano mo in-install ang CashPilot:

| Install | Container ng UI |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | isang ginawang pangalan; ipinapakita ito ng `docker ps` |

May console button din para sa container ang Portainer, Unraid at CasaOS. Hindi kailangan ng command ang input sa terminal, kaya gumagana rin ito roon.

Para palitan ang username:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

Sinusunod ng bagong pangalan ang patakaran sa pagpaparehistro: 3 hanggang 32 titik, numero, `_` o `-`. Mag-sign out at mag-sign in muli para makita ito.

**Pagkatapos ng pinaghihinalaang compromise**, halimbawa isang nawalang backup na may hawak ng `/data/.secret_key`, hindi sapat ang pag-reset ng password lang. Ang sinumang may hawak ng key na iyon ay makakapag-sign ng valid na login cookie, at hindi iyon napipigilan ng reset. Palitan ang key, pagkatapos i-restart ang container ng UI. Nire-restart lang ito ng `&&` kapag nakalagay na ang bagong key; kung may ipinapakitang error ang command, ayusin muna iyon:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Pagkatapos ng restart, nasa-sign out ang bawat browser, at muling nagsa-sign in ang lahat gamit ang kanilang password. Hindi naaapektuhan ang mga naka-save na credential. Kung ikaw mismo ang nagtakda ng `CASHPILOT_SECRET_KEY`, tumatanggi ang command: maglagay ng bagong random na value sa variable na iyon at gawing muli ang container sa halip. Hindi nakikita ng `docker run` mula sa image ang variable na iyon at hindi ito makakatanggi, kaya gamitin ang `docker exec` sa container ng UI.

Tinatapos ng bagong key ang mga pekeng cookie, pero hindi ang ginawa ng umaatake habang nasa loob siya. Dalawa pang hakbang:

1. Patakbuhin ang `docker exec cashpilot-ui python -m app.users list`. Burahin mula sa dashboard ang anumang account na hindi mo kilala.
2. Kung buong `/data` ang laman ng nawalang kopya, palitan ang mga password ng iyong mga account sa provider. Magkasamang nagde-decrypt ng bawat naka-save na credential ang `.fernet_key` at `cashpilot.db`.

Kung sa kalaunan ay magre-restore ka ng backup na kinuha bago ang rotation, huwag isama ang `.secret_key` nito ([Pag-backup at pag-restore](backup-restore.md#restore)), o mag-rotate at mag-restart muli. Kung hindi, babalik ang lumang key. Ibinabalik din ng na-restore na database ang mga account at password na hawak nito, kaya ulitin ang pagsusuri sa mga account at anumang pag-reset ng password.

**Kung hindi magsimula ang container ng UI**, patakbuhin ang command mula sa parehong image laban sa parehong data. Hanapin muna ang host folder na may hawak ng `/data` ng UI. Gumagana ito para sa nakahintong container, at para sa named volume pati sa bind mount (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Pagkatapos, i-mount ang folder na iyon at gamitin ang image tag na pinapatakbo mo:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Tingnan kung ipinapakita ng listahan ang iyong mga account, pagkatapos patakbuhin ang parehong linya na may `reset-password alice` kapalit ng `list`.

Ang path na walang database ay nagbibigay ng error na "no database", at walang ginagawa o binabago ang command doon. Maaari pa ring mag-iwan ang Docker ng walang lamang folder o volume na may ganoong pangalan; alisin ito.

**Huwag** burahin ang data volume: binubura niyon ang `/data/.fernet_key` at kasama nito ang bawat naka-save na credential. **Huwag** ding magbura ng mga row mula sa table na `users`.

**Paano ko ganap na aalisin ang CashPilot?**

Inaalis lang ng `docker compose down -v` ang sariling mga container ng CashPilot. Patuloy na tumatakbo ang mga serbisyong na-deploy nito, at nananatili ang kanilang data, ang nabakurang network at isang firewall table. Inaalis ng [Ganap na pag-alis ng CashPilot](uninstall.md) ang lahat ng iyon, sinasabi kung ano ang tuluyang mawawala, at ipinapakita kung paano tiyaking walang natira.

**Paano naman ang seguridad?**

Bawat serbisyong dine-deploy ng CashPilot ay tumatakbo sa sarili nitong container na tinanggalan ng bawat Linux capability (may ilang serbisyong nagbabalik lang ng mga idinedeklara nila) at may nakatakdang `--security-opt no-new-privileges`, kaya hindi makakakuha ng pribilehiyo ang isang proseso sa loob. Hindi nakikita ng mga container ang filesystem ng iyong host lampas sa mga volume na idinedeklara ng serbisyo. Sa bagong install, binabakuran din sila ng worker palayo sa iyong LAN, sa host, sa iyong tailnet at sa cloud metadata, kaya naaabot nila ang internet at walang lokal ([Isolation ng network](isolation.md)). Sa Podman, hindi available ang bakod: tumatakbo ang mga earner app sa default na network ng Podman, na nakakaabot sa iyong LAN, at sinasabi iyon ng pahinang **Fleet** (Fleet) (inililista ng [Isolation ng network](isolation.md) ang mga opsyon). Ang install na na-upgrade mula sa release bago ang 1.70 ay nananatiling may mga earner app sa default na bridge ng Docker, na nakakaabot sa iyong LAN, hanggang i-click mo ang **Turn on isolation** (I-on ang isolation) sa pahinang **Fleet** (Fleet). Mula 2.0.7, tumatakbo na rin ang Mysterium sa likod ng bakod; ang node na na-deploy hanggang 2.0.6 ay nananatili sa network ng host hanggang i-redeploy mo ito ([Paglipat ng iyong Mysterium node sa likod ng bakod](mysterium-fence.md)). Ang [Pagprotekta sa iyong home network](home-network-security.md) ang tumatalakay sa paglalagay ng firewall sa sarili mong bridge sa halip. Naka-encrypt habang naka-imbak ang mga credential ng serbisyo gamit ang Fernet symmetric encryption. Walang access sa Docker ang UI. Sa mga kasamang compose file, hindi kailanman binibigyan ang worker ng hilaw na Docker socket: naaabot nito ang Docker sa pamamagitan ng `cashpilot-socket-proxy`, na tumatanggi sa mga privileged container at sa pag-bind ng `/` o ng socket (maliban kung ilalagay mo ang isa sa mga ito, o isang folder sa itaas ng socket, sa `CASHPILOT_PROXY_BIND_MOUNTS` o `CASHPILOT_COMPOSE_DIR`: tinatanggap iyon ng proxy nang walang tanong), at nililimitahan ang worker sa mga container, volume at network na may owner label nito ([mga default sa seguridad](security-defaults.md)). Ang mga Unraid template at ang TrueNAS app ay nagma-mount pa rin ng hilaw na socket sa worker, na katumbas ng root sa host ([mga app store](app-stores.md)).

Gayunpaman, walang setup na hindi tinatablan. Nagpapatakbo ka pa rin ng third-party na software na nagruruta ng panlabas na traffic sa iyong network. Malaki ang ibinabawas ng isolation ng Docker sa attack surface kumpara sa direktang pagpapatakbo ng mga serbisyong ito sa iyong host, pero hindi nito inaalis ang lahat ng panganib. Inirerekomenda naming patakbuhin ang CashPilot sa isang nakalaang makina o VLAN, panatilihing updated ang Docker at ang OS ng iyong host, at suriin ang open-source na code ng anumang serbisyo bago ito i-deploy.

**Ano ang nangyayari kapag nag-crash ang container ng isang serbisyo?**

Patuloy na binabantayan ng CashPilot ang kalusugan ng mga container. Kapag hindi inaasahang lumabas ang container ng isang serbisyo, awtomatiko itong nire-restart. Ipinapakita ng dashboard ang uptime at status ng kalusugan para sa bawat tumatakbong serbisyo.

**Hindi magsimula ang aking Mysterium node pagkatapos ng redeploy. Bakit?**

Ang pinakakaraniwang dahilan ay isang port sa UDP range nito na hawak na ng ibang program sa host. Kailangang i-reserve ng Docker ang bawat port sa range, kaya napipigilan ng isang abalang port ang pagsisimula. Ipinapaliwanag ng [Pagpili ng UDP port range](mysterium-fence.md#choosing-the-udp-port-range) kung paano pumili ng range na nananatiling bakante.

**Tumatakbo ang aking proxied copy pero walang kinikita. Bakit?**

Maaaring tumanggi ang proxy na kumonekta sa mga server ng earner app na iyon, o pinapayagan lang ang mga port 80 at 443. Sinusuri lang ng **Test** (Subukan) ng CashPilot kung naaabot ng proxy ang internet. Ipinapakita ng [Subukan ang mga server ng earner app sa pamamagitan ng proxy](proxies.md#probe-an-earners-servers-through-the-proxy) kung paano tingnan ang sariling host at port ng earner app.

**Aling mga serbisyo ang mabigat, at saan dapat tumakbo ang mga ito?**

Ang mga storage node, relay at VPN exit, at ang GPU na trabaho ang pinakamalakas gumamit. Inililista sila ng [Pagba-budget sa isang maliit na makina](fleet.md#budgeting-a-small-box) at ipinapakita kung paano sukatin ang bawat container bago ka magpasya.

<a id="worker-lost-docker"></a>

### Nawalan ng Docker ang worker pagkatapos ng update ng Docker { #the-worker-lost-docker-after-a-docker-update }

**Ang nakikita mo.** Nananatiling online ang worker sa pahinang **Fleet** (Fleet), pero hindi kayang simulan, ihinto o i-update ng CashPilot ang mga container nito. Ipinapakita ng pahinang **Fleet** (Fleet) ang **Docker unreachable** (Hindi maabot ang Docker) sa tabi ng worker. Pagkalipas ng 10 minuto, pumapalya ang healthcheck ng worker (ipinapakita ng `docker ps` ang worker bilang `unhealthy`). Pagkalipas ng 30 minuto, sinasabi ng bell at ng iyong mga notification na hindi maabot ng worker ang Docker. Ipinapakita ng `docker logs cashpilot-socket-proxy` ang `upstream Docker socket unreachable`, at sa kasalukuyang compose file, ipinapakita ng `docker ps` ang proxy bilang `unhealthy` sa loob ng mga 3 minuto. Patuloy na tumatakbo ang iyong mga earner app.

**Dahilan.** Bina-bind ng mga kasamang compose file ang socket file na `/var/run/docker.sock` sa `cashpilot-socket-proxy`. Hawak ng file bind ang iisang file na iyon. Nire-restart ng update ng Docker (halimbawa, ang `unattended-upgrades` na nag-i-install ng bagong `docker-ce`) ang Docker, at gumagawa ang Docker ng bagong socket file sa parehong path. Kapag naka-on ang live-restore ng Docker, patuloy na tumatakbo ang proxy sa restart na iyon at hawak pa rin ang lumang file. Walang sumasagot sa lumang file.

**Mabilis na ayos.** Sa makinang iyon, i-restart ang proxy:

```bash
docker restart cashpilot-socket-proxy
```

Bina-bind ng restart ang bagong socket, at muling nahahanap ng worker ang Docker sa susunod nitong heartbeat. Hindi mo kailangang i-restart ang worker. Sa Unraid at TrueNAS, ang worker mismo ang may hawak ng socket, kaya i-restart ang worker.

**Pangmatagalang ayos.** I-bind ang folder ng socket, hindi ang socket file. Agad na ipinapakita ng folder bind ang pinalitang socket. Sa serbisyong `cashpilot-socket-proxy` ng iyong compose file, palitan ang linyang `- /var/run/docker.sock:/var/run/docker.sock:ro` ng bind sa ibaba, at idagdag ang linyang `SOCKGUARD_UPSTREAM_SOCKET` sa `environment` nito:

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

Pagkatapos, patakbuhin ang `docker compose up -d`. Gumagana rin ang parehong pagbabago sa `docker-compose.worker.yml` at `docker-compose.fleet.yml`. Binabasa lang ng Compose ang mga file na iyon kapag pinangalanan mo sila, kaya patakbuhin ang `docker compose -f docker-compose.worker.yml up -d` o `docker compose -f docker-compose.fleet.yml up -d`, maliban kung pinangalanan na ng `COMPOSE_FILE` ang file.

- Kailangan ang `recursive: disabled`. May hawak na ibang mount ang `/var/run`, halimbawa ang mga network namespace ng Docker sa ilalim ng `/run/docker/netns` at `/run/user/...`. Dinadala ng recursive bind ang lahat ng iyon sa proxy. Ang folder lang mismo ang ipinapakita ng non-recursive bind.
- Itinuturo ng `SOCKGUARD_UPSTREAM_SOCKET` ang proxy sa bagong path. Nananatili ang policy block at ang fingerprint nito, dahil ino-override ng environment variable ang `upstream.socket` sa policy. Kung wala ang variable, hindi nagsisimula ang proxy (`upstream socket not found (/var/run/docker.sock)`).
- Maaaring panatilihin ng `cashpilot-migrate` ang file bind nito. Nagsisimula itong muli sa bawat `docker compose up`, kaya lagi nitong nakukuha ang kasalukuyang socket. Kung bibigyan mo ito ng parehong folder bind, idagdag ang `DOCKER_HOST=unix:///host-run/docker.sock` sa `environment` nito. Binabasa ng worker 2.8.4 at mas bago ang variable na iyon. Huwag kailanman itong ituro sa socket ng proxy: kailangan ng migrator ang sariling socket ng host.
- Ibinibigay ng folder bind sa proxy ang bawat socket sa `/var/run`, hindi lang ang sa Docker. Sa karaniwang server, kasama roon ang sariling socket ng systemd, ang D-Bus, at ang mga socket ng mga tool gaya ng Tailscale o snapd. Hindi napipigilan ng `read_only` ang isang program na kumonekta sa isang socket, at tumatakbo ang proxy bilang root. Nagbibigay na ng root sa host ang access sa Docker socket, kaya kaunti lang ang madadagdag sa isang na-compromise na proxy na wala pa rito. Kung gusto mong ang Docker socket lang ang hawak ng proxy, panatilihin ang file bind at i-restart ang proxy pagkatapos ng update ng Docker: sasabihin sa iyo ng alerto sa itaas kung kailan.
- Kailangan nito ang Docker Compose 2.30.0 o mas bago. Tinatanggihan ng mas lumang release ang buong file nang may `Additional property recursive is not allowed`. Patakbuhin ang `docker compose version` para tingnan. Compose 2.26.1 ang naka-package sa Debian 13, kaya sa Debian, i-install ang Compose mula sa sariling repository ng Docker. Gumagamit ang in-app update ng sarili nitong Compose 2.33, kaya nababasa nito ang binagong file.
- Sa Linux lang ito gumagana. Sa Docker Desktop sa macOS at Windows, ang `/var/run/docker.sock` lang ang naka-map sa virtual machine nito. Doon, ang `/var/run` ay isang folder sa iyong Mac o PC, na walang Docker socket.
- Sa rootless Docker, nasa `/run/user/<your uid>` ang socket, na hiwalay na mount. Gamitin ang folder na iyon bilang `source`.
- Sa Podman, panatilihin ang file bind. Hindi pa namin nasusubukan doon ang folder bind.

Pinapanatili ng mga kasamang file ang file bind, dahil kailangan ng folder bind ang Compose 2.30 at Linux, at sinusuportahan din ng CashPilot ang mas lumang release ng Compose at ang Docker Desktop. Wala sa mas bagong compose file na dina-download mo ang iyong pagbabago, kaya gawin itong muli pagkatapos mong palitan ang file.
