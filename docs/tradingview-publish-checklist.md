# TradingView Publish Checklist

- Confirm the correct `//@version` line is present.
- Confirm the correct `indicator()` or `strategy()` declaration is present.
- Confirm there are no unfinished placeholders.
- Confirm there are no accidental debug plots unless they are toggle-controlled.
- Confirm inputs are named clearly.
- Confirm visuals match expected behavior.
- Confirm alerts still exist if they existed before.
- Confirm `original.pine` remains untouched.
- Confirm `changelog.md` was updated.
- Confirm `source.pine` is the working file.
- Confirm the file in `published/` is ready for copy/paste into TradingView.
