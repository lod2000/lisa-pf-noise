import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors

import psd
import utils
    
def shifted_cmap(cmap, start=0, midpoint=0.5, stop=1.0, name='shiftedcmap'):
    '''
    Function to offset the "center" of a colormap. Useful for
    data with a negative min and positive max and you want the
    middle of the colormap's dynamic range to be at zero.

    Input
    -----
      cmap : The matplotlib colormap to be altered
      start : Offset from lowest point in the colormap's range.
          Defaults to 0.0 (no lower offset). Should be between
          0.0 and `midpoint`.
      midpoint : The new center of the colormap. Defaults to 
          0.5 (no shift). Should be between 0.0 and 1.0. In
          general, this should be  1 - vmax / (vmax + abs(vmin))
          For example if your data range from -15.0 to +5.0 and
          you want the center of the colormap at 0.0, `midpoint`
          should be set to  1 - 5/(5 + 15)) or 0.75
      stop : Offset from highest point in the colormap's range.
          Defaults to 1.0 (no upper offset). Should be between
          `midpoint` and 1.0.
    '''
    cdict = {
        'red': [],
        'green': [],
        'blue': [],
        'alpha': []
    }
    # regular index to compute the colors
    reg_index = np.linspace(start, stop, 257)
    # shifted index to match the data
    shift_index = np.hstack([
        np.linspace(0.0, midpoint, 128, endpoint=False), 
        np.linspace(midpoint, 1.0, 129, endpoint=True)
    ])
    for ri, si in zip(reg_index, shift_index):
        r, g, b, a = cmap(ri)
        cdict['red'].append((si, r, r))
        cdict['green'].append((si, g, g))
        cdict['blue'].append((si, b, b))
        cdict['alpha'].append((si, a, a))
    newcmap = matplotlib.colors.LinearSegmentedColormap(name, cdict)
    plt.register_cmap(cmap=newcmap)
    return newcmap

def colormap(fig, ax, run, psd, cmap, vlims=None, cbar_label=None, center=None):
    '''
    Function to plot the colormap of a PSD with frequency on the y-axis and
    time on the x-axis.
    
    Input
    -----
      fig, ax : The figure and axes of the plot
      psd : The PSD, an unstacked DataFrame
      run : Run object
      cmap : The unaltered color map to use
      vlims : A tuple of the color scale limits
      cbar_label : Color bar label
      center : The center value of a diverging colormap
    '''
    # Change columns from GPS time to days elapsed from start of run
    psd.columns = pd.Series(run.gps2day(psd.columns), name='TIME')
    # Median frequency step
    df = np.median(np.diff(psd.index))
    # Auto colormap scale
    if not vlims:
        med = psd.median(axis=1).median()
        std = psd.std(axis=1).median()
        vlims = (med - 2 * std, med + 2 * std)
    # Shift colormap to place 0 in the center if needed
    if center:
        cmap = shifted_cmap(
            cmap, 
            midpoint=(center-vlims[0])/(vlims[1]-vlims[0]), 
            name='shifted colormap'
        )
    im = ax.pcolormesh(
        list(psd.columns) + [psd.columns[-1] + run.dt / (60*60*24)],
        list(psd.index) + [psd.index[-1] + df],
        psd,
        cmap=cmap,
        vmin=vlims[0],
        vmax=vlims[1]
    )
    # Vertical scale
    ax.set_yscale('log')
    ax.set_ylim(bottom=1e-3, top=1.)
    # Axis labels
    ax.set_xlabel(f'Days elapsed since {run.start_date} UTC')
    ax.set_ylabel('Frequency (Hz)')
    # Add and label colorbar
    cbar = fig.colorbar(im, ax=ax)
    if cbar_label:
        cbar.set_label(cbar_label, labelpad=15, rotation=270)

