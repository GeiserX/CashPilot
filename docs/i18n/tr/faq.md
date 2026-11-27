---
source_hash: 915470497dbc
---
# SSS { #faq }

**Bant genişliği paylaşımı güvenli mi?**

Bant genişliği paylaşım hizmetleri genellikle meşru trafiği (pazar araştırması, reklam doğrulama, fiyat karşılaştırma, içerik dağıtımı) bağlantınız üzerinden yönlendirir. Yine de IP adresinizi paylaşıyorsunuz, bu yüzden kaydolmadan önce her hizmetin hizmet koşullarını ve gizlilik politikasını dikkatle inceleyin. Bazı hizmetlerde bunları ev IP'si yerine bir VPS üzerinde çalıştırmak bir seçenektir. **Bu hukuki tavsiye değildir -- kullanmayı düşündüğünüz hizmetlere danışın ve gerekirse yargı bölgenizle ilgili bağımsız hukuki danışmanlık alın.**

**Ne kadar kazanabilirim?**

Kazançlar konuma, internet sağlayıcısına, cihaz sayısına ve hangi hizmetleri çalıştırdığınıza göre büyük ölçüde değişir. Pano, kurulumunuzu iyileştirebilmeniz için gerçek kazançlarınızı zaman içinde izler. Kabaca bir fikir vermek için, ve bir vaat olarak değil: 10 ila 15 hizmet çalıştıran bir ev sunucusu ayda yaklaşık $30 ila $100 kazandırır ve daha azını, sıfıra kadar, kazandırabilir. Daha fazla sunucu veya GPU işlem gücü bunun üzerine ekler.

**Bir VPS veya bulut sunucusunda çalıştırabilir miyim?**

Bazı hizmetler ev IP'si gerektirir ve VPS/veri merkezi IP'lerine ödeme yapmaz (ya da onları yasaklar). Katalog, gereksinimler altında "residential IP" ifadesini listeler. VPS'te çalışan hizmetler, ek ev donanımı olmadan ölçeği büyütmenin iyi bir yoludur.

**Kimlik bilgileri nasıl saklanır?**

Tüm hizmet kimlik bilgileri, SQLite veritabanında `/data/.fernet_key` konumunda saklanan ve ilk çalıştırmada otomatik olarak üretilen bir Fernet anahtarıyla diskte şifrelenir. Veritabanı dosyası bağlanan Docker biriminde (`cashpilot_data:/data`) bulunur. Kimlik bilgileri hizmet konteynerlerinin kendileri dışında hiçbir yere gönderilmez.

Bunun, yalnızca oturum açma oturumlarını imzalayan `CASHPILOT_SECRET_KEY` değerinden farklı bir anahtar olduğunu unutmayın.

### Şifreleme anahtarını yedekleme { #backing-up-the-encryption-key }

Kimlik bilgilerinizi kurtarabilmeniz tamamen `/data/.fernet_key` dosyasına bağlıdır. O dosyayı kaybederseniz her kimlik bilgisini yeniden girmeniz gerekir, çünkü o dosya olmadan saklanan değerlerin şifresini çözmenin bir yolu yoktur.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

Dosya her zaman ortam değişkeninden önceliklidir, bu yüzden zaten bir anahtarı olan bir kurulumda `CASHPILOT_ENCRYPTION_KEY` ayarlamak hiçbir şeyi değiştirmez ve güvenlidir. Değişken yalnızca hiçbir anahtar dosyası olmadığında benimsenir; bu da tam olarak geri yükleme durumudur.

CashPilot anahtarı diske hiç yazamazsa (`/data` yazılamaz veya bağlanmamış olduğu için), kimlik bilgilerinizi bir sonraki yeniden başlatmada kaybolacak bir anahtarla şifrelemek yerine başlamayı reddeder. Gerçekten istediğiniz buysa `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` ayarlayın.

<a id="forgot-password"></a>

### Parolayı veya kullanıcı adını unuttum { #forgot-password-or-username }

CashPilot'ta e-postayla sıfırlama yoktur. Parolayı, sunucuyu çalıştıran kişi CashPilot UI konteynerinin konsolundan sıfırlar. Hizmetleriniz, kazançlarınız ve kaydedilmiş kimlik bilgileriniz etkilenmez: bunlar parolanızla değil, `/data/.fernet_key` ile şifrelenir.

