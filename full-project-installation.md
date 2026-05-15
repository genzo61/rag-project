# Data Processing Modülü + LLM/RAG Mikroservisi Kurulum Dokümanı

## 1. Genel Mimari ve Kurulum Sırası

1. Docker Desktop kurulumu ve Docker servisinin çalıştığının doğrulanması.
2. pgvector veritabanının Docker ile kurulması ve vector extension’ın aktif edilmesi.
3. SearXNG local web search servisinin Docker ile kurulması.
4. Data Processing modülünün Git üzerinden indirilmesi, .env dosyasının oluşturulması ve docker compose ile çalıştırılması.
5. PostgreSQL/pgAdmin bağlantısının yapılması ve mock product veritabanı şeması + dummy data’nın basılması.
6. Ollama kurulumu, gerekli modellerin indirilmesi ve LLM/RAG mikroservisinin çalıştırılması.
7. Servislerin tarayıcı ve curl komutları ile doğrulanması.

## 2. Ön Gereksinimler

Kuruluma başlamadan önce aşağıdaki araçların bilgisayarda hazır olması gerekir:

| Araç              | Neden gerekli?                                                             | Kontrol komutu   |
| ----------------- | -------------------------------------------------------------------------- | ---------------- |
| Docker Desktop    | pgvector, SearXNG ve proje servislerini container olarak çalıştırmak için. | docker --version |
| Git               | Projeleri Git repo üzerinden indirmek için.                                | git --version    |
| Python 3.10+      | LLM/RAG mikroservisini lokal çalıştırmak için.                             | python --version |
| PostgreSQL client | Veritabanı bağlantısı ve SQL scriptlerini çalıştırmak için.                | psql --version   |
| Ollama            | Local LLM ve embedding modellerini çalıştırmak için.                       | ollama --version |

## 3. Resmi Kurulum Bağlantıları

- Docker Desktop Windows kurulumu -> https://docs.docker.com/desktop/install/windows-install/
- Docker Desktop WSL 2 ayarı -> https://learn.microsoft.com/tr-tr/windows/wsl/install
- pgAdmin Windows indirme sayfası -> https://www.pgadmin.org/download/
- Ollama Windows kurulumu -> https://ollama.com/download
- SearXNG Docker kurulumu -> https://docs.searxng.org/admin/docker.html

## 4. Port Haritası

Kurulum sırasında default olarak kullanılan portların değerleri gösterilmiştir.

| Servis             | Host Port | Container Port | Açıklama                     |
| ------------------ | --------- | -------------- | ---------------------------- |
| pgvector-db        | 5436      | 5432           | RAG/vector database: rag_db  |
| SearXNG            | 8089      | 8080           | Local web search servisi     |
| Data Processing UI | 5173      | -              | Frontend arayüz              |
| Data Processing DB | 5433      | 5432           | Mock product / demo_local DB |
| LLM/RAG API        | 8000      | -              | FastAPI mikroservisi         |
| Ollama             | 11434     | -              | Local LLM servis portu       |

## 5. Docker Desktop Kurulumu

Windows üzerinde Docker Desktop kurulumu yapılır. Kurulumdan sonra Docker Desktop açılır ve servis tamamen başlatılır.

- Docker Desktop Windows kurulum sayfasından installer indirilir.
- Kurulum sırasında WSL 2 kullanımı istenirse onaylanır.
- Kurulum sonrası bilgisayar yeniden başlatılırsa Docker Desktop tekrar açılır.
- PowerShell açılarak Docker’ın çalıştığı doğrulanır. (Aşağıdaki komutlar kullanılabilir)
  docker --version
  docker ps

## 6. pgvector Veritabanı Kurulumu

RAG tarafında vektör verilerini saklamak için pgvector container'ı kurulup çalıştırılır.

docker run -d --name pgvector-db ^
-e POSTGRES_USER=postgres ^
-e POSTGRES_PASSWORD=1234 ^
-e POSTGRES_DB=rag_db ^
-p 5436:5432 ^
pgvector/pgvector:pg16

