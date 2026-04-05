# Crawler Grup

CLI Python untuk mencari link grup publik WhatsApp atau Telegram dari hasil pencarian web, mengecek apakah grup masih aktif, lalu menyimpan hasil aktif ke Google Sheets tab `Grup`.

Perilaku default saat ini:
- platform dipilih lewat `--platform whatsapp` atau `--platform telegram`
- keyword akan diperluas ke banyak query discovery publik dalam mode `wide`
- provider default per platform:
  - WhatsApp: `brave`
  - Telegram: `duckduckgo`, `yahoo`, `aol`, dan `brave`
- untuk WhatsApp dengan provider default `brave`, worker query default diturunkan agar lebih tahan terhadap rate limit
- grup aktif difilter minimum `50` anggota jika jumlah anggota bisa dibaca dari metadata
- crawler mengikuti sampai `2` hop tambahan dari halaman hasil untuk menangkap link grup yang tersembunyi di halaman lanjutan
- hasil validasi disimpan ke cache SQLite selama `72` jam agar link yang sama tidak dicek ulang setiap run
- ada budget fetch global default `200` halaman target per run agar discovery agresif tetap terkontrol
- hasil yang dikirim ke sheet hanya grup dengan status `active`
- sink default adalah Google Sheets, bukan file lokal
- file lokal hanya dibuat jika `--output` diisi
- nama grup difilter ke grup Indonesia secara default
- jika dijalankan tanpa argumen di terminal interaktif, wizard akan muncul untuk memilih platform, keyword/query, target grup, sink sheet, dan scheduler
- tersedia mode scheduler untuk menjalankan crawler berulang dan terus menambah hasil baru ke sheet
- provider pencarian yang tersedia: `duckduckgo`, `brave`, `yahoo`, `aol`, `google`

## Cara Pakai

Jalankan langsung dari source:

```bash
python3 crawler_wa.py
python3 crawler_wa.py --platform whatsapp --keyword-file keywords.whatsapp.txt --max-active-groups 20
python3 crawler_wa.py --platform telegram --keyword-file keywords.telegram.txt --max-active-groups 20
```

Jika kamu menjalankan:

```bash
python3 crawler_wa.py
```

maka wizard interaktif akan muncul dan kamu bisa memilih:
- WhatsApp atau Telegram
- pakai semua keyword bawaan, keyword sendiri, file keyword, atau query mentah
- jumlah grup aktif target
- kirim ke sheet atau simpan file lokal
- jalan sekali atau scheduler rutin

Atau instal editable lalu pakai command CLI:

```bash
python3 -m pip install -e .
crawler-groups --platform whatsapp --keyword-file keywords.whatsapp.txt --max-active-groups 20
```

Pakai file query jika ingin query yang sudah dibentuk penuh:

```bash
python3 crawler_wa.py --platform whatsapp --query-file queries.whatsapp.txt
python3 crawler_wa.py --platform telegram --query-file queries.telegram.txt
```

Pilih provider tertentu saja:

```bash
python3 crawler_wa.py \
  --platform whatsapp \
  --keyword 'komunitas coding' \
  --provider duckduckgo \
  --provider brave \
  --provider yahoo \
  --provider aol
```

Discovery lebar ke sosial media dan website publik:

```bash
python3 crawler_wa.py \
  --platform telegram \
  --keyword 'komunitas mahasiswa' \
  --discovery-mode wide \
  --source-domain facebook.com \
  --source-domain instagram.com \
  --source-domain tiktok.com
```

Batasi jumlah grup aktif yang dicari:

```bash
python3 crawler_wa.py \
  --platform telegram \
  --keyword 'komunitas mahasiswa' \
  --max-active-groups 10
```

Optimasi discovery yang lebih agresif:

```bash
python3 crawler_wa.py \
  --platform telegram \
  --keyword-file keywords.telegram.txt \
  --max-active-groups 20 \
  --min-member-count 50 \
  --follow-hops 2 \
  --max-follow-pages 3 \
  --max-fetch-budget 200 \
  --max-query-workers 8 \
  --max-validation-workers 8
```

Atur cache validasi:

```bash
python3 crawler_wa.py \
  --platform telegram \
  --keyword-file keywords.telegram.txt \
  --cache-db crawler_cache.sqlite3 \
  --cache-ttl-hours 72
```

Simpan juga ke file lokal:

```bash
python3 crawler_wa.py \
  --platform whatsapp \
  --keyword-file keywords.whatsapp.txt \
  --output active_whatsapp_links.txt
```

Matikan sink ke sheet dan simpan lokal saja:

```bash
python3 crawler_wa.py \
  --platform telegram \
  --keyword 'komunitas mahasiswa' \
  --no-sheet-sync \
  --output active_telegram_links.txt
```

Matikan filter grup Indonesia:

```bash
python3 crawler_wa.py \
  --platform telegram \
  --keyword-file keywords.telegram.txt \
  --allow-global-groups
```

Jalankan scheduler agar crawler rutin menambah hasil ke sheet:

```bash
python3 crawler_wa.py \
  --platform whatsapp \
  --discovery-mode focused \
  --keyword 'komunitas ai indonesia' \
  --keyword 'komunitas umkm indonesia' \
  --max-active-groups 10 \
  --max-query-workers 1 \
  --schedule-every-minutes 60
```

Contoh scheduler dengan batas jumlah siklus:

```bash
python3 crawler_wa.py \
  --platform whatsapp \
  --keyword 'komunitas digital marketing' \
  --schedule-every-minutes 30 \
  --schedule-max-runs 4
```

File contoh yang sudah dipisah per platform:
- `keywords.whatsapp.txt`
- `queries.whatsapp.txt`
- `keywords.telegram.txt`
- `queries.telegram.txt`

Opsi yang paling sering dipakai:
- `--platform`: pilih `whatsapp` atau `telegram`
- `--keyword-file`: file keyword dasar yang akan dibentuk jadi query pencarian
- `--query-file`: file query penuh
- `--keyword`: tambah keyword langsung dari terminal
- `--query`: tambah query langsung dari terminal
- `--provider`: pilih provider pencarian, bisa dipakai berulang
- `--discovery-mode`: `focused` untuk query sempit, `wide` untuk discovery lebar ke sosial media dan website publik
- `--source-domain`: tambahkan domain sumber discovery publik, misalnya `facebook.com`, `forumkampus.id`, atau `kompasiana.com`
- `--max-active-groups`: hentikan proses setelah jumlah grup aktif tercapai
- `--min-member-count`: filter minimum jumlah anggota grup aktif, default `50`
- `--follow-hops`: jumlah hop lanjutan dari halaman hasil, default `2`
- `--max-follow-pages`: jumlah halaman lanjutan maksimum dari tiap halaman hasil
- `--max-fetch-budget`: batas total fetch halaman hasil lanjutan per run, default `200`
- `--max-validation-workers`: jumlah worker paralel untuk validasi grup aktif
- `--cache-db`: path file cache SQLite untuk status validasi link
- `--cache-ttl-hours`: umur maksimum cache validasi sebelum dicek ulang
- `--no-cache`: matikan cache SQLite
- `--schedule-every-minutes`: aktifkan mode scheduler dan jalankan ulang tiap N menit
- `--schedule-max-runs`: batasi jumlah siklus scheduler
- `--schedule-initial-delay-seconds`: tunda run pertama saat scheduler aktif
- `--output`: simpan hasil aktif ke file lokal
- `--no-sheet-sync`: matikan pengiriman default ke sheet
- `--allow-global-groups`: matikan filter grup Indonesia
