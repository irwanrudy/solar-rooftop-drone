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
