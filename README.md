# solar-rooftop-drone

Perkiraan awal luas atap yang berpotensi dipasangi panel surya, dihitung dari **foto udara (ortofoto) hasil drone** dan data denah bangunan terbuka.

> **Status: v0.1.** Project ini baru mengukur *luas bangunan*. Belum ada perhitungan daya atau energi (lihat [Roadmap](#roadmap)).

---

## Disclaimer: baca ini dulu

Project ini adalah **alat screening awal**, bukan desain teknis dan bukan dasar keputusan investasi.

Angka yang dihasilkan menjawab pertanyaan *"kira-kira seberapa besar atap di area ini?"*, bukan *"berapa panel yang bisa dipasang di atap ini?"*. Beberapa hal yang **tidak** dihitung:

- **Kemiringan dan arah atap.** Data yang dipakai hanya foto 2D, tanpa informasi ketinggian (DSM). Atap datar, miring ke utara, dan miring ke selatan diperlakukan sama, padahal hasil energinya berbeda.
- **Bayangan dan halangan.** Pohon, bangunan tetangga, tangki air, cerobong, dan antena tidak dihitung.
- **Kondisi dan kekuatan atap.** Umur material, daya dukung struktur, dan kebocoran tidak diperiksa.
- **Aturan, izin, dan sambungan listrik.** Tidak ada pengecekan terhadap regulasi, pemilik bangunan, atau jaringan PLN.
- **Luas atap sebenarnya.** Luas yang dihitung adalah luas denah bangunan (proyeksi dari atas). Atap miring punya permukaan yang lebih luas dari denahnya, dan tidak seluruh permukaan bisa dipasangi panel.

Dua sumber ketidakpastian lain yang perlu diketahui:

- **Posisi denah bangunan tidak selalu pas.** Denah dari Overture Maps berasal dari beragam sumber (antara lain OpenStreetMap dan hasil deteksi otomatis). Di beberapa bangunan, terutama yang kecil atau tertutup pohon, garis denah bisa bergeser beberapa meter dari atap sesungguhnya.
- **Cakupan data bisa bolong.** Di sebagian wilayah Indonesia, bangunan belum terpetakan atau terpetakan sebagian. Jika jumlah bangunan terlalu sedikit, script akan menampilkan peringatan.

Untuk kebutuhan nyata (pemasangan, pembiayaan, atau perizinan), gunakan survei lapangan dan perhitungan oleh tenaga ahli.

---

## Tujuan

Banyak orang ingin tahu potensi surya sebuah kawasan, tapi belum punya data detail setiap atap. Project ini mencoba jalan yang ringan: memakai foto udara yang sudah ada, ditambah denah bangunan gratis, untuk mendapatkan gambaran awal dengan cepat dan bisa diulang.

Project ini juga dibuat sebagai latihan alur kerja geospasial dengan Python: membaca raster, mengolah data vektor, menangani sistem koordinat, dan menyajikan hasil di peta interaktif.

## Metodologi

1. **Baca ortofoto** (GeoTIFF): sistem koordinat (CRS), resolusi dalam meter per piksel, dan batas area. Resolusi dikoreksi untuk distorsi Web Mercator (EPSG:3857).
2. **Tentukan area analisis.** Jika ada file AOI (*area of interest*, poligon batas studi), area itu dipakai. Jika tidak ada, dipakai area ortofoto yang benar-benar berisi citra (bukan sekadar kotak pembatas).
3. **Unduh denah bangunan** dari [Overture Maps](https://overturemaps.org/) lewat DuckDB. Query memakai filter kotak batas langsung ke file Parquet di cloud, jadi hanya bagian yang relevan yang diunduh.
4. **Potong (clip) ke area analisis** dan **proyeksikan ke UTM** yang sesuai (zona dideteksi otomatis dari lokasi), supaya luas dihitung dalam meter persegi dengan akurat. Bangunan yang terpotong tepi diberi tanda `is_edge`, dan serpihan yang sangat kecil dibuang.
5. **Hitung statistik**: jumlah bangunan, total luas, serta luas minimum, median, dan maksimum.
6. **Buat peta interaktif** (Folium): ortofoto yang sudah diperkecil sebagai lapisan dasar, lengkap dengan denah bangunan, batas AOI, dan luas setiap bangunan saat diarahkan kursor.

### Contoh hasil

Pada satu area uji seluas sekitar 16,4 hektare (AOI), dengan ortofoto resolusi 7,4 cm per piksel:

| Ukuran | Nilai |
|---|---|
| Bangunan di dalam AOI | 117 |
| Total luas denah | 56.330 m² |
| Luas median per bangunan | 76 m² |
| Bangunan terbesar | 4.758 m² |

Angka ini luas denah bangunan, **bukan** luas atap yang bisa dipasangi panel (lihat disclaimer).

## Instalasi (Windows)

Diuji di Python 3.13 (Windows 11). Butuh koneksi internet (untuk mengunduh denah bangunan).

```powershell
git clone https://github.com/irwanrudy/solar-rooftop-drone.git
cd solar-rooftop-drone

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Cara menjalankan

1. Siapkan data (folder `data/` tidak ikut di repo):
   - `data/orto/<nama>.tif`: ortofoto RGB berformat GeoTIFF.
   - `data/aoi/<nama>.shp`: poligon batas area studi (opsional).
2. Sesuaikan nama file di `config.yaml`.
3. Jalankan:

```powershell
python src/footprints.py
```

Hasil ada di folder `output/`:

| File | Isi |
|---|---|
| `buildings.geojson` | Denah bangunan hasil clip, lengkap dengan `area_m2` |
| `buildings_summary.csv` | Jumlah bangunan, total luas, min/median/max |
| `map.html` | Peta interaktif, bisa dibuka langsung di browser |

### Pengaturan (`config.yaml`)

| Kunci | Fungsi |
|---|---|
| `input.ortho` | Path ortofoto |
| `input.aoi` | Path AOI. Kosongkan untuk memakai area data valid ortofoto |
| `input.clip_to_valid_data` | Jika tanpa AOI: potong ke area ber-citra, bukan kotak pembatas |
| `output.*` | Folder dan nama file hasil |
| `map.overlay_max_px` | Ukuran sisi terpanjang gambar ortofoto di peta (makin kecil, makin ringan) |
| `overture.release` | `latest` atau versi tertentu, mis. `2026-09-23.1` |
| `overture.min_area_m2` | Buang serpihan hasil clip di bawah luas ini |
| `overture.min_buildings_warn` | Tampilkan peringatan jika bangunan lebih sedikit dari ini |

## Struktur folder

```
solar-rooftop-drone/
├── src/footprints.py   # script utama
├── config.yaml         # semua path dan parameter
├── requirements.txt
├── data/               # input (tidak di-commit)
├── output/             # hasil (tidak di-commit)
└── notebooks/
```

## Keterbatasan

- Tanpa DSM, semua atap dianggap datar dan menghadap langit; tidak ada analisis bayangan.
- Hasil bergantung pada kualitas dan kelengkapan data Overture di lokasi studi.
- Posisi denah bisa bergeser relatif terhadap ortofoto (lihat disclaimer). Belum ada koreksi otomatis.
- Ortofoto diasumsikan RGB. Piksel hitam murni dianggap "tidak ada data".
- Baru diuji pada satu area studi.

## Roadmap

- [x] **v0.1**: denah bangunan Overture, clip ke AOI, luas, peta interaktif.
- [ ] **v0.2**: luas efektif dengan faktor pemanfaatan, lalu kWp dan kWh per tahun. Parameter diatur di `config.yaml`.
- [ ] **v0.3**: deteksi atap sendiri dari ortofoto memakai SAM ([segment-geospatial](https://github.com/opengeos/segment-geospatial)), lalu dibandingkan dengan Overture.
- [ ] **v0.4**: analisis kemiringan (slope) dan arah (aspect) atap jika DSM tersedia, misalnya dari WebODM.

## Sumber data dan atribusi

- Denah bangunan: [Overture Maps Foundation](https://overturemaps.org/), tema *buildings*. Data ini memuat kontribusi OpenStreetMap dan dilisensikan di bawah [ODbL](https://opendatacommons.org/licenses/odbl/). Cek ketentuan lisensi sebelum memakai ulang hasilnya.
- Peta dasar pada `map.html`: © kontributor [OpenStreetMap](https://www.openstreetmap.org/copyright).
- Ortofoto dan AOI adalah data milik pembuat project dan tidak disertakan dalam repo.
