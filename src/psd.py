#!/usr/bin/env python3

import os
from glob import glob
import sys
import argparse

import numpy as np
import pandas as pd
from pymc3.stats import hpd

import linechain as lc
import plot
import utils

def import_time(run, time_dir):
    '''
    Import and combine all psd.dat files in a single time directory 
    for many channels. Assumes file name format 'psd.dat.#' and 'psd.dat.##'.
    Returns a DataFrame with frequency increasing down the rows and 
    chain index increasing across the columns. The DataFrame is MultiIndexed,
    with indices (highest level to lowest) channel, time, frequency.

    Input
    -----
      time_dir : relative path to the time directory
    '''
    time = run.get_time(time_dir)
    # Sort so that (for example) psd.dat.2 is sorted before psd.dat.19
    psd_files = sorted(glob(os.path.join(time_dir, 'psd.dat.[0-9]'))) + \
        sorted(glob(os.path.join(time_dir, 'psd.dat.[0-9][0-9]')))
    # Import PSD files into DataFrame
    time_data = []
    for pf in psd_files:
        # Import data file
        psd = pd.read_csv(
            pf, sep=' ', usecols=range(run.channels.shape[0]+1), 
            header=None, index_col=0
        )
        # Add index column name
        psd.index.name = 'FREQ'
        # Round frequency index to 5 decimals to deal with floating point issues
        psd.index = np.around(psd.index, 5)
        # Add channel names
        psd.columns = pd.Series(run.channels, name='CHANNEL')
        # Add time level to index
        psd['TIME'] = time
        psd.set_index('TIME', append=True, inplace=True)
        # Concatenate columns vertically
        psd = psd.stack()
        time_data.append(psd)
    # Concatenate psd series horizontally
    time_data = pd.concat(time_data, axis=1, ignore_index=True)
    # Reorder and sort multiindex levels
    time_data = time_data.reorder_levels(['CHANNEL', 'TIME', 'FREQ']).sort_index()
    # Strip rows of 2s
    return time_data[time_data.iloc[:,0] < 2]

def summarize_psd(run, time_dir):
    '''
    Returns a DataFrame with the median and credible intervals for one time.
    Credible intervals are calculated using
    pymc3's highest posterior density (HPD) function, where alpha is the 
    desired probability of type I error (so, 1 - C.I.).
    Uses the same MultiIndex as import_time().
    
    Input
    -----
      time_dir : relative path to the time directory
    '''
    # Import time data
    time_data = import_time(run, time_dir)
    # Grab MultiIndex
    midx = time_data.index
    # Calculate HPDs
    time_data_np = time_data.to_numpy().T
    hpd_50 = hpd(time_data_np, alpha=0.5)
    hpd_90 = hpd(time_data_np, alpha=0.1)
    # Return summary DataFrame
    return pd.DataFrame({
        'MEDIAN'    : time_data.median(axis=1),
        'CI_50_LO'  : pd.Series(hpd_50[:,0], index=midx),
        'CI_50_HI'  : pd.Series(hpd_50[:,1], index=midx),
        'CI_90_LO'  : pd.Series(hpd_90[:,0], index=midx),
        'CI_90_HI'  : pd.Series(hpd_90[:,1], index=midx),
    }, index=midx)

def save_summary(run):
    '''
    Returns a multi-index DataFrame of PSD summaries across multiple times 
    from one run folder. The first index represents channel, the second GPS time
    and the third frequency. Inserts blank rows in place of time gaps.
    
    Input
    -----
      run : Run object
    '''
    # Set up progress indicator
    p = utils.Progress(run.time_dirs, f'Importing {run.name} psd files...')
    # Concatenate DataFrames of all times; takes a while
    summaries = []
    for i, d in enumerate(run.time_dirs):
        summaries.append(summarize_psd(run, d))
        # Update progress indicator
        p.update(i)

    summaries = pd.concat(summaries)

    # Check for time gaps and fill with NaN DataFrames
    #times = run.gps_times[:-1]
    #p = utils.Progress(times, 'Checking for time gaps...')
    #N = 0
    print('Checking for time gaps...')
    frequencies = summaries.index.unique(level='FREQ')
    midx = pd.MultiIndex.from_product(
        [run.channels, run.missing_times, frequencies],
        names=['CHANNEL', 'TIME', 'FREQ']
    )
    filler = pd.DataFrame(columns=summaries.columns, index=midx)
    summaries = summaries.append(filler).sort_index(level=[0, 1, 2])
    '''
    for i, gps_time in enumerate(times):
        diff = run.gps_times[i+1] - run.gps_times[i]
        if diff > run.dt + 1:
            # Number of new times to insert
            n = int(np.floor(diff / run.dt))
            N += n
            # List of missing times, with same time interval
            missing_times = [times[i] + run.dt * k for k in range(1, n + 1)]
            # Create new MultiIndex for empty DataFrame
            frequencies = summaries.index.unique(level='FREQ')
            midx = pd.MultiIndex.from_product(
                [run.channels, missing_times, frequencies],
                names=['CHANNEL', 'TIME', 'FREQ']
            )
            # Create empty DataFrame, append to summaries, and sort
            filler = pd.DataFrame(columns=summaries.columns, index=midx)
            summaries = summaries.append(filler).sort_index(level=[0, 1, 2])
        # Update progress indicator
        p.update(i)
    '''
    print(f'Filled {len(run.missing_times)} missing times with NaN.')
    
    # Output to file
    print(f'Writing to {run.psd_file}...')
    summaries.to_pickle(run.psd_file)
    return summaries

