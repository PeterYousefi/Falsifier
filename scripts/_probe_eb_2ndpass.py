"""
Probe: TLS result at 5.07 days (true EB period, doubled from half-period detection).
"""
import multiprocessing
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

    # Now mask the 2.54-day signal to simulate what run_search does after 1st detection
    period1 = 2.53880
    epoch1 = 261.5935
    dur1 = 0.09157
    half_dur1 = dur1 / 2 * 1.2  # with 20% margin

    phase1 = (t - epoch1) % period1
    phase1[phase1 > period1/2] -= period1
    in_transit1 = np.abs(phase1) < half_dur1

    flat_f2 = flat_f.copy()
    flat_f2[in_transit1] = 1.0
    print(f"Masked {in_transit1.sum()} in-transit cadences from first detection")

    model = TLS(t, flat_f2)
    res = model.power(period_min=1.0, period_max=10.0,
                      use_threads=multiprocessing.cpu_count(), show_progress_bar=False)

    print(f"2nd pass: period={res.period:.5f}d SDE={res.SDE:.2f}")
    print(f"  odd_even_mismatch={res.odd_even_mismatch:.4f}")
    depth_ppm = (1 - res.depth) * 1e6
    print(f"  depth={depth_ppm:.0f} ppm")
    dm = res.depth_mean
    do_ = res.depth_mean_odd
    de_ = res.depth_mean_even
    print(f"  depth_mean={1-dm[0]:.5f} ({(1-dm[0])*1e6:.0f} ppm) ± {dm[1]*1e6:.0f} ppm")
    print(f"  depth_odd={1-do_[0]:.5f} ({(1-do_[0])*1e6:.0f} ppm) ± {do_[1]*1e6:.0f} ppm")
    print(f"  depth_even={1-de_[0]:.5f} ({(1-de_[0])*1e6:.0f} ppm) ± {de_[1]*1e6:.0f} ppm")
    
    # transit depths
    td_ppm = (1 - np.array(res.transit_depths)) * 1e6
    print(f"  transit depths (first 10): {[f'{d:.0f}' for d in td_ppm[:10]]}")

if __name__ == "__main__":
    main()