- PowerShell tek satır kullanım:
  docker run -d --name pgvector-db -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=1234 -e POSTGRES_DB=rag_db -p 5436:5432 pgvector/pgvector:pg16

- Kurulumdan sonra vector extension aktif edilir:
  docker exec -it pgvector-db psql -U postgres -d rag_db -c "CREATE EXTENSION IF NOT EXISTS vector;"

- pgvector Extension kontrolü:
  docker exec -it pgvector-db psql -U postgres -d rag_db -c "SELECT extname FROM pg_extension;"

- Beklenen çıktı Aşağıdaki gibidir:
  plpgsql
  vector

## 7. SearXNG Local Web Search Kurulumu

Web search senaryoları için SearXNG lokal olarak Docker container içinde çalıştırılır.

- Docker run komutu:
  docker run -d --name searxng -p 8089:8080 --restart always searxng/searxng:latest

-Çalıştığını test etmek için:
curl.exe "http://localhost:8089/search?q=searxng&format=json"

## 8. Data Processing Modülünün Kurulumu

Data Processing projesi Git üzerinden indirilir ve proje klasörüne girilir.

- Git komutu:
  git clone https://haydar.ali61@bitbucket.org/vivavis-intern/d.git
  cd d

# 8.1 .env Dosyasını Oluşturma

Proje içinde .env.example dosyası mevcuttur. Bu dosyanın içeriğinin aynısını oluşturulan .env dosyasına aktarabilirsiniz. Default olarak.

- Örnek .env içeriği aşağıdaki gibi olabilir.

DB_HOST=localhost
DB_PORT=5436
DB_NAME=rag_db
DB_USER=postgres
DB_PASSWORD=1234

DP_DB_HOST=localhost
DP_DB_PORT=5433
DP_DB_NAME=demo_local
DP_DB_USER=demo_user
DP_DB_PASSWORD=DemoLocalDb!2026

LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.2:3b
OLLAMA_EMBED_MODEL=nomic-embed-text
SEARXNG_BASE_URL=http://localhost:8089

# 8.2 Data Processing Servislerini Çalıştırma

- Proje klasöründeyken aşağıdaki komutu çalıştırınız:
  docker compose up --build
- Container durumunu kontrol etmek için:
  docker compose ps
  docker compose logs --tail=100

- Bu İşlemler yapıldıktan sonra aşağıdaki web arayüz adresini açabilirsiniz.
  http://localhost:5173/
- Data Processing modülü açıldıktan sonra sisteme giriş için aşağıdaki giriş bilgilerini kulanabilirsiniz.
  Kullanıcı adı : admin  
   şifre : 1234

## 9. PostgreSQL, pgAdmin ve psql Kullanımı

# 9.1 pgAdmin Kurulumu

    1. pgAdmin Windows indirme sayfasına gidilir ve güncel installer indirilir.
    2. Installer çalıştırılır ve standart seçeneklerle kurulum tamamlanır.
    3. pgAdmin ilk açılışta bir Master Password ister. Bu şifre sadece pgAdmin uygulamasına giriş içindir, veritabanı şifresi değildir.

# 9.2 pgAdmin ile Data Processing Modülünün Veritabanına Bağlanma

pgAdmin içinde Servers > Register > Server adımıyla yeni bağlantı ekleme admına geçilir. Aşağıda Tabloda yer alan bilgilerle bağlantının kurulması gerekir.

| Alan                 | Değer            |
| -------------------- | ---------------- |
| Name                 | RAG Demo DB      |
| Host name/address    | localhost        |
| Port                 | 5433             |
| Maintenance database | demo_local       |
| Username             | demo_user        |
| Password             | DemoLocalDb!2026 |

# 9.3 psql Kurulumu ve Kullanımı

psql komutunun çalışması için PostgreSQL Command Line Tools kurulmalı ve PostgreSQL bin klasörü PATH’e eklenmelidir. İlk aşamalrda bunu yaptık zaten.