def get_exact_freq(summary, approx_freqs):
    '''
    Takes an approximate input frequency and returns the closest measured
    frequency in the data.
    '''
    gps_times = list(summary.index.unique(level='TIME'))
    freqs = np.array(summary.xs(gps_times[0]).index)
    freq_indices = list(np.round(
            approx_freqs / (np.max(freqs) - np.min(freqs)) * len(freqs)
    ).astype(int))
    return freqs[freq_indices]

def get_impacts(impacts_file):
    cols = ['DATE', 'GPS', 'P_MED', 'P_CI_LO', 'P_CI_HI', 'FACE', 'LOCAL', 
            'LAT_SC', 'LON_SC', 'LAT_SSE', 'LON_SSE', 'LPF_X', 'LPF_Y', 'LPF_Z']
    impacts = pd.read_csv(impacts_file, sep=' ', names=cols, na_values='-')
    return impacts

def main():
    # Argument parser
    parser = argparse.ArgumentParser(
        description='Generate PSD summaries and plots.'
    )
    parser.add_argument('runs', type=str, nargs='*', 
        help='run directory name (default: all folders in "data/" directory)'
    )
    parser.add_argument('--overwrite-all', dest='overwrite', action='store_true',
        help='re-generate summary files even if they already exist (default: \
              ask for each run)'
    )
    parser.add_argument('--keep-all', dest='keep', action='store_true',
        help='do not generate summary file if it already exists (default: ask \
              for each run)'
    )
    args = parser.parse_args()
    # Add all runs in data directory if none are specified
    if len(args.runs) == 0: 
        args.runs = glob(f'data{os.sep}*{os.sep}*{os.sep}')
    
    # Initialize run objects; skip missing directories
    runs = utils.init_runs(args.runs)
    
    # Import impacts file, if any
    impacts_file = 'impacts.dat'
    impacts = np.array([])
    if os.path.exists(impacts_file):
        impacts = get_impacts(impacts_file)
    
    for run in runs:
        print(f'\n-- {run.mode} {run.name} --')
        # Confirm to overwrite if summary already exists
        if args.keep: overwrite = False
        elif args.overwrite: overwrite = True
        elif os.path.exists(run.psd_file):
            over = input('Found psd.pkl for this run. Overwrite? (y/N) ')
            overwrite = True if over == 'y' else False
        else: overwrite = True

        # Import / generate summary PSD DataFrame
        if overwrite:
            run.psd_summary = save_summary(run)
        else:
            run.psd_summary = pd.read_pickle(run.psd_file)
        
        # Make plots
        df = run.psd_summary
        # Frequency slices: roughly logarithmic, low-frequency
        plot_frequencies = np.array([1e-3, 3e-3, 5e-3, 1e-2, 3e-2, 5e-2])
        # Time slices: get even spread of times
        n = 6
        indices = [int(i / (n-1) * len(run.gps_times)) for i in range(1,n-1)]
        slice_times = sorted([run.gps_times[0], run.gps_times[-1]] +
            [run.gps_times[i] for i in indices]
        )
        
        '''
        p = utils.Progress(run.channels, 'Plotting...')
        for i, channel in enumerate(run.channels):
            # Colormap
            cmap_file = os.path.join(run.plot_dir, f'colormap{i}.png')
            plot.save_colormaps(run, channel, cmap_file)
            # Frequency slices
            fslice_file = os.path.join(run.plot_dir, f'fslice{i}.png')
            plot.save_freq_slices([run], channel, plot_frequencies, 
                    impacts=impacts, plot_file=fslice_file)
            # Time slices
            tslice_file = os.path.join(run.plot_dir, f'tslice{i}.png')
            plot.save_time_slices(run, channel, slice_times, tslice_file)
            # Update progress
            p.update(i)
        '''
        
    p = utils.Progress(runs[0].channels, '\nPlotting run comparisons...')
    for i, channel in enumerate(runs[0].channels):
        plot.save_freq_slices(runs, channel, plot_frequencies, impacts=impacts,
                plot_file=f'out/multi_fslice{i}.png')
        p.update(i)
    
    print('Done!')

if __name__ == '__main__':
    main()