`python -m app.users` komutu CashPilot 2.3 veya daha yenisini gerektirir. 2.2 veya daha eski sürümlerde `No module named app.users` hatasıyla başarısız olur. Önce güncelleyin: Docker Compose ile `drumsergio/cashpilot` ve `drumsergio/cashpilot-worker` etiketlerini `2.3` veya daha yenisine değiştirin (`2.2` ya da `2.2.9` gibi bir sabitleme o sürümde kalır), ardından `docker compose up -d` çalıştırın ([CashPilot'u güncelleme](getting-started.md#updating-cashpilot)). Unraid'de konteyneri güncelleyin.

1. Hesapları listeleyin. Bu, unuttuğunuz bir kullanıcı adını da gösterir. Kullanıcı adları büyük/küçük harfe duyarlıdır.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Hesap için rastgele yeni bir parola belirleyin. `alice` yerine 1. adımdaki kullanıcı adını yazın.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Tam olarak bir sahip varsa kullanıcı adını yazmayabilirsiniz; komut o sahibi sıfırlar. Kullanıcı adı `-` ile başlıyorsa önüne `--` koyun: `reset-password -- -alice`.

    Komut yeni parolayı bir kez yazdırır.

3. Hesaba başka birinin erişmiş olma ihtimali varsa UI konteynerini şimdi yeniden başlatın (`docker restart cashpilot-ui`). O kullanıcı olarak hâlâ oturumu açık olan tarayıcıların oturumu yalnızca yeniden başlatmadan sonra kapanır. Yalnızca parolayı unuttuysanız yeniden başlatma isteğe bağlıdır.
4. Yeni parolayla oturum açın, ardından onu avatar menüsünden (sağ üst) **Change password** (Parolayı değiştir) ile değiştirin.

Konteyner adı CashPilot'u nasıl kurduğunuza bağlıdır:

| Kurulum | UI konteyneri |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | üretilmiş bir ad; `docker ps` onu gösterir |

Portainer, Unraid ve CasaOS'ta da bir konteyner için konsol düğmesi vardır. Komut terminal girdisi gerektirmez, bu yüzden orada da çalışır.

Bir kullanıcı adını değiştirmek için:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

Yeni ad kayıt kuralına uyar: 3 ila 32 harf, rakam, `_` veya `-`. Görmek için oturumu kapatıp yeniden açın.

**Bir güvenlik ihlali şüphesinden sonra**, örneğin `/data/.secret_key` içeren bir yedeği kaybettiğinizde, yalnızca parola sıfırlamak yeterli değildir. O anahtara sahip olan herkes geçerli bir oturum çerezi imzalayabilir ve sıfırlama bunu durdurmaz. Anahtarı değiştirin, ardından UI konteynerini yeniden başlatın. `&&`, konteyneri yalnızca yeni anahtar yerindeyse yeniden başlatır; komut bir hata yazdırırsa önce onu düzeltin:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Yeniden başlatmadan sonra her tarayıcının oturumu kapanır ve herkes parolasıyla yeniden oturum açar. Kaydedilmiş kimlik bilgileri etkilenmez. `CASHPILOT_SECRET_KEY` değerini kendiniz ayarladıysanız komut reddeder: bunun yerine o değişkene yeni bir rastgele değer koyun ve konteyneri yeniden oluşturun. İmajdan çalıştırılan bir `docker run` bu değişkeni görmez ve reddedemez, bu yüzden UI konteynerinde `docker exec` kullanın.

Yeni bir anahtar sahte çerezleri sona erdirir, ama saldırganın içerideyken yaptıklarını geri almaz. İki adım daha:

1. `docker exec cashpilot-ui python -m app.users list` çalıştırın. Tanımadığınız hesapları panodan silin.
2. Kaybolan kopya `/data` dizininin tamamını içeriyorsa sağlayıcı hesaplarınızın parolalarını değiştirin. `.fernet_key` ve `cashpilot.db` birlikte, kaydedilmiş her kimlik bilgisinin şifresini çözer.

Daha sonra anahtar değiştirmeden önce alınmış bir yedeği geri yüklerseniz onun `.secret_key` dosyasını dışarıda bırakın ([Yedekleme ve geri yükleme](backup-restore.md#restore)) ya da anahtarı yeniden değiştirip yeniden başlatın. Aksi halde eski anahtar geri gelir. Geri yüklenen veritabanı içerdiği hesapları ve parolaları da geri getirir, bu yüzden hesap kontrolünü ve gereken parola sıfırlamalarını tekrarlayın.

**UI konteyneri başlamıyorsa**, komutu aynı imajdan, aynı verilere karşı çalıştırın. Önce UI'nin `/data` dizinini tutan ana makine klasörünü bulun. Bu, durdurulmuş bir konteyner için ve bind mount kadar adlandırılmış bir birim için de çalışır (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Ardından o klasörü bağlayın ve çalıştırdığınız imaj etiketini kullanın:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Listenin hesaplarınızı gösterdiğini kontrol edin, ardından aynı satırı `list` yerine `reset-password alice` ile çalıştırın.

Veritabanı olmayan bir yol "no database" hatası verir ve komut orada hiçbir şey oluşturmaz veya değiştirmez. Docker yine de o adla boş bir klasör veya birim bırakabilir; onu kaldırın.

Veri birimini **silmeyin**: bu, `/data/.fernet_key` dosyasını ve onunla birlikte kaydedilmiş her kimlik bilgisini siler. `users` tablosundan satır da **silmeyin**.

**CashPilot'u tamamen nasıl kaldırırım?**

`docker compose down -v` yalnızca CashPilot'un kendi konteynerlerini kaldırır. Dağıttığı hizmetler çalışmaya devam eder; onların verileri, bariyerli ağ ve bir güvenlik duvarı tablosu yerinde kalır. [CashPilot'u tamamen kaldırma](uninstall.md) sayfası bunların hepsini kaldırır, nelerin kalıcı olarak kaybolduğunu söyler ve geride hiçbir şey kalmadığını nasıl kontrol edeceğinizi gösterir.

**Güvenlik ne durumda?**

CashPilot'un dağıttığı her hizmet, tüm Linux yetkileri (capabilities) kaldırılmış olarak (birkaç hizmet yalnızca bildirdiklerini geri ekler) ve `--security-opt no-new-privileges` ayarlanmış olarak kendi konteynerinde çalışır; böylece içerideki bir süreç ayrıcalık kazanamaz. Konteynerler, bir hizmetin bildirdiği birimlerin ötesinde ana makinenizin dosya sistemini göremez. Yeni bir kurulumda worker ayrıca onları LAN'ınızdan, ana makineden, tailnet'inizden ve bulut meta verilerinden bariyerle ayırır; böylece internete ulaşırlar ama yerel hiçbir şeye ulaşmazlar ([Ağ yalıtımı](isolation.md)). Podman'da bariyer kullanılamaz: kazanç uygulamaları LAN'ınıza ulaşabilen Podman'ın varsayılan ağında çalışır ve **Fleet** (Filo) sayfası bunu belirtir (seçenekleri [Ağ yalıtımı](isolation.md) listeler). 1.70'ten önceki bir sürümden yükseltilmiş bir kurulum, **Fleet** (Filo) sayfasında **Turn on isolation** (Yalıtımı aç) düğmesine tıklayana kadar kazanç uygulamalarını LAN'ınıza ulaşabilen Docker'ın varsayılan köprüsünde tutar. 2.0.7'den beri Mysterium da bariyerin arkasında çalışır; 2.0.6 ve öncesiyle dağıtılmış bir düğüm, siz onu yeniden dağıtana kadar ana makinenin ağında kalır ([Mysterium düğümünüzü bariyerin arkasına taşıma](mysterium-fence.md)). [Ev ağınızı koruma](home-network-security.md) sayfası bunun yerine kendi köprünüzü güvenlik duvarıyla korumayı anlatır. Hizmet kimlik bilgileri diskte Fernet simetrik şifrelemesiyle şifrelenir. Arayüzün Docker erişimi yoktur. Birlikte gelen compose dosyalarıyla worker'a ham Docker soketi hiçbir zaman verilmez: Docker'a `cashpilot-socket-proxy` üzerinden ulaşır. Proxy ayrıcalıklı konteynerleri ve `/` ya da soketin bağlanmasını reddeder (bunlardan birini ya da soketin üstündeki bir klasörü `CASHPILOT_PROXY_BIND_MOUNTS` veya `CASHPILOT_COMPOSE_DIR` içine koymadığınız sürece: proxy bunları verildiği gibi kabul eder) ve worker'ı sahip etiketini taşıyan konteynerler, birimler ve ağlarla sınırlar ([varsayılan güvenlik ayarları](security-defaults.md)). Unraid şablonları ve TrueNAS uygulaması ise ham soketi hâlâ worker'a bağlar; bu da ana makinede root demektir ([uygulama mağazaları](app-stores.md)).

Yine de hiçbir kurulum kusursuz değildir. Dış trafiği ağınız üzerinden yönlendiren üçüncü taraf yazılımları çalıştırmaya devam ediyorsunuz. Docker yalıtımı, bu hizmetleri doğrudan ana makinenizde çalıştırmaya kıyasla saldırı yüzeyini önemli ölçüde azaltır, ancak tüm riski ortadan kaldırmaz. CashPilot'u ayrı bir makinede veya VLAN'da çalıştırmanızı, Docker'ı ve ana makinenizin işletim sistemini güncel tutmanızı ve herhangi bir hizmeti dağıtmadan önce açık kaynak kodunu incelemenizi öneririz.

**Bir hizmet konteyneri çökerse ne olur?**

CashPilot konteyner sağlığını sürekli izler. Bir hizmet konteyneri beklenmedik şekilde çıkarsa otomatik olarak yeniden başlatılır. Pano, çalışan her hizmet için çalışma süresini ve sağlık durumunu gösterir.

**Mysterium düğümüm yeniden dağıtımdan sonra başlamıyor. Neden?**

En yaygın neden, UDP aralığındaki bir portu ana makinedeki başka bir programın zaten tutmasıdır. Docker aralıktaki her portu ayırmak zorundadır, bu yüzden tek bir meşgul port başlatmayı durdurur. [UDP port aralığını seçme](mysterium-fence.md#choosing-the-udp-port-range) bölümü boş kalan bir aralığın nasıl seçileceğini açıklar.

**Proxy kopyam çalışıyor ama hiçbir şey kazanmıyor. Neden?**

Proxy o kazanç uygulamasının sunucularına bağlanmayı reddediyor ya da yalnızca 80 ve 443 portlarına izin veriyor olabilir. CashPilot'un **Test** (Test et) kontrolü yalnızca proxy'nin internete ulaştığını kontrol eder. [Bir kazanç uygulamasının sunucularını proxy üzerinden yoklayın](proxies.md#probe-an-earners-servers-through-the-proxy) bölümü, kazanç uygulamasının kendi ana makinesini ve portunu nasıl kontrol edeceğinizi gösterir.

**Hangi hizmetler ağırdır ve nerede çalışmalıdır?**

En çok kaynağı depolama düğümleri, relay'ler ve VPN çıkışları ile GPU işleri kullanır. [Küçük bir makine için bütçe yapma](fleet.md#budgeting-a-small-box) bölümü bunları listeler ve karar vermeden önce her konteyneri nasıl ölçeceğinizi gösterir.

<a id="worker-lost-docker"></a>

### Worker bir Docker güncellemesinden sonra Docker'ı kaybetti { #the-worker-lost-docker-after-a-docker-update }

**Ne görürsünüz.** Worker **Fleet** (Filo) sayfasında çevrimiçi kalır, ancak CashPilot onun konteynerlerini başlatamaz, durduramaz veya güncelleyemez. **Fleet** (Filo) sayfası worker'ın yanında **Docker unreachable** (Docker'a ulaşılamıyor) gösterir. 10 dakika sonra worker'ın sağlık kontrolü başarısız olur (`docker ps` worker'ı `unhealthy` olarak gösterir). 30 dakika sonra zil simgesi ve bildirimleriniz worker'ın Docker'a ulaşamadığını söyler. `docker logs cashpilot-socket-proxy` `upstream Docker socket unreachable` gösterir ve güncel bir compose dosyasıyla `docker ps` proxy'yi yaklaşık 3 dakika içinde `unhealthy` olarak gösterir. Kazanç uygulamalarınız çalışmaya devam eder.

**Neden.** Birlikte gelen compose dosyaları `/var/run/docker.sock` soket dosyasını `cashpilot-socket-proxy` içine bağlar. Bir dosya bağlaması o tek dosyayı tutar. Bir Docker güncellemesi (örneğin yeni bir `docker-ce` kuran `unattended-upgrades`) Docker'ı yeniden başlatır ve Docker aynı yolda yeni bir soket dosyası oluşturur. Docker'ın live-restore özelliği açıkken proxy bu yeniden başlatma boyunca çalışmaya devam eder ve eski dosyayı tutar. Eski dosyada hiçbir şey yanıt vermez.

**Hızlı çözüm.** O makinede proxy'yi yeniden başlatın:

```bash
docker restart cashpilot-socket-proxy
```

Yeniden başlatma yeni soketi bağlar ve worker bir sonraki yaşam sinyalinde Docker'ı yeniden bulur. Worker'ı yeniden başlatmanız gerekmez. Unraid ve TrueNAS'ta soketi worker'ın kendisi tutar, bu yüzden worker'ı yeniden başlatın.

**Kalıcı çözüm.** Soket dosyasını değil, soketin klasörünü bağlayın. Bir klasör bağlaması, değiştirilen bir soketi hemen gösterir. Compose dosyanızın `cashpilot-socket-proxy` hizmetinde `- /var/run/docker.sock:/var/run/docker.sock:ro` satırını aşağıdaki bağlamayla değiştirin ve `environment` bölümüne `SOCKGUARD_UPSTREAM_SOCKET` satırını ekleyin:

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

Ardından `docker compose up -d` çalıştırın. Aynı değişiklik `docker-compose.worker.yml` ve `docker-compose.fleet.yml` içinde de çalışır. Compose bu dosyaları yalnızca adlarını verdiğinizde okur, bu yüzden `COMPOSE_FILE` dosyayı zaten belirtmiyorsa `docker compose -f docker-compose.worker.yml up -d` veya `docker compose -f docker-compose.fleet.yml up -d` çalıştırın.

- `recursive: disabled` gereklidir. `/var/run` başka bağlamaları da barındırır, örneğin `/run/docker/netns` altındaki Docker ağ ad alanlarını ve `/run/user/...` dizinini. Özyinelemeli bir bağlama bunların hepsini proxy'ye getirir. Özyinelemesiz bir bağlama yalnızca klasörün kendisini gösterir.
- `SOCKGUARD_UPSTREAM_SOCKET` proxy'yi yeni yola yönlendirir. Politika bloğu ve parmak izi olduğu gibi kalır, çünkü ortam değişkeni politikadaki `upstream.socket` değerini geçersiz kılar. Değişken olmadan proxy başlamaz (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` dosya bağlamasını koruyabilir. Her `docker compose up` işleminde yeniden başlar, bu yüzden her zaman güncel soketi alır. Ona da aynı klasör bağlamasını verirseniz `environment` bölümüne `DOCKER_HOST=unix:///host-run/docker.sock` ekleyin. Worker 2.8.4 ve sonrası bu değişkeni okur. Onu asla proxy'nin soketine yönlendirmeyin: taşıyıcının ana makinenin kendi soketine ihtiyacı vardır.
- Klasör bağlaması proxy'ye yalnızca Docker'ınkini değil, `/var/run` içindeki her soketi verir. Tipik bir sunucuda buna systemd'nin kendi soketi, D-Bus ve Tailscale veya snapd gibi araçların soketleri dahildir. `read_only` bir programın bir sokete bağlanmasını engellemez ve proxy root olarak çalışır. Docker soketine erişim zaten ana makinede root yetkisi verir, bu yüzden ele geçirilmiş bir proxy zaten sahip olmadığı pek bir şey kazanmaz. Proxy'nin yalnızca Docker soketini tutmasını istiyorsanız dosya bağlamasını koruyun ve bir Docker güncellemesinden sonra proxy'yi yeniden başlatın: yukarıdaki uyarı size ne zaman gerektiğini söyler.
- Docker Compose 2.30.0 veya daha yenisi gerekir. Eski sürümler dosyanın tamamını `Additional property recursive is not allowed` ile reddeder. Kontrol etmek için `docker compose version` çalıştırın. Debian 13, Compose 2.26.1 paketler, bu yüzden Debian'da Compose'u Docker'ın kendi deposundan kurun. Uygulama içi güncelleme kendi Compose 2.33 sürümünü kullanır, bu yüzden değiştirilmiş dosyayı okur.
- Yalnızca Linux'ta çalışır. macOS ve Windows'taki Docker Desktop, sanal makinesine yalnızca `/var/run/docker.sock` dosyasını eşler. Orada `/var/run`, Mac'inizde veya PC'nizde içinde Docker soketi olmayan bir klasördür.
- Rootless Docker'da soket ayrı bir bağlama olan `/run/user/<your uid>` içindedir. `source` olarak o klasörü kullanın.
- Podman'da dosya bağlamasını koruyun. Klasör bağlamasını orada test etmedik.

Birlikte gelen dosyalar dosya bağlamasını korur, çünkü klasör bağlaması Compose 2.30 ve Linux gerektirir; CashPilot ise eski Compose sürümlerini ve Docker Desktop'ı da destekler. İndirdiğiniz daha yeni bir compose dosyası sizin değişikliğinizi içermez, bu yüzden dosyayı değiştirdikten sonra değişikliği yeniden yapın.
