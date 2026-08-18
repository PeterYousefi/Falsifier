"""
Probe: What is TLS secondary_depth at the dominant EB period?
Reads full TLS result from 1–10 days search.
Run as: .venv/bin/python scripts/_probe_eb_secondary.py
"""
import multiprocessing
import time
import numpy as np
from astropy.io import fits
from wotan import flatten

def main():
    from transitleastsquares import transitleastsquares as TLS

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

    n_threads = multiprocessing.cpu_count()
    t0 = time.monotonic()
    model = TLS(t, flat_f)
    res = model.power(period_min=1.0, period_max=10.0,
                      use_threads=n_threads, show_progress_bar=False)
    elapsed = time.monotonic() - t0
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"period={res.period:.5f}d, depth={1-res.depth:.5f} ({(1-res.depth)*1e6:.0f} ppm)")
    print(f"odd_even_mismatch={res.odd_even_mismatch:.4f}")
    print(f"snr={res.snr:.2f}")
    
    # Print all scalar attrs
    print("\nAll TLS scalars:")
    for attr in sorted(dir(res)):
        if attr.startswith('_'):
            continue
        val = getattr(res, attr, None)
        if callable(val):
            continue
        if isinstance(val, (float, int, str, bool)):
            print(f"  {attr!r}: {val}")
        elif hasattr(val, 'ndim') and val.ndim == 0:
            print(f"  {attr!r}: {float(val)}")

if __name__ == "__main__":
    main()
