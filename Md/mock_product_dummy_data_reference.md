# Mock Product Dummy Data Reference

Bu dosya, mock product demo verisini test ederken hizli referans olarak kullanilsin diye hazirlandi.

Amac:
- Hangi tabloya veri yuklendigini bilmek
- Hangi kolonun ne anlama geldigini gormek
- Soru sorarken hangi veri mantigina gore sorman gerektigini anlamak

## Hizli Ozet

| Tablo | Satir sayisi | Aciklama |
| --- | ---: | --- |
| `measurementType` | 5 | Olcum turleri |
| `measurementPointType` | 5 | Olcum noktasi tipleri |
| `facilityType` | 5 | Tesis tipleri |
| `operationArea` | 2 | Operasyon alanlari |
| `region` | 2 | Bolgesel ust katman |
| `district` | 2 | Basit district lookup |
| `districtInfo` | 2 | Zengin district/DMA bilgisi |
| `data_sources` | 3 | Veri kaynaklari |
| `assets` | 6 | Ana saha varliklari |
| `assetProperties` | 3 | Asset'e bagli ek alanlar |
| `consumer_profile` | 1 | Tuketici profili |
| `dataDefinition` | 8 | Register tanimlari |
| `waterBalance` | 2 | Su dengesi kayitlari |
| `s_data_current` | 7 | En guncel olcumler |
| `s_data` | 3660 | Yaklasik 1 aylik history |

## En Onemli Join Mantigi

```text
assets.id
  -> dataDefinition.assetId
  -> dataDefinition.register
  -> s_data.dataid / s_data_current.dataid
```

Olcum tipi:

```text
measurementType.id
  -> dataDefinition.measurementTypeId
```

Konum:

```text
assets.region   -> region.id
assets.district -> districtInfo.id
assets.opAreaId -> operationArea.opAreaId
```

## Lookup Tablolari

### `measurementType`

| id | name | Anlam |
| ---: | --- | --- |
| 1 | `flow` | Debi / akis |
| 2 | `pressure` | Basinc |
| 3 | `level` | Seviye |
| 4 | `consumption` | Tuketim |
| 5 | `leakage` | Kacak |

Bu tablo soru yazarken en kritik lookup'lardan biri. `flow`, `pressure`, `level` gibi kelimeler genelde buradan okunur.

Turkce metrik sozlugu:

| Kullanici ifadesi | Sistemde karsiligi |
| --- | --- |
| `debi`, `akis`, `akis miktari`, `su debisi`, `su akisi` | `flow` |
| `basinc`, `su basinci`, `hat basinci`, `sebeke basinci` | `pressure` |
| `seviye`, `su seviyesi`, `depo seviyesi`, `rezervuar seviyesi` | `level` |
| `tuketim`, `su tuketimi`, `kullanim`, `faturali tuketim` | `consumption` |
| `kacak`, `su kacagi`, `sebeke kacagi`, `kayip` | `leakage` |

### `measurementPointType`

| id | name |
| ---: | --- |
| 1 | `reservoir_sensor` |
| 2 | `dma_meter` |
| 3 | `pump_sensor` |
| 4 | `consumer_meter` |
| 5 | `valve_sensor` |

### `facilityType`

| id | name |
| ---: | --- |
| 1 | `reservoir` |
| 2 | `pump_station` |
| 3 | `metering_station` |
| 4 | `dma` |
| 5 | `chamber` |

## Konum Katmani

### `operationArea`

| opAreaId | name |
| ---: | --- |
| 201 | `North Operations` |
| 202 | `West Operations` |

### `region`

| id | name | city |
| ---: | --- | --- |
| 1 | `North Region` | `DemoCity` |
| 2 | `West Region` | `DemoCity` |

### `district`

| id | name |
| ---: | --- |
| 11 | `Riverside` |
| 12 | `Hilltop` |

### `districtInfo`

Bu tablo test sorularinda cok kullanisli.

| id | name | region |
| ---: | --- | ---: |
| 101 | `Riverside DMA` | 1 |
| 102 | `Hilltop DMA` | 2 |

Not:
- `Hilltop districtindeki` ve `Hilltop DMA` gibi ifadeler daha net eslesir.
- `Hilltop bolgesindeki` ifadesi de destekleniyor ama veri semantigi district/DMA tarafina daha yakindir.

## Ana Varliklar

### `assets`

Onemli kolonlar:

| Kolon | Anlam |
| --- | --- |
| `id` | Asset kimligi |
| `parentId` | Ust asset |
| `type` | Varlik tipi |
| `label` | Kullaniciya gorunen ad |
| `measurementPointTypeId` | Olcum noktasi tipi |
| `facilityTypeId` | Tesis tipi |
| `opAreaId` | Operasyon alani |
| `region` | Region referansi |
| `district` | DistrictInfo referansi |
| `i2` | Bu seed'de consumer profile link'i |

