---
source_hash: 1a93abea95d7
---
# CashPilot'un karşılaştırması { #how-cashpilot-compares }

Bu sayfa CashPilot'u, Docker'da birden çok pasif gelir uygulaması çalıştıran diğer açık projelerle karşılaştırır. Her projeyi 2026-11-04 tarihinde kontrol ettik. Başka bir projeyle ilgili her hücre, kendiniz kontrol edebilmeniz için bilginin geldiği dosyaya sabit bir commit'te bağlantı verir. Bir hücre yanlış veya güncel değilse lütfen [bir issue açın](https://github.com/GeiserX/CashPilot/issues).

## Karşılaştırılan projeler { #projects-compared }

| Proje | Neyi kontrol ettik | 2026-11-04 tarihindeki yıldızlar | Lisans |
|---|---|---|---|
| [money4band][m4b-tree] | 5.0.0 sürümü, etiket commit'i `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `65e900d` üzerindeki `main` (2026-10-20), ayrıca README'nin 3.0.0-beta.9 ikili dosyası hakkındaki iddiaları | 238 | Tescilli, [kendi lisansı v1.4][igm-license] |
| [InternetIncome][ii-tree] | `db9338a` üzerindeki `main` (2026-11-03) | 257 | LICENSE dosyası yok. [README][ii-license] orijinalin kopyalanmasına izin verir ve değiştirilmiş kopyaların dağıtılmasını yasaklar |
| [CashFactory][cf-tree] | `0ff4bd0` üzerindeki `main` (2025-04-08) | 410 | [LICENSE][cf-license-file] dosyası GPL-3.0'dır, ancak [README][cf-license] değiştirilmiş kopyaların dağıtılmasını yasaklar |
| [home-assistant-passive-income][ha-tree] (HA eklentileri) | 2.0.6 sürümü, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | v1.64.0 sürümü, `c7a12bd` üzerindeki `main` (2026-11-04) | 77 | GPL-3.0 |

money4band'in iki kod hattı vardır. Varsayılan dalı `main` (`3bfafb1`) hâlâ 4.x kodunu tutar ve orada son kod değişikliği 2026-03-03 tarihinde yapıldı. 5.0.0 sürümü ayrı bir geçmişten derlenir. 5.0.0'ı karşılaştırıyoruz, çünkü en son sürümünün yayımladığı odur.

IGM'nin web arayüzü, filo yönetimi ve kurulum ikili dosyası kapalı kaynaktır ve deposunda yer almaz. Bir hücre bunlara dayandığında "README iddia ediyor" der ve README satırına bağlantı verir. IGM sütunundaki diğer her şey depodaki kabuk betiklerinden ve compose dosyalarından gelir.