def all_psds(fig, ax, time_dir, channel, xlim=None, ylim=None):
    '''
    Plots all PSD samples in a single time directory for one channel
    '''
    df = psd.import_time(time_dir).loc[channel]
    summary = psd.summarize_psd(time_dir).loc[channel]
    freqs = df.index.get_level_values('FREQ')
    for i in range(100):
        ax.scatter(freqs, df[i], marker='.', color='b')
    if xlim: ax.set_xlim(xlim)
    else: ax.set_xlim(auto=True)
    if ylim: ax.set_ylim(ylim)
    else: ax.set_ylim(auto=True)
    ax.set_xscale('log')
    ax.set_yscale('log')
    
def freq_slice(fig, ax, run, freq, summary, color='b', ylim=None):
    '''
    Plots time vs PSD at a specific frequency.

    Input
    -----
      fig, ax : the figure and axes of the plot
      freq : the approximate frequency along which to slice
      run : Run object
      summary : the summary DataFrame
      color : the color of the plot, optional
      ylim : tuple of y axis bounds, optional
    '''
    # Get the index of the nearest frequency to the one requested
    freq = psd.get_exact_freq(summary, freq)
    # Slice along that frequency
    fslice = summary.xs(freq, level='FREQ')
    # Date stuff
    days_elapsed = run.gps2day(fslice.index)
    # Plot 50% credible interval
    ax.fill_between(days_elapsed,
        fslice['CI_50_LO'],
        fslice['CI_50_HI'], 
        color=color,
        alpha=0.5,
        label='50% credible interval')
    # Plot 90% credible interval
    ax.fill_between(days_elapsed,
        fslice['CI_90_LO'],
        fslice['CI_90_HI'],
        color=color,
        alpha=0.2,
        label='90% credible interval')
    # Plot median
    ax.plot(days_elapsed, fslice['MEDIAN'], label='Median PSD', color=color)
    # Vertical scale
    if ylim: 
        ax.set_ylim(ylim)
    else:
        med = fslice['MEDIAN'].median()
        std = fslice['MEDIAN'].std()
        hi = fslice['CI_90_HI'].quantile(0.95) - med
        lo = med - fslice['CI_90_LO'].quantile(0.05)
        ax.set_ylim((max(med - 2 * lo, 0), med + 2 * hi))
    ax.title.set_text(str(np.around(freq*1000, 3)) + ' mHz')

def time_slice(fig, ax, time, summary, color='b', ylim=None, logpsd=False):
    '''
    Plots frequency vs PSD at a specific time.

    Input
    -----
      fig, ax : the figure and axes of the plot
      time : the exact gps time along which to slice
      summary : the summary DataFrame
      color : the color of the plot, optional
      ylim : tuple of y axis bounds, optional
      lobpsd : if true, plots psd on a log scale
    '''
    # Get time slice
    tslice = summary.xs(time)
    # Plot 50% credible interval
    ax.fill_between(tslice.index, 
        tslice['CI_50_LO'], 
        tslice['CI_50_HI'],
        color=color, 
        alpha=0.5,
        label='50% credible interval')
    # Plot 90% credible interval
    ax.fill_between(tslice.index, 
        tslice['CI_90_LO'], 
        tslice['CI_90_HI'],
        color=color, 
        alpha=0.1,
        label='90% credible interval')
    # Plot median
    ax.plot(tslice.index, tslice['MEDIAN'], 
        label='Median PSD', 
        color=color)
    ax.set_xscale('log')
    if ylim: ax.set_ylim(ylim)
    if logpsd: ax.set_yscale('log')
    ax.title.set_text(str(time))

def save_colormaps(run, channel, plot_file, show=False):
    df = run.psd_summary.loc[channel]
    # Unstack psd, removing all columns except the median
    unstacked = df['MEDIAN'].unstack(level=0)
    # Find median across all times
    median = unstacked.median(axis=1)
    # Set up figure
    fig, axs = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(f'Colormap of {run.mode} {run.name} channel {channel} PSD over time')
    # Subplots
    axs[0].title.set_text('Absolute difference from median PSD')
    colormap(fig, axs[0], run,
        unstacked.sub(median, axis=0), 
        cmap=cm.get_cmap('coolwarm'),
        center=0.0
    )
    axs[1].title.set_text('Fractional difference from median PSD')
    colormap(fig, axs[1], run,
        abs(unstacked.sub(median, axis=0)).div(median, axis=0),
        cmap='PuRd',
        vlims=(0,1)
    )
    plt.savefig(plot_file)
    if show: plt.show()
    else: plt.close()