Seed edilen ana asset'ler:

| id | label | type | region | districtInfo |
| ---: | --- | --- | ---: | ---: |
| 1101 | `North Reservoir A` | `reservoir` | 1 | 101 |
| 1201 | `Riverside DMA Inlet` | `DMA` | 1 | 101 |
| 1301 | `East Pump Station` | `pump` | 1 | 101 |
| 1401 | `Valve Chamber 7` | `valve` | 1 | 101 |
| 1501 | `Hilltop DMA Inlet` | `DMA` | 2 | 102 |
| 1601 | `Consumer Meter Block A` | `meter` | 1 | 101 |

### `assetProperties`

Bu tablo daha esnek ek alanlar icin var.

| Kolon | Anlam |
| --- | --- |
| `assetId` | Bagli asset |
| `i1`, `i2` | Esnek integer alanlar |
| `f1`, `f2` | Esnek numeric alanlar |
| `d1`, `d2` | Esnek tarih alanlari |

Bu tabloda su an 3 asset icin ek veri var: `1101`, `1201`, `1501`.

### `consumer_profile`

| profileId | name | type | asset_id |
| ---: | --- | --- | ---: |
| 701 | `Residential Midrise` | `residential` | 1601 |

## Register ve Olcum Tanimlari

### `dataDefinition`

Bu tablo en kritik tablolardan biri. Hangi register hangi asset'e, hangi olcum tipine ve hangi birime bagli burada gorursun.

Onemli kolonlar:

| Kolon | Anlam |
| --- | --- |
| `id` | Definition id |
| `register` | Stabil register anahtari |
| `label` | Register adi |
| `archivePeriod` | Beklenen veri periyodu |
| `isActive` | Aktif mi |
| `measurementTypeId` | Olcum tipi |
| `assetId` | Bagli asset |
| `unit` | Olcu birimi |
| `type` | `telemetry` ya da `derived` |
| `formula` | Turetilmis hesap aciklamasi |
| `dataSourceId` | Veri kaynagi |

Seed edilen register'lar:

| id | register | label | type | assetId | unit | isActive |
| ---: | --- | --- | --- | ---: | --- | --- |
| 2001 | `REG_FLOW_DMA_RIVERSIDE` | `Riverside Inlet Flow` | `flow` | 1201 | `m3/h` | `true` |
| 2002 | `REG_PRESS_DMA_RIVERSIDE` | `Riverside Pressure` | `pressure` | 1201 | `bar` | `true` |
| 2003 | `REG_LEVEL_RES_NORTH` | `North Reservoir Level` | `level` | 1101 | `m` | `true` |
| 2004 | `REG_CONS_DMA_RIVERSIDE` | `Riverside Billed Consumption` | `consumption` | 1601 | `m3/d` | `true` |
| 2005 | `REG_LEAK_DMA_RIVERSIDE` | `Riverside Estimated Leakage` | `leakage` | 1201 | `m3/d` | `true` |
| 2006 | `REG_FLOW_DMA_HILLTOP` | `Hilltop Inlet Flow` | `flow` | 1501 | `m3/h` | `true` |
| 2007 | `REG_PRESS_DMA_HILLTOP` | `Hilltop Pressure` | `pressure` | 1501 | `bar` | `true` |
| 2008 | `REG_FLOW_PUMP_EAST` | `East Pump Station Flow` | `flow` | 1301 | `m3/h` | `false` |

Not:
- `2008` bilerek `isActive = false` birakildi.
- Bu sayede `Aktif dataDefinition kaydi olmayan assetler hangileri?` gibi sorular anlamli oluyor.

### `data_sources`

| id | name | type |
| ---: | --- | --- |
| 1 | `SCADA OPC-UA` | `opcua` |
| 2 | `Pressure MQTT Feed` | `mqtt` |
| 3 | `Formula Engine` | `formula` |

## Current Veri

### `s_data_current`

Bu tablo "en son", "guncel", "latest" sorulari icin ana kaynaktir.

Onemli kolonlar:

| Kolon | Anlam |
| --- | --- |
| `dataid` | `dataDefinition.register` ile join olur |
| `interval` | `15m`, `1d` gibi periyot |
| `type` | `telemetry` ya da `derived` |
| `ze1`, `ze2` | Zaman araligi |
| `value` | Asil olcum degeri |
| `art` | `avg`, `sum` gibi aggregation tipi |
| `quality` | Veri kalitesi |

Current kayitlar:

