# Notes

## What It Measures

`Chung Lee Swing + Compression Stats` is a nonvisual TradingView indicator that scans the bars loaded on the active chart and summarizes completed swing legs, completed compression periods, and completed post-compression expansion windows in a compact table.

## How Swing Legs Are Measured

- A ZigZag-style swing engine tracks price from a confirmed pivot to the current extreme.
- A swing leg is only completed after price reverses by the selected threshold.
- The reversal threshold can use either an ATR multiple or a fixed-point amount.
- Completed up legs and down legs are stored separately.
- Each completed leg stores distance in points, distance as an ATR multiple when available, duration in bars, and approximate duration in minutes when the chart timeframe supports that estimate.

## How Compression Is Measured

- Compression is mechanical.
- The script looks at the rolling high-low range over the selected compression lookback.
- A compression state is active when that rolling range is less than or equal to ATR multiplied by the selected compression threshold for at least the minimum number of bars.
- Only completed compression periods are stored.
- Each completed compression sample stores duration in bars, approximate duration in minutes when available, range height in points, and range height as an ATR multiple when available.

## How Post-Compression Expansion Is Measured

- After a compression period ends, the script opens a simple post-compression window.
- During the next selected number of bars, it measures the maximum distance price expands above the compression high or below the compression low.
- The larger of the upside or downside expansion becomes the stored expansion value for that sample.
- Upside and downside sample direction counts are also tracked for the dashboard.

## What It Does Not Do

- This indicator is not predictive.
- It does not generate trade signals.
- It does not place orders, alerts, labels, boxes, lines, arrows, or chart shading.
- It only renders a statistics table.

## Known Limitations

- Only analyzes bars loaded on the active TradingView chart.
- Swing pivots are confirmed after reversal, so they are delayed.
- Compression is mechanical and depends on the selected inputs.
- Approximate minutes are only shown when the active timeframe supports a stable bar-to-minutes conversion.
- TradingView is required for final compile and runtime validation.