Dışarıda bırakılanlar: [earning-machine](https://github.com/jf-m/earning-machine) ve [passiveMachine](https://github.com/Xpl0itU/passiveMachine) projelerinde 2024'ten beri hiç commit yok. Bir GitHub araması, birden fazla uygulama çalıştıran ve bakımı süren başka bir şey bulamadı; yalnızca tek uygulamalı imajlar buldu.

## Kısa sürüm { #short-version }

- **InternetIncome, money4band, IGM ve v1.69.0'dan beri CashPilot, proxy'ler üzerinden birçok IP'de kazanç elde edebilir.** İlk üçü her uygulamayı proxy başına bir kez çalıştırır ve proxy'ler InternetIncome'un ana özelliğidir. CashPilot, bir worker'da zaten dağıtılmış bir hizmetin ek kopyalarını, her biri bir SOCKS5, HTTP CONNECT veya Tailscale exit-node proxy'si üzerinden olacak şekilde çalıştırır ([proxy kopyaları](proxies.md)).
- **InternetIncome (23), CashPilot'un worker'ından (<!-- n:docker -->21<!-- /n -->) daha fazla uygulama başlatır; IGM 20 uygulama başlatır.** CashPilot toplamda daha fazla hizmeti izler (<!-- n:live -->50<!-- /n -->), çünkü çalıştırmadığı tarayıcı eklentisi, masaüstü ve GPU hizmetlerini de takip eder. v1.64.0'dan beri adını verdiğiniz herhangi bir imajı [özel hizmet](custom-services.md) olarak da çalıştırabilir.
- **money4band ve IGM günlük ödülleri sizin için talep eder ve uygulama imajlarını Watchtower ile güncel tutar.** CashPilot bunların hiçbirini yapmaz. Bir imajı yalnızca dağıttığınızda veya yeniden dağıttığınızda yeniden çeker.
- **Burada sağlayıcı hesaplarınızdan bakiye okuyan ve geçmiş tutan tek proje CashPilot'tur.** money4band 5.0.0, hesaplarınızdan değil kendi kataloğundan tahminler gösterir. Diğerleri her sağlayıcının panosuna bağlantı verir.
- **Burada birçok sunucu için tek bir arayüzü olan tek açık kaynaklı proje CashPilot'tur.** IGM'nin README'si filo yönetimi iddia eder, ancak o kod kapalı ikili dosyasındadır.
- **v1.70.0'dan beri burada kazanç uygulaması konteynerlerini varsayılan olarak LAN'ınızdan uzak tutan tek proje CashPilot'tur; bazı sınırlarla.** Bu özellik yeni kurulumlarda ve Docker'ın varsayılan köprüsünde hiçbir kazanç uygulaması olmayan yükseltilmiş kurulumlarda açıktır. Kazanç uygulamaları zaten o köprüde bulunan yükseltilmiş bir kurulum, siz yalıtımı açana kadar onları orada tutar ve `CASHPILOT_CONTAINER_NETWORK` içinde adını verdiğiniz bir ağ CashPilot'tan hiçbir bariyer almaz ([yalıtım](isolation.md#modes)). 2.0.7'den beri Mysterium da bariyerin arkasında çalışır; 2.0.6 ve öncesiyle dağıtılmış bir düğüm, siz onu yeniden dağıtana kadar bariyersiz olarak ana makinenin ağında kalır ([bariyerin arkasında Mysterium](mysterium-fence.md)).

## Yan yana { #side-by-side }

CashPilot sütunu v1.64.0 sürümünü anlatır; proxy, Docker soketi ve LAN yalıtımı satırları hariç, bunlar v1.71.1 sürümünü (`0170dee`, 2026-11-06) anlatır; konteyner ayarları ve LAN yalıtımı satırlarındaki Mysterium ağı ise 2.0.6'dan sonraki sürümü (`01e7310`) anlatır. Dışa giden çağrılar satırı, [güncel zincir üstü rehberindeki](onchain.md) gezgin çağrılarını içerir. Diğer sütunlar yukarıdaki tablodaki commit'leri anlatır.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA eklentileri |
|---|---|---|---|---|---|---|
| Başlatabildiği uygulamalar ([nasıl saydığımıza](#how-we-counted) bakın) | <!-- n:docker -->21<!-- /n --> tanesini worker çalıştırır, ayrıca [özel imajlar](custom-services.md); toplamda <!-- n:live -->50<!-- /n --> izlenen | 15 ([katalog][m4b-catalog]). README 35 der, bu sayı topluluk uygulamalarını ve bırakılmış uygulamaları [içerir][m4b-readme-35] | 20 ([apps.json][igm-apps]) | 23 ([betik][ii-script]) | 11 ([compose dosyası][cf-compose]) | 10 ([eklenti klasörleri][ha-tree]) |
| Nasıl kurulur | Docker Compose: bir arayüz ve her sunucuda bir worker; worker kazanç uygulamalarını Docker API üzerinden başlatır ([filo](fleet.md)) | Bir compose dosyası yazan Python CLI veya önceden derlenmiş bir ikili dosya ([sürüm][m4b-tree]) | `curl \| sh` kurucusu ([README][igm-install]); kapalı bir ikili dosya indirir ve onu yalnızca aynı sürümdeki bir SHA256SUMS dosyasına karşı kontrol eder ([kurucu][igm-installer-sums]) | `sudo docker run` çağıran 1.608 satırlık tek bir bash betiği ([betik][ii-script]) | Statik bir compose dosyası ve sudo ile çalıştırılan `setup.sh` ([kurulum][cf-setup]) | Bir Home Assistant eklenti deposu; Home Assistant OS veya Supervised gerektirir |
| Birçok sunucu, tek görünüm | Evet ([filo](fleet.md)) | Hayır, cihaz başına bir yığın | README evet der, kapalı ikili dosyada ([README][igm-features]) | Hayır | Hayır | Hayır |
| Birçok proxy veya IP | Evet, v1.69.0'dan beri: dağıtılmış bir hizmetin ek kopyaları, her biri bir SOCKS5, HTTP CONNECT veya Tailscale exit-node proxy'si üzerinden. SOCKS5 ve HTTP CONNECT yalnızca TCP taşır (tünel dışarıya yalnızca proxy'nin portuna giden TCP'yi bırakır, bu yüzden SOCKS5 UDP aktarımları düşürülür); bir Tailscale exit node UDP de taşır. Kazanç uygulaması, güvenlik duvarı dışarıya yalnızca loopback'i, tüneli ve tünelin proxy'ye kendi bağlantısını (adresine ve portuna TCP ya da tailscaled'in işaretli paketleri) bırakan bir tünel konteynerinin ağ ad alanını paylaşır; bu yüzden ölü bir proxy sızdırmak yerine onu durdurur ([proxy kopyaları](proxies.md#how-it-works), [kod][cp-proxy-deploy], [tünel güvenlik duvarı][cp-tunnel-fw]). Ana makine ağı, yayımlanmış portlar, birimler, cihazlar ya da `NET_ADMIN`, `NET_RAW` veya `SYS_ADMIN` gerektiren hizmetler bir proxy üzerinden çalışamaz ([proxy kopyaları](proxies.md#what-cannot-run-through-a-proxy)) | Evet ([README][m4b-features], [kod][m4b-multiproxy]) | Evet ([README][igm-features], [compose][igm-proxy]) | Evet, ana özelliği ([README][ii-readme-top]) | Hayır | Hayır |
| Kazançlar | <!-- n:collectors -->20<!-- /n --> toplayıcı sağlayıcı hesaplarından bakiye okur ve geçmiş tutar. Bazıları tarayıcınızdan kopyalanmış bir çerez veya belirteç gerektirir ve bunların bazılarının süresi dolar (her hizmetin rehberine bakın) | Hesap verisinden değil, katalog aralıklarından tahminler ([kod][m4b-earnings]) | Betiklerde bulunamadı | Yok | Yok | Yok |
| Ödemeler | Bir bakiye düştüğünde bir ödeme önerir ve siz onayladığınızda kaydeder ([şema][cp-payouts]) | Yok | Yok | Yok | Yok | Yok |
| Günlük ödül talebi | Hayır | Evet, yan konteynerler ([README][m4b-features]) | Evet ([README][igm-features], [compose][igm-sidecars]) | Hayır | Hayır | Hayır |
| Diskteki kimlik bilgileri | Arayüzün veritabanında şifrelenmiş (Fernet); anahtar dosyası aynı veri biriminde durur ([kod][cp-fernet]). Kazanç uygulaması kimlik bilgileri her worker'a konteyner ortam değişkenleri olarak ulaşır, bu yüzden o worker'ın Docker yapılandırmasında düz metindir (`docker inspect`) | Şifrelenmiş (Fernet); anahtar dosyası veri dizininde durur ([kod][m4b-crypto]) | Şifrelenmiş (openssl ile AES-256); anahtar dosyası kasanın yanında durur ([kod][igm-encryptor]) | `properties.conf` içinde düz metin; bazı parolalar `docker run` argümanları olarak geçirilir ([betik][ii-password-arg]) | `.env` içinde düz metin ([dosya][cf-env]) | Supervisor tarafından `/data/options.json` içinde saklanan eklenti seçenekleri ([HA belgeleri][ha-options]) |
| Kazanç uygulaması konteyner ayarları | Tüm yetkiler kaldırılır, sonra katalog bir hizmetin ihtiyaç duyduklarını geri ekler; `no-new-privileges`; bir pids sınırı; ayrıcalıklı mod reddedilir ([kod][cp-hardening], [kod][cp-privileged]). Mysterium, bariyerli köprüde kendi ağ ad alanında `NET_ADMIN`, `SETUID` ve `SETGID` ile, digest ile sabitlenmiş bir imajla çalışır ([katalog][cp-myst]) | Ayrıcalıklı olmayan her hizmette `no-new-privileges` ([kod][m4b-nnp]); proxy konteyneri `NET_ADMIN` ile ayrıcalıklıdır ([şablon][m4b-tun]) | Uygulama hizmetlerinde hiçbir şey ayarlanmamış; Mysterium `NET_ADMIN` alır ([compose][igm-hosting-myst]); proxy konteyneri `no-new-privileges` ve bir pids sınırıyla `NET_ADMIN` alır ([compose][igm-proxy]) | Ebesucher `seccomp=unconfined` ile çalışır ([betik][ii-seccomp]); proxy konteynerleri ve Mysterium `NET_ADMIN` alır | Hiçbir şey ayarlanmamış | Hiçbir eklenti ayrıcalıklı mod, ana makine ağı veya Docker API erişimi istemez ([örnek yapılandırma][ha-config]) |
| Docker soketinin bağlandığı yer | v1.71.0'dan beri salt okunur bir soket proxy'si (sockguard 2.4.5, digest ile sabitlenmiş). Worker, ayrıcalıklı konteynerleri, `/` veya soketin bağlanmasını ve katalogdakilerin dışındaki yetkileri veya cihazları reddeden filtrelenmiş bir kopya alır ([compose][cp-sock], [ayrıntılar](security-defaults.md)); hiçbir zaman bir kazanç uygulaması değil ([kod][cp-mounts]) | Watchtower ([şablon][m4b-watchtower]) | `no-new-privileges` ile salt okunur olan Watchtower ([compose][igm-watchtower]) | Beş yeniden başlatma yardımcı konteyneri ([betik][ii-sock-helper]) ve Watchtower ([betik][ii-watchtower]) | Tüm arayüzlerde 8000, 9000 ve 9443 portlarında yayımlanan Portainer ([compose][cf-portainer]) ve iki Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Yok |
| İmaj etiketleri | <!-- n:docker -->21<!-- /n --> kazanç uygulaması imajından 9'u bir sürüme veya digest'e sabitlenmiştir; geri kalanı serbesttir | 15 uygulama imajının tümü `:latest` kullanır ([örnek][m4b-image]); proxy konteyneri v2.6.0'a, Watchtower `:1` etiketine sabitlenmiş | Etiket yok, bu yüzden Docker `latest` kullanır ([compose][igm-hosting]); etiket yalnızca bazı ARM derlemeleri için ayarlanır | Çoğunlukla `:latest` ([örnek][ii-seccomp]); EarnApp `:lite`, Honeygain amd64'te proxy üzerinden çalışırken 0.6.6'ya sabitlenmiş ([betik][ii-honeygain]), ARM'de Traffmonetizer için mimariye özel etiketler; Watchtower `:nightly` | EarnApp `:lite` dışında `:latest` veya etiket yok ([compose][cf-compose]) | Eklenti başına bir sürüm, günlük bir CI işiyle yükseltilir ([iş akışı][ha-bump], [örnek][ha-dockerfile]) |
| Uygulama imajı güncellemeleri | Her dağıtımda veya yeniden dağıtımda yeniden çekilir; otomatik güncelleyici yok | Watchtower ([şablon][m4b-watchtower]) | 4 saatte bir Watchtower ([compose][igm-watchtower]) | Açarsanız günde bir kez Watchtower ([betik][ii-watchtower]) | Her biri tek bir uygulamayla sınırlı iki Watchtower, PacketStream ([compose][cf-watchtower-ps]) ve EarnFM ([compose][cf-watchtower-efm]); diğer 9 uygulama güncellenmez | Home Assistant'ın eklenti güncellemeleri |
| LAN yalıtımı | v1.70.0'dan beri yeni kurulumlarda ve Docker'ın varsayılan köprüsünde hiçbir kazanç uygulaması olmayan yükseltilmiş kurulumlarda varsayılan olarak açık: worker kazanç uygulamalarını kendi köprüsüne koyar ve özel aralıkları, tailnet aralığını, bulut meta verilerini, ana makinenin bağlı alt ağlarını, ana makinenin kendisini ve genel IP algılama açıkken evin genel IP'sini düşüren bir güvenlik duvarı tablosu yazar ([yalıtım](isolation.md#lan-isolation-by-default), [kod][cp-fence]). Kazanç uygulamaları zaten varsayılan köprüde bulunan yükseltilmiş bir kurulum, siz **Turn on isolation** (Yalıtımı aç) düğmesine basana kadar orada kalır; `CASHPILOT_ISOLATION=off` yalıtımı kapatır; `CASHPILOT_CONTAINER_NETWORK` ayarlıyken CashPilot o ağ için bariyer yazmaz ve güvenlik duvarı kuralları size kalır ([yalıtım](isolation.md#modes), [kod][cp-fence-mode]). 2.0.7'den beri Mysterium da bariyerlidir; 2.0.6 ve öncesiyle dağıtılmış bir düğüm, siz onu yeniden dağıtana kadar ana makinenin ağında kalır ([bariyerin arkasında Mysterium](mysterium-fence.md)). Bir kontrol, kazanç uygulamalarının nelere ulaşabildiğini gösterir ([kontrol](isolation-check.md)) | LAN'ı engellemeyen kendi köprü alt ağı ([yapılandırma][m4b-subnet]) | Birleştirilmiş bir çözüm yok | Bulunamadı | Bulunamadı | Bulunamadı |
| ARM | arm64 arayüz ve worker; bir dağıtımdan önce her hizmetin platformlarını kontrol eder ([ARM](arm.md)) | arm64 ve armv7 ikili dosyaları ([sürüm][m4b-release]) | README amd64 ve arm64'ü, sınırlı olarak arm32'yi iddia eder ve QEMU'yu kurar ([README][igm-arch]) | Yalnızca amd64 için olan imajlarda binfmt emülasyonu gerektirir ([README][ii-arm]) | README, Raspberry Pi'de çalışmadığını söyler ([README][cf-raspberry]) | Eklentiye göre değişir; ProxyRack yalnızca amd64'tür ([yapılandırma][ha-proxyrack]) |
| Arayüz | Web arayüzü, ayrıca Desktop, Android, MCP ve Home Assistant istemcileri | CLI, menüler ve varsayılan olarak 127.0.0.1'e bağlı yerel bir web panosu ([kod][m4b-bind]) | CLI, menüler ve README'ye göre LAN'dan ulaşılabilen 4747 portunda bir web arayüzü ([README][igm-webui]) | Yok, bir betik | 80 portunda bir yer imleri sayfası ve Portainer ([README][cf-ui]) | Home Assistant eklenti paneli |
| Varsayılan daldaki commit'ler, 2026-08-06 ile 2026-11-04 arası | 286 | 6, hepsi belgeler (5.0.0 ayrı bir geçmişte) | 6 | 31 | 0 | 23 |
| En son sürüm | v1.64.0, 2026-11-04 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Sürümlenmiş yayın yok | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Uygulamalar dışındaki dışa giden çağrılar | Günde bir kez GitHub sürümleri (`CASHPILOT_UPDATE_CHECK=off` bunu durdurur, [kod][cp-update]); her worker'dan saatte bir kez, kendi genel IP'si için `api.ipify.org`, `ifconfig.me` veya `icanhazip.com` (`CASHPILOT_EGRESS_DETECT=off` bunu durdurur, [kod][cp-egress]); döviz kurları için CoinGecko ve Frankfurter ([kod][cp-rates]); [zincir üstü bakiyeler](onchain.md) için mempool.space, api.kaspa.org ve herkese açık Ethereum, Polygon ve Solana RPC düğümleri; toplayıcılar için her sağlayıcı. Tarayıcı Google Fonts'u ([şablon][cp-cdn]) ve jsDelivr'den Chart.js'yi ([şablon][cp-chartjs]) yükler | Güncelleme kontrolü için GitHub sürümleri ([kod][m4b-updater]); imaj etiketlerini kontrol etmek için Docker Hub ve ghcr.io ([kod][m4b-registry]); IP kontrolünü çalıştırdığınızda genel IP'niz için `api.ipify.org`, `ifconfig.me` veya `icanhazip.com` ve IP puanları için düz HTTP üzerinden `ip-api.com` ([kod][m4b-ipscore]) | GitHub sürümleri ([kod][igm-version]); genel IP'niz için `api.ipify.org`, `ifconfig.me` veya `icanhazip.com` ([kod][igm-ifconfig]); IP puanları için düz HTTP üzerinden `ip-api.com` ([kod][igm-ipscore]). Kapalı ikili dosya kontrol edilmedi | Bulunamadı | Bulunamadı | Bulunamadı |

Okuduğumuz kodda projelerin hiçbiri kullanım telemetrisi göndermiyor. IGM'nin kapalı ikili dosyası okunamadı.

Buradaki her proje uygulama kimlik bilgilerini konteynerlere ortam değişkenleri olarak geçirir; InternetIncome bazılarını komut argümanları olarak da geçirir. Bu yüzden uygulamaları çalıştıran ana makinede bunlar Docker'ın konteyner yapılandırmasında (`docker inspect` içindeki `Env` ve `Args`) düz metindir ve Docker erişimi olan herkes tarafından okunabilir. "Diskteki kimlik bilgileri" satırı yalnızca saklanan kopyayı anlatır.

## Nasıl saydık { #how-we-counted }

- **CashPilot.** Katalogda durumu active veya beta olan ve bir Docker imajı bulunan hizmetler; GPU işlem gücü ve madencilik havuzları sayılmaz. Bu sayfadaki sayı `scripts/generate_readme_tables.py` betiğinden gelir ve sayı kayarsa CI başarısız olur.
- **money4band 5.0.0.** `config/catalog/supported/` içinde uygulama başına bir JSON dosyası: 15. README'deki "35 apps" varsayılan olarak kapalı olan topluluk kataloğunu ([yapılandırma][m4b-community]), Docker imajı olmayan uygulamaları ve bırakılmış uygulamaları da sayar.
- **IGM.** `apps.json` içindeki girdiler: 20, hepsi etkin. Proxy konteyneri, Watchtower ve talep yan konteynerleri sayılmaz.
- **InternetIncome.** `internetIncome.sh` içindeki proxy ve Watchtower blokları dışındaki her `# Starting ... container` yorum bloğu: 24. Ebesucher'in Chrome ve Firefox blokları tek bir uygulamadır; aynı EarnFM hesabını kullanan EarnFM ve EarnFM Fleetshare de öyle. Depin uzantıları bloğu Grass ve Gradient'i ([betik][ii-depin]), yani iki uygulamayı başlatır. Toplam 23. README tablosu, bazılarında yalnızca kayıt bağlantısı olan 27 uygulama listeler.
- **CashFactory.** `docker-compose.yml` içindeki kazanç hizmetleri: 11. Portainer, web sunucusu ve iki Watchtower sayılmaz. Bir hizmet yorum satırına alınmıştır.
- **HA eklentileri.** Yapılandırma dosyası olan eklenti klasörleri: 10.

Her listedeki her uygulamanın hâlâ ödeme yapıp yapmadığını kontrol etmedik.

## CashPilot'un geride kaldığı yerler { #where-cashpilot-is-behind }

- Ana makine ağı, yayımlanmış portlar, birimler, cihazlar veya ek ağ yetkileri gerektiren hizmetler bir proxy üzerinden çalışamaz, bu yüzden <!-- n:docker -->21<!-- /n --> hizmetten 10'u (EarnApp, URnetwork, ProxyBase Markets, Bitping, Mysterium, Storj, Sia, Anyone Protocol, SRBMiner-Multi ve Kryptex Pool (Pearl)) yalnızca sunucunun kendi IP'sinden kazanır ([proxy kopyaları](proxies.md#what-cannot-run-through-a-proxy)).
- Kendi başlattığı uygulama sayısı InternetIncome'dan azdır.
- Günlük ödül talebi ve otomatik imaj güncellemeleri yoktur.
- <!-- n:docker -->21<!-- /n --> kazanç uygulaması imajından 12'si yayıncılarının en son etiketini izler.
- Soket proxy'si henüz bir root sınırı değildir: ele geçirilmiş bir worker, politikası dahilinde hâlâ konteyner oluşturabilir ve iki adımlı kaçışlar (başka bir konteynerin süreç ad alanına katılmak, izin verilen bir klasördeki bir sembolik bağlantı) reddedilmez ([ayrıntılar](security-defaults.md)).
- Saklanan kimlik bilgilerinin şifreleme anahtarı verilerle aynı birimde durur ve her worker'da kazanç uygulaması kimlik bilgileri Docker'ın konteyner yapılandırmasında düz metindir.
- Bazı toplayıcılar tarayıcıdan kopyalanmış bir çerez veya belirteç gerektirir ve bunların bazılarının süresi dolar, bu yüzden o hizmetlerde kazanç takibi bakım ister.
- Arayüz yazı tiplerini ve Chart.js'yi üçüncü taraf CDN'lerden yükler.
- LAN yalıtımı, kazanç uygulamaları Docker'ın varsayılan köprüsünde bulunan yükseltilmiş bir kurulumda siz açana kadar kapalı kalır; `CASHPILOT_CONTAINER_NETWORK` içinde adı verilen bir ağa bariyer koymaz ([yalıtım](isolation.md#modes)); 2.0.6 ve öncesiyle dağıtılmış bir Mysterium düğümü de siz onu yeniden dağıtana kadar bariyersiz olarak ana makinenin ağında kalır ([bariyerin arkasında Mysterium](mysterium-fence.md)).
- money4band'inkinden çok daha küçük bir topluluk.
- Sık sürüm yayımlar, bazen günde birkaç kez.

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

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L515-L531
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L48
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/orchestrator.py#L745-L752
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L1244
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L992-L1040
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/01e7310cf1d923ba35523d8944ebaf2478f39079/services/bandwidth/mysterium.yml#L19-L113
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/docker-compose.yml#L69-L106
[cp-update]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/update_check.py#L80
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/exchange_rates.py#L101-L119
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L313
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L254
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/proxy_tunnel.py#L336-L350
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/tunnel/cp-tunnel#L48-L99
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L83-L100
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L630-L646
