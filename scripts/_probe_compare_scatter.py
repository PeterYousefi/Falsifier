"""
Compare transit depth scatter metric between EB and K10b.
"""
import multiprocessing
import numpy as np
from astropy.io import fits
from wotan import flatten

def excess_depth_scatter(results):
    """Compute depth scatter / (depth/SNR) from TLS results. Returns normalized excess."""
    td = np.array(results.transit_depths, dtype=float)
    depths_ppm = (1 - td) * 1e6
    # Remove NaNs
    depths_ppm = depths_ppm[np.isfinite(depths_ppm)]
    if len(depths_ppm) < 2:
        return 0.0
    scatter = np.std(depths_ppm)
    depth = (1 - float(results.depth)) * 1e6
    snr = float(results.snr)
    noise_per_transit = depth / snr if snr > 0 else 1.0
    return scatter / noise_per_transit if noise_per_transit > 0 else 0.0

def main():
    from transitleastsquares import transitleastsquares as TLS

    # --- Kepler-10b ---
    with fits.open('data/golden/kepler10_q3_long.fits') as hdul:
        t = hdul[1].data['TIME'].astype(np.float64)
        f = hdul[1].data['FLUX'].astype(np.float64)
        q = hdul[1].data['QUALITY'].astype(np.int32)
    mask = np.isfinite(t) & np.isfinite(f) & (q == 0)
    t, f = t[mask], f[mask]
    f /= np.median(f)
    flat_f, _ = flatten(t, f, method='biweight', window_length=0.75,
                        break_tolerance=0.5, edge_cutoff=0, return_trend=True, cval=5.0)
    flat_f = np.where(np.isfinite(flat_f), flat_f, 1.0)
    model = TLS(t, flat_f)
    res_k10b = model.power(period_min=0.5, period_max=2.0,
                           use_threads=multiprocessing.cpu_count(), show_progress_bar=False)
    
    ods_k10b = excess_depth_scatter(res_k10b)
    print(f"K10b: period={res_k10b.period:.5f}d SNR={res_k10b.snr:.1f} "
          f"odd_even={res_k10b.odd_even_mismatch:.3f} excess_scatter={ods_k10b:.2f}")
    
    # Transit depths for K10b (finite only)
    td_k10b = np.array(res_k10b.transit_depths, dtype=float)
    td_k10b_ppm = (1 - td_k10b[np.isfinite(td_k10b)]) * 1e6
    print(f"  K10b depths: mean={td_k10b_ppm.mean():.0f} std={td_k10b_ppm.std():.0f} N={len(td_k10b_ppm)}")

    # --- EB ---
    with fits.open('data/golden/kic6965293_q3_long.fits') as hdul:
        t = hdul[1].data['TIME'].astype(np.float64)
        f = hdul[1].data['FLUX'].astype(np.float64)
        q = hdul[1].data['QUALITY'].astype(np.int32)
    mask = np.isfinite(t) & np.isfinite(f) & (q == 0)
    t, f = t[mask], f[mask]
    f /= np.median(f)
    flat_f, _ = flatten(t, f, method='biweight', window_length=2.0,
                        break_tolerance=0.5, edge_cutoff=0, return_trend=True, cval=5.0)
    flat_f = np.where(np.isfinite(flat_f), flat_f, 1.0)
    model = TLS(t, flat_f)
    res_eb = model.power(period_min=1.0, period_max=10.0,
                         use_threads=multiprocessing.cpu_count(), show_progress_bar=False)
    
    ods_eb = excess_depth_scatter(res_eb)
    print(f"EB: period={res_eb.period:.5f}d SNR={res_eb.snr:.1f} "
          f"odd_even={res_eb.odd_even_mismatch:.3f} excess_scatter={ods_eb:.2f}")
    
    td_eb = np.array(res_eb.transit_depths, dtype=float)
    td_eb_ppm = (1 - td_eb[np.isfinite(td_eb)]) * 1e6
    print(f"  EB depths: mean={td_eb_ppm.mean():.0f} std={td_eb_ppm.std():.0f} N={len(td_eb_ppm)}")

if __name__ == "__main__":
    main()
