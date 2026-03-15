# Crawler Grup

CLI Python untuk mencari link grup publik WhatsApp atau Telegram dari hasil pencarian web, mengecek apakah grup masih aktif, lalu menyimpan hasil aktif ke Google Sheets tab `Grup`.

Perilaku default saat ini:
- platform dipilih lewat `--platform whatsapp` atau `--platform telegram`
- keyword akan diperluas ke banyak query discovery publik dalam mode `wide`
- hasil yang dikirim ke sheet hanya grup dengan status `active`
- sink default adalah Google Sheets, bukan file lokal
- file lokal hanya dibuat jika `--output` diisi
- nama grup difilter ke grup Indonesia secara default
- provider pencarian yang tersedia: `duckduckgo`, `brave`, `yahoo`, `aol`, `google`

## Cara Pakai

Jalankan langsung dari source:

```bash
python3 crawler_wa.py --platform whatsapp --keyword-file keywords.whatsapp.txt --max-active-groups 20
python3 crawler_wa.py --platform telegram --keyword-file keywords.telegram.txt --max-active-groups 20
```

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
- `--output`: simpan hasil aktif ke file lokal
- `--no-sheet-sync`: matikan pengiriman default ke sheet
- `--allow-global-groups`: matikan filter grup Indonesia
