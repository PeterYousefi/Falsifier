"""
Probe script: check what TLS computes for odd_even_mismatch on the EB golden data.
Run as: .venv/bin/python scripts/_probe_eb_odd_even.py
"""
import multiprocessing
import time
import numpy as np
from astropy.io import fits
from wotan import flatten
from transitleastsquares import transitleastsquares as TLS

if __name__ == "__main__":
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
    print(f"Threads: {n_threads}")

    # First pass: full range
    t0 = time.monotonic()
    model = TLS(t, flat_f)
    res1 = model.power(period_min=1.0, period_max=10.0,
                       use_threads=n_threads, show_progress_bar=False)
    elapsed1 = time.monotonic() - t0
    depth_ppm = (1 - res1.depth) * 1e6
    print(f"1st pass ({elapsed1:.1f}s): period={res1.period:.5f}d SDE={res1.SDE:.2f} "
          f"odd_even={res1.odd_even_mismatch:.4f} depth={depth_ppm:.0f}ppm snr={res1.snr:.2f}")
    # Check secondary_depth attribute
    for attr in ['secondary_depth', 'secondary', 'secondary_eclipse_depth']:
        v = getattr(res1, attr, None)
        if v is not None:
            print(f"  {attr}={v}")
    
    # Also check odd/even transits manually at first detected period
    period = res1.period
    epoch = res1.T0
    print(f"\nManual odd/even depth check at period={period:.5f}d:")
    half_dur = res1.duration / 2 * 1.3
    print(f"  transit duration={res1.duration:.4f}d, half_dur_used={half_dur:.4f}d")
    
    # Phase fold
    phase = (t - epoch) % period
    phase[phase > period/2] -= period
    in_transit = np.abs(phase) < half_dur
    
    # Separate odd and even transits
    transit_number = np.floor((t - epoch) / period).astype(int)
    odd_in = in_transit & (transit_number % 2 == 1)
    even_in = in_transit & (transit_number % 2 == 0)
    
    print(f"  Odd transit cadences: {odd_in.sum()}")
    print(f"  Even transit cadences: {even_in.sum()}")
    
    if odd_in.sum() > 0:
        print(f"  Odd mean flux: {flat_f[odd_in].mean():.6f}, depth={(1-flat_f[odd_in].mean())*1e6:.0f} ppm")
    if even_in.sum() > 0:
        print(f"  Even mean flux: {flat_f[even_in].mean():.6f}, depth={(1-flat_f[even_in].mean())*1e6:.0f} ppm")