def save_freq_slices(run, channel, plot_file, show=False,
        frequencies=[1e-3, 3e-3, 5e-3, 1e-2, 3e-2, 5e-2]):
    # Automatically create grid of axes
    nrows = int(np.floor(len(frequencies) ** 0.5))
    ncols = int(np.ceil(1. * len(frequencies) / nrows))
    fig = plt.figure(figsize=(4 * ncols, 4 * nrows))
    fig.suptitle(f'Selected frequencies for {run.mode} {run.name} channel {channel} PSDs')
    df = run.psd_summary.loc[channel]
    # Subplots
    for i, freq in enumerate(frequencies):
        ax = fig.add_subplot(nrows, ncols, i+1)
        freq_slice(fig, ax, run, frequencies[i], df)
        # Vertical axis label on first plot in each row
        if i % ncols == 0:
            ax.set_ylabel('PSD')
        # Horizontal axis label on bottom plot in each column
        if i >= len(frequencies) - ncols:
            ax.set_xlabel('Days elapsed since ' + str(run.start_date) + ' UTC')
    # Legend
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels)
    fig.tight_layout(w_pad=-1.0, rect=[0, 0, 1, 0.92])
    plt.savefig(plot_file)
    if show: plt.show()
    else: plt.close()

def save_time_slices(run, channel, times, plot_file=None, show=False,
        time_format='gps', exact=True, logpsd=True):
    # Convert given times to gps if necessary
    if time_format == 'day': times = run.day2gps(times)
    # Find exact times if necessary
    if not exact: times = run.get_exact_gps(times)
    # Automatically create grid of axes
    nrows = int(np.floor(float(len(times)) ** 0.5))
    ncols = int(np.ceil(1. * len(times) / nrows))
    fig = plt.figure(figsize=(4 * ncols, 4 * nrows))
    fig.suptitle(f'Selected times for {run.mode} {run.name} channel {channel} PSDs')
    df = run.psd_summary.loc[channel]
    # Subplots
    for i, time in enumerate(times):
        ax = fig.add_subplot(nrows, ncols, i+1)
        time_slice(fig, ax, times[i], df, logpsd=logpsd)
        # Axis title
        ax.title.set_text(f'PSD at GPS time {time}')
        # Vertical axis label on first plot in each row
        if i % ncols == 0:
            ax.set_ylabel('PSD')
        # Horizontal axis label on bottom plot in each column
        if i >= len(times) - ncols:
            ax.set_xlabel('Frequency (Hz)')
    # Legend
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    if plot_file: plt.savefig(plot_file)
    if show: plt.show()
    else: plt.close()

def linechain_scatter(run, channel, param, plot_file=None, show=False):
    df = run.lc_summary.loc[channel, :, :, param]
    # 90% error bars
    plt.errorbar(run.gps2day(df.index.get_level_values('TIME')), 
        df['MEDIAN'], 
        yerr=([df['MEDIAN'] - df['CI_90_LO'], df['CI_90_HI'] - df['MEDIAN']]), 
        ls='', marker='', capsize=3, alpha=0.2, ecolor='b'
    )
    # Median and 50% error bars
    plt.errorbar(run.gps2day(df.index.get_level_values('TIME')), 
        df['MEDIAN'], 
        yerr=([df['MEDIAN'] - df['CI_50_LO'], df['CI_50_HI'] - df['MEDIAN']]), 
        ls='', marker='.', capsize=5, ecolor='b'
    )
    plt.xlabel(f'Days elapsed since {run.start_date} UTC')
    plt.ylabel(param)
    plt.yscale('log')
    plt.title(f'{run.mode} {run.name} channel {channel} spectral line {param} over time')
    if plot_file:
        plt.savefig(plot_file)
    if show: plt.show()
    else: plt.close()