| dataid | value | unit | Not |
| --- | ---: | --- | --- |
| `REG_FLOW_DMA_RIVERSIDE` | 182.4 | `m3/h` | Riverside son flow |
| `REG_PRESS_DMA_RIVERSIDE` | 4.8 | `bar` | Riverside son pressure |
| `REG_LEVEL_RES_NORTH` | 7.2 | `m` | Reservoir son level |
| `REG_CONS_DMA_RIVERSIDE` | 3520.0 | `m3/d` | Riverside son consumption |
| `REG_LEAK_DMA_RIVERSIDE` | 621.0 | `m3/d` | Riverside son leakage |
| `REG_FLOW_DMA_HILLTOP` | 143.1 | `m3/h` | Hilltop son flow |
| `REG_PRESS_DMA_HILLTOP` | 4.3 | `bar` | Hilltop son pressure |

## History Veri

### `s_data`

Bu tablo artik gercek anlamda history tablosu gibi davranir.

Kapsam:
- Baslangic: `2026-04-11 00:00:00`
- Bitis: `2026-05-10 23:00:00`
- Toplam satir: `3660`

Dagilim:

| Register | Ornek sayisi | Frekans |
| --- | ---: | --- |
| `REG_FLOW_DMA_RIVERSIDE` | 720 | Saatlik |
| `REG_PRESS_DMA_RIVERSIDE` | 720 | Saatlik |
| `REG_LEVEL_RES_NORTH` | 720 | Saatlik |
| `REG_FLOW_DMA_HILLTOP` | 720 | Saatlik |
| `REG_PRESS_DMA_HILLTOP` | 720 | Saatlik |
| `REG_CONS_DMA_RIVERSIDE` | 30 | Gunluk |
| `REG_LEAK_DMA_RIVERSIDE` | 30 | Gunluk |

Onemli kolonlar:

| Kolon | Anlam |
| --- | --- |
| `dataid` | Register anahtari |
| `ze1`, `ze2` | Zaman araligi |
| `value` | Olcum degeri |
| `interval` | `1h` ya da `1d` |
| `art` | `avg` ya da `sum` |
| `type` | `telemetry` ya da `derived` |
| `quality` | Veri kalitesi |
| `created_at` | Sisteme yazilma zamani |

Bu history ile artik sunlar daha anlamli:
- `Hilltop bolgesindeki flow degerlerinin ortalamasi nedir?`
- `Riverside districtindeki pressure degerlerinin ortalamasi nedir?`
- `Son 1 ayda Hilltop flow trendi nasil?`
- `North Reservoir level gecmiste nasil degismis?`

Ornek tarihsel referans degerler:

| Soru | Beklenen mantikli sonuc |
| --- | --- |
| `Hilltop bolgesindeki flow degerlerinin ortalamasi nedir?` | Yaklasik `140.62 m3/h` |
| `Riverside districtindeki pressure degerlerinin ortalamasi nedir?` | Yaklasik `5.05 bar` |

## Water Balance

### `waterBalance`

Bu tablo leakage ve su dengesi sorulari icin kullanilir.

Onemli kolonlar:

| Kolon | Anlam |
| --- | --- |
| `assetId` | Hangi asset icin |
| `interval` | Periyot |
| `systemInputId` | Giris register'i |
| `billMeteredId` | Faturali olculen tuketim |
| `billUnmeteredId` | Faturali olculmeyen tuketim |
| `leakageNetwork` | Sebeke kacagi |
| `leakageReservoir` | Depo kacagi |
| `leakageService` | Servis hatti kacagi |

Seed edilen kayitlar:

| id | assetId | interval | systemInputId | billMeteredId | leakageNetwork | leakageService |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 3001 | 1201 | `1d` | 2001 | 2004 | 14.8 | 4.2 |
| 3002 | 1501 | `1d` | 2006 | `NULL` | 9.7 | 2.9 |

## Test Sorulari Icin Pratik Rehber

En iyi calisan soru tipleri:

| Hedef | Ornek soru |
| --- | --- |
| Current deger | `Riverside districtindeki en son pressure degeri nedir?` |
| Current flow | `Hilltop bolgesindeki en son flow degeri nedir?` |
| Average history | `Hilltop bolgesindeki flow degerlerinin ortalamasi nedir?` |
| Historical pressure | `Riverside districtindeki pressure degerlerinin ortalamasi nedir?` |
| Asset listesi | `Aktif dataDefinition kaydi olmayan assetler hangileri?` |
| Count | `Kac tane asset var?` |
| Register listesi | `Riverside DMA icin hangi registerlar tanimli?` |
| Water balance | `Water balance kayitlarinda hangi assetler var?` |

Kisa ezber:
- `en son`, `latest`, `current` -> genelde `s_data_current`
- `ortalama`, `gecmis`, `history`, `trend` -> genelde `s_data`
- `hangi register`, `hangi olcum tanimli` -> genelde `dataDefinition`
- `hangi asset nerede` -> genelde `assets` + `districtInfo` + `region`
- `kacak`, `su dengesi`, `leakage` -> genelde `waterBalance`
