# Catatan progres v0.3 (Task 7, belum selesai)

Status per 2026-10-21: Task 0-6 selesai dan di-commit; Task 7 setengah jalan.

## Sudah dikerjakan di Task 7

- `build_map` menerima `extra_layers` (di-commit).
- Run nyata `python src/detect_roofs.py` pada AOI berhasil: 722 dtk, vit_l di cuda, tanpa error.
  Catatan spike memperkirakan sekitar 5 menit; sisanya waktu CPU (pasca-proses mask, poligonisasi, dedupe) dan mode dipandu.

## Hasil run pertama (ambang filter awal, tentatif)

| Item | Nilai |
|---|---|
| Segmen mentah, luas, bentuk, kecerahan, vegetasi | 2093, 1826, 1765, 1765, 696 |
| Denah cocok / kurang cocok / hanya Overture | 27 / 35 / 55 |
| Segmen hanya SAM | 380 (median luas 50 m2) |
| Median IoU (yang cocok) | 0,585 |
| Denah berhasil pada mode dipandu | 117 |
| Pergeseran pusat median, `bias_ratio` | 2,02 m, 0,398 |

Peta: atap genting besar tertangkap baik; kandidat "hanya SAM" banyak berupa serpihan kecil, bidang miring atap yang terpisah, petak tanah/plaza, dan tajuk pohon.

## Temuan: luas SAM dalam ringkasan menyesatkan

Segmen SAM saling bertumpuk (atap dan bidang-bidangnya sama-sama lolos dedupe IoU 0,7).
Jumlah luas segmen 147.952 m2, luas gabungan (union) hanya 69.682 m2. Luas Overture 56.330 m2.
Selisih luas sebenarnya sekitar +24%, bukan +162,7% seperti tercetak.
Irisan union SAM x union Overture: 41.244 m2.

## Rencana lanjutan (menunggu keputusan pengguna)

1. `compare.comparison_summary`: hitung `luas_sam_m2` dari luas gabungan (+ tes).
2. Naikkan `sam.filters.min_area_m2` dari 10 ke 30 (membuang 125 dari 380 segmen hanya-SAM, 61 dari 316 yang terkait denah).
3. Simpan segmen mentah sebelum filter ke berkas agar penyetelan ambang tidak perlu menjalankan SAM ulang 12 menit.
4. Setel ambang lain lewat inspeksi peta bersama pengguna, catat nilai akhir dan alasannya (masuk README sebagai metodologi).
5. Task 8: README, notebook, peninjauan visual.

## Belum di-commit sengaja

- `docs/index.html` berubah karena `publish_copy` aktif saat run; di-commit di Task 8 setelah hasil final.
- `output/` di-ignore git; hasil run nyata bisa dibuat ulang.

## Update: run 2 (setelah perbaikan, `min_area_m2` 30, cache `--reuse`)

Tiga usulan dikerjakan (commit `40067df`): luas SAM memakai luas gabungan, `min_area_m2` 30, cache segmen mentah + `--reuse`.
Run penuh 891 dtk; `--reuse` 44 dtk dengan hasil identik.

| Item | Run 1 | Run 2 |
|---|---|---|
| Segmen mentah, luas, bentuk, kecerahan, vegetasi | 2093, 1826, 1765, 1765, 696 | 2093, 1374, 1327, 1327, 510 |
| Cocok / kurang cocok / hanya Overture | 27 / 35 / 55 | 24 / 31 / 62 |
| Hanya SAM | 380 | 255 |
| Median IoU | 0,585 | 0,598 |
| Luas SAM (gabungan) vs Overture | 147.952 (jumlah, menyesatkan) vs 56.330 m2 | 67.950 vs 56.330 m2 (+20,6%) |

Pergeseran pusat (2,02 m median, `bias_ratio` 0,398) dan 117 denah mode dipandu tidak berubah.

### Sensitivitas `max_exg` (uji offline pada cache)

ExG kandidat berdistribusi dua kelompok: atap sekitar 0 atau di bawahnya, vegetasi 0,25-0,37.
Menaikkan `max_exg` dari 0,05 ke 0,15 hanya menambah 9 segmen terkait denah dan 31 segmen tanpa denah (dari 354 dan 973).
Kesimpulan: 0,05 tetap, hasilnya tidak sensitif terhadap ambang ini.
Dari segmen yang menempel >=50% pada denah Overture (354), 72% lolos; sisanya berwarna hijau (kemungkinan tajuk pohon di atas denah).

## Sisa pekerjaan Task 7

- Pengguna menilai `output/map.html` (server lokal: `python -m http.server` di folder output) untuk 255 segmen hanya-SAM: apakah ambang `min_solidity` 0,75 dan `min_area_m2` 30 sudah wajar.
- Setelah ambang final: catat alasan di README (Task 8), commit `config.yaml` bila berubah.

## Temuan: mode dipandu cocok rendah dengan denah Overture

Pada 117 denah, SAM dipandu kotak menghasilkan mask untuk semuanya, tetapi kesesuaiannya rendah:
IoU terhadap denah kuantil 10/25/50/75/90 = 0,23 / 0,31 / 0,41 / 0,51 / 0,63.
IoU >= 0,5: 33 denah (28%); >= 0,7: 7 (6%); >= 0,8: 2 (2%). Skor SAM median 0,873 (SAM yakin, tetapi mask berbeda dari denah).

Penyebab yang mungkin (belum dibedakan, tidak ada data acuan):
- Denah Overture bergeser (pergeseran pusat median 2,02 m, rata-rata dy -1,48 m).
- SAM menangkap satu bidang atap limasan, bukan seluruh atap.
- Denah Overture kurang presisi (satu denah menutup beberapa atap).

Hasil dilaporkan sebagai kesesuaian antar-metode, bukan akurasi. Usulan: cek manual 20-30 bangunan untuk mendapat gambaran akurasi sungguhan (menunggu keputusan pengguna), lalu Task 8.
