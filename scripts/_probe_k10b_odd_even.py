"""
Probe: TLS odd_even_mismatch for Kepler-10b golden data.
"""
import multiprocessing
import numpy as np
from astropy.io import fits
from wotan import flatten

def main():
    from transitleastsquares import transitleastsquares as TLS

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

    print(f"Kepler-10b:")
    print(f"  period={res.period:.6f}d")
    print(f"  SDE={res.SDE:.2f}")
    print(f"  odd_even_mismatch={res.odd_even_mismatch:.6f}")
    print(f"  depth={(1-res.depth)*1e6:.0f} ppm")
    dm = res.depth_mean
    do_ = res.depth_mean_odd
    de_ = res.depth_mean_even
    print(f"  depth_mean={(1-dm[0])*1e6:.0f} ppm ± {dm[1]*1e6:.0f} ppm")
    print(f"  depth_odd={(1-do_[0])*1e6:.0f} ppm ± {do_[1]*1e6:.0f} ppm")
    print(f"  depth_even={(1-de_[0])*1e6:.0f} ppm ± {de_[1]*1e6:.0f} ppm")

if __name__ == "__main__":
    main()