def linecounts_cmap(run, channel, plot_file=None, show=False):
    ''' Plots a colormap of the spectral line counts over time '''
    counts = run.linecounts.loc[channel]
    # Change GPS times to days elapsed
    counts.index = pd.Series(run.gps2day(counts.index), name='TIME')
    # Convert counts to fraction of total
    counts = counts / sum(counts.iloc[0].dropna())
    # Plot
    fig, ax = plt.subplots(1, 1)
    ax.title.set_text(
        f'Line model frequency over time for {run.mode} {run.name} channel {channel}'
    )
    im = ax.pcolormesh(
        list(counts.index) + [counts.index[-1] + run.dt / (60*60*24)],
        list(counts.columns) + [int(counts.columns[-1]) + 1],
        counts.to_numpy().T,
        cmap='PuRd',
        vmax=0.5
    )
    # Axis labels
    ax.set_xlabel(f'Days elapsed since {run.start_date} UTC')
    ax.set_ylabel('Modeled no. spectral lines')
    # Put the major ticks at the middle of each cell
    ax.set_yticks(counts.columns + 0.5, minor=False)
    ax.set_yticklabels(counts.columns)
    # Add and label colorbar
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label('Line model relative frequency', labelpad=15, rotation=270)
    # Save figure and close
    if plot_file: plt.savefig(plot_file)
    if show: plt.show()
    else: plt.close()

'''
DANGER - UNDER CONSTRUCTION
'''

def linecounts_combined(runs, channel, plot_file=None, show=False):
    ''' Plots a colormap of the spectral line counts over time for many runs '''
    # Sort runs by start date
    runs.sort(key=lambda run: run.start_date)
    # Fill missing times, if the gap between runs isn't too big
    for i in range(len(runs) - 1):
        diff = runs[i+1].gps_times[0] - runs[i].gps_times[-1]
        # If the gap is less than 3 days
        if diff < 3 * (24*60*60):
            all_times = runs[i].gps_times + runs[i+1].gps_times
            missing_times = runs[i].get_missing_times(all_times)
            missing_midx = pd.MultiIndex.from_product(
                    [run[i].channels, missing_times], names=['CHANNEL', 'TIME']
            )
            missing_df = pd.DataFrame(columns=run[i].linecounts.columns,
                    index=missing_midx
            )
            runs[i].linecounts = pd.concat(
                    [runs[i].linecounts, missing_df]
            ).sort_index(level=[0,1])
    counts = pd.concat([run.linecounts for run in runs]).loc[channel]
    print(counts[counts.isna()])
    # Change GPS times to days elapsed
    counts.index = pd.Series(runs[0].gps2day(counts.index), name='TIME')
    # Convert counts to fraction of total
    counts = counts / sum(counts.iloc[0].dropna())
    # Plot
    fig, ax = plt.subplots(1, 1)
    ax.title.set_text(
        f'Line model frequency over time for all runs, channel {channel}'
    )
    im = ax.pcolormesh(
        list(counts.index) + [counts.index[-1] + runs[0].dt / (60*60*24)],
        list(counts.columns) + [int(counts.columns[-1]) + 1],
        counts.to_numpy().T,
        cmap='PuRd',
        vmax=0.5
    )
    # Axis labels
    ax.set_xlabel(f'Days elapsed since {runs[0].start_date} UTC')
    ax.set_ylabel('Modeled no. spectral lines')
    # Put the major ticks at the middle of each cell
    ax.set_yticks(counts.columns + 0.5, minor=False)
    ax.set_yticklabels(counts.columns)
    # Add and label colorbar
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label('Line model relative frequency', labelpad=15, rotation=270)
    # Save figure and close
    if plot_file: plt.savefig(plot_file)
    if show: plt.show()
    else: plt.close()