- Tipik Windows yolu:
  C:\Program Files\PostgreSQL\16\bin

- PATH kontrolü:
  psql --version

- pgvector DB’ye terminalden bağlanma örneği:  
   psql -h localhost -p 5436 -U postgres -d rag_db

- Data Processing DB’ye terminalden bağlanma örneği:
  psql -h localhost -p 5433 -U demo_user -d demo_local

## 10. Mock Product DB Şeması ve Dummy Data Basılması

Data Processing tarafındaki demo verilerin (LLM Tarafında Kullanılacak Olan Verilerin) oluşması için SQL dosyaları sırasıyla çalıştırılır.

1. pgAdmin içinde demo_local veritabanı seçilir.
2. Tools > Query Tool açılır.
3. scripts/sql/mock_product_schema.sql dosyasındaki tüm SQL kopyalanıp çalıştırılır.
4. Ardından scripts/sql/mock_product_seed.sql dosyası aynı şekilde çalıştırılır.
5. Messages sekmesinde Query returned successfully benzeri başarı mesajı görülmelidir.

- psql ile çalıştırmak isterseniz proje klasöründen şu komutlar kullanılabilir:

  psql -h localhost -p 5433 -U demo_user -d demo_local -f scripts/sql/mock_product_schema.sql
  psql -h localhost -p 5433 -U demo_user -d demo_local -f scripts/sql/mock_product_seed.sql

## 11. LLM/RAG Mikroservisinin Kurulumu

LLM mikroservisi ayrı repo olarak indirilir ve lokal FastAPI servisi şeklinde çalıştırılır.

- Git komutu:
  git clone https://github.com/genzo61/rag-project.git
  cd rag-project

# 11.1 Python Sanal Ortamı ve Paketler

- Terminalde Aşağıdaki Komut Çalıştırılır Ortam ayarları yapılır ve gerekli kütüphaneler indirilmesi sağlanır.
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  python -m pip install --upgrade pip
  pip install -r requirements.txt

# 11.2 LLM Mikroservisi .env Dosyası

- Proje içindeki .env.example dosyasının içeriğini kopyalayarak .env dosyası oluşturulur.

- Örnek .env içeriği aşağıdaki gibidir.

       DB_HOST=localhost
       DB_PORT=5436
       DB_NAME=rag_db
       DB_USER=postgres
       DB_PASSWORD=1234

       DP_DB_HOST=localhost
       DP_DB_PORT=5433
       DP_DB_NAME=demo_local
       DP_DB_USER=demo_user
       DP_DB_PASSWORD=DemoLocalDb!2026

       LLM_BACKEND=ollama
       OLLAMA_BASE_URL=http://localhost:11434
       OLLAMA_CHAT_MODEL=llama3.2:3b
       OLLAMA_EMBED_MODEL=nomic-embed-text
       SEARXNG_BASE_URL=http://localhost:8089

## 12. Ollama Kurulumu ve Model İndirme

Ollama Windows installer ile kurulur. Kurulumdan sonra PowerShell açılarak aşağıdaki komutlar çalıştırılır:

- Ollama versiyon kontrolü:
  ollama --version

- İndirilmiş modelleri listele:
  ollama list

- Chat modeli ve embedding model indirmek için komutlar.
  ollama pull llama3.2:3b
  ollama pull nomic-embed-text

## 13. LLM/RAG API’yi Çalıştırma

- rag-project klasöründe sanal ortam aktifken FastAPI servisi başlatılır:

        uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

## Gemma modelinin entegresi ve kurulum anlatımı elife tarafından yapılacaktır.

- Gemma modeli eklenmeden önce denemek için ollama modeli ile aşağıdaki komutlar .env dosyasındaki komutlar ile değiştirilmelidir. Gemma modeli eklendikten sonra tekrar eski duruma getirilebilir.
  OLLAMA_CHAT_MODEL=llama3.2:3b
  LOCAL_CHAT_MODEL_ID=llama3.2:3b
  RAG_UI_MODEL_ID=llama3.2:3b
