# Mock Product Demo Setup

Bu proje artık `mock-npm-llm-schema.json` içindeki ürün-benzeri şemayı mevcut demo akışına paralel olarak destekliyor.

## Ne eklendi

- `app/mock_product_schema.py`
  JSON dosyasını okuyup Vector DB için schema guidance üretir.
- `scripts/generate_mock_product_sql.py`
  JSON dosyasından `schema.sql` ve `seed.sql` üretir.
- `scripts/sql/mock_product_schema.sql`
  Demo relational schema kurulumu için DDL.
- `scripts/sql/mock_product_seed.sql`
  Anlamlı dummy data içeren seed scripti.
  Seed içinde `s_data` için yaklaşık 1 aylık history de bulunur.

## Çalışma mantığı

- Vector DB:
  Şemanın açıklaması, ilişkileri ve örnek sorgu pattern'leri embed edilip retrieval tarafında kullanılır.
- Data Processing DB:
  Gerçek satırlar burada tutulur. LLM önce Vector DB'den schema guidance alır, sonra gerekiyorsa read-only SQL üretir.

## SQL dosyalarını yeniden üretme

```powershell
python scripts/generate_mock_product_sql.py
```

## Demo DB'ye kurma

Örnek:

```powershell
psql -h localhost -p 5433 -U demo_user -d demo_local -f scripts/sql/mock_product_schema.sql
psql -h localhost -p 5433 -U demo_user -d demo_local -f scripts/sql/mock_product_seed.sql
```

## Ne tür sorular hedefleniyor

- Bir district içindeki en güncel pressure değeri nedir?
- Region bazında historical flow toplamı nedir?
- Hilltop bölgesindeki flow değerlerinin ortalaması nedir?
- Active `dataDefinition` kaydı olmayan asset'ler hangileri?
- `waterBalance` kayıtları hangi measurement register'lara bağlı?

## Notlar

- `dashboard_like_external.id` tanımlı olmadığı için bu foreign key bilerek atlanır.
- `assets.i2 <-> consumer_profile.profileId` ilişkisi seed aşamasında `UPDATE` ile tamamlanır.
- Var olan `formula`, `validation`, `aggregation` ve `npm` demo akışları korunur.
