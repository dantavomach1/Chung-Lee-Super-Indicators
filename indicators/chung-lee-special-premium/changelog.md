# Changelog

## 2026-05-28

- `2026-05-28-retain-cleared-breakout-zones`: Added a master Keep Cleared Breakout Zones option plus per-timeframe retain toggles, with one retained historical box per timeframe/side that freezes the last valid breakout-zone boundaries when cleared and resets when the source anchor rolls forward.
- `2026-05-28-break-zone-label-distance-fix`: Changed all Hourly, Four Hour, Daily, Weekly, and Monthly breakout points labels to measure the shaded zone height from the zone boundary prices instead of from live price, and updated the label text to `{points} pts till {timeframe} break`.

## 2026-05-27

- `2026-05-27-breakout-one-sided-candle-fill-fix`: Corrected Fill Between Candles breakout zones so upper fills use the candle high as the lower edge and shade upward only, while lower fills use the candle low as the upper edge and shade downward only.
- `2026-05-27-fix-breakout-fill-plot-limit`: Replaced the Breakout Zone Fill Between Candles plot/fill implementation with capped object-based box strips so the new mode does not add plot counts.
- `2026-05-27-chung-lee-breakout-fill-and-points-labels`: Added a three-option breakout zone display selector with the existing exact-anchor box behavior as the default, a floating-window box mode, and a new fill-between-candles mode.
- Added Points Till Break labels for active breakout zones with configurable offset bars, label text color, and label size.
- Mirrored the Sessions high/low boundary idea for the new fill-between-candles breakout shade mode while keeping rectangular boxes disabled in that mode.

## 2026-05-26

- Safe import of the untouched TradingView Pine Script code for `Chung Lee Special Premium`.
- No logic, plots, inputs, alerts, or visuals were intentionally changed during import.
