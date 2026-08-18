"""
Probe: K10b transit depth scatter vs EB scatter.
"""
import multiprocessing
import numpy as np
from astropy.io import fits
from wotan import flatten

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
    res = model.power(period_min=0.5, period_max=2.0,
                      use_threads=multiprocessing.cpu_count(), show_progress_bar=False)

    k10b_depths = (1 - np.array(res.transit_depths)) * 1e6
    k10b_depth = (1 - res.depth) * 1e6
    k10b_snr = res.snr
    k10b_scatter = np.std(k10b_depths)
    k10b_noise = k10b_depth / k10b_snr if k10b_snr > 0 else 1
    k10b_excess = k10b_scatter / k10b_noise
    
    print(f"Kepler-10b:")
    print(f"  period={res.period:.5f}d, SDE={res.SDE:.2f}, SNR={k10b_snr:.2f}")
    print(f"  depth={k10b_depth:.0f} ppm")
    print(f"  TLS odd_even_mismatch={res.odd_even_mismatch:.4f}")
    print(f"  Transit depths std: {k10b_scatter:.0f} ppm ({len(k10b_depths)} transits)")
    print(f"  Per-transit noise (depth/SNR): {k10b_noise:.0f} ppm")
    print(f"  Excess scatter metric: {k10b_excess:.2f}")
    print(f"  Transit depths (first 10): {[f'{d:.0f}' for d in k10b_depths[:10]]}")

if __name__ == "__main__":
    main()
