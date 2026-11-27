---
source_hash: e99e2c0c80bb
---
# Uygulama mağazaları { #app-stores }

CashPilot'u birçok ev sunucusu sisteminin uygulama mağazasından kurabilirsiniz.
Her liste panoyu (`drumsergio/cashpilot`) ve hizmet konteynerlerini başlatıp
durduran worker'ı (`drumsergio/cashpilot-worker`) kurar. Bu depodaki paketlerden
yalnızca CasaOS ve Runtipi paketleri `docker-compose.yml` içindeki Docker soket
proxy'sini de kurar, bu yüzden onların worker'ı ham Docker soketini hiçbir zaman tutmaz.
Unraid şablonları, TrueNAS uygulaması ve CasaOS uygulama mağazasına açık çekme
isteğindeki paket ise Docker soketini hâlâ doğrudan worker'a bağlar.

Hangi mağazayı kullanırsanız kullanın, panoyu LAN'ınızda veya VPN'inizde tutun. Pano
worker'a komut verebilir, worker da ana makinedeki Docker'ı yönetir. Worker'ın soketi
kendisinin tuttuğu yerde bu, ana makinede root demektir.

## Bugün listelenenler { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Apps sekmesinde **CashPilot** araması yapın ve iki şablonu da kurun:
`cashpilot` (pano) ve `cashpilot-worker`. İkisinde de aynı
`CASHPILOT_API_KEY` değerini ayarlayın.

Şablonlar https://github.com/GeiserX/docker-templates adresinden gelir ve
`latest` imaj etiketini izler, bu yüzden Community Applications kullanıcıları her sürümü
şablon değişikliği olmadan alır.

### TrueNAS SCALE { #truenas-scale }

CashPilot, TrueNAS **community** treninde yer alır. Apps'i, ardından Discover Apps'i açın
ve **CashPilot** araması yapın.

Uygulama tanımı
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot adresinde tutulur ve
tam bir imaj digest'ini sabitler. TrueNAS'ın kendi botları onu yeni sürümlere taşır, bu yüzden
en yeni CashPilot sürümünün birkaç sürüm gerisinde olabilir.

## İncelemeyi bekleyenler { #waiting-for-review }

### CasaOS { #casaos }

CasaOS uygulama mağazasına bir çekme isteği açıktır:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

İstek birleştirilene kadar CashPilot'u özel uygulama olarak kurun: CasaOS'ta App Store'u,
ardından Custom Install'u, ardından Import'u seçin ve şu dosyanın içeriğini yapıştırın:
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

CasaOS 0.4.5 veya daha yenisi gerekir: o sürümden itibaren uygulama yöneticisi, soket
proxy'sinin politikasını dosyadan okuyan Docker Compose 2.23 üzerine kuruludur.
Daha eski sürümler politikayı atar ve worker bu durumda Docker'a ulaşamaz.

O dosya tam bir sürümü sabitler. İçe aktarmadan önce iki imaj etiketini de
(`drumsergio/cashpilot` ve `drumsergio/cashpilot-worker`)
https://github.com/GeiserX/CashPilot/releases adresindeki en yeni sürüme ayarlayın. Dosyadaki
proxy politikası `main` dalını izler; worker'ın durum sayfası politikasının
güncel olmadığını söylüyorsa dosyayı yeniden içe aktarın.

## Hazır, henüz gönderilmedi { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Paket
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
adresinde hazırdır, ancak henüz Runtipi uygulama mağazasında değildir. Şimdi kullanmak için
Runtipi belgelerini izleyerek onu kontrol ettiğiniz özel bir uygulama mağazasına ekleyin:
https://runtipi.io/docs/guides/create-your-own-app-store

## Sunulmayanlar { #not-offered }

Umbrel farklı bir worker tasarımı gerektirir, çünkü Umbrel uygulamaları Docker'a ana makine
soketi yerine Docker-in-Docker konteyneri üzerinden ulaşır. Bunu test etmedik,
bu yüzden henüz bir Umbrel paketi yok.

Diğer tüm sistemlerde, [Başlarken](getting-started.md) sayfasında anlatıldığı gibi depodaki
`docker-compose.yml` dosyasını kullanın.
