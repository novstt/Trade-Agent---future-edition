# Project overview

Trade Agent is a local-only Windows 11 desktop program. A selected window is the only image source. The flow is `WindowSelection → CaptureProvider → RegionDetector / OcrEngine → PriceRecognizer → MarketAnalyzer → ProfitEngine → UI / SQLite`.

The application has separate market and Sell Menu workflows. Market rows are used solely to form a ten-price snapshot; market images are never passed to the sticker detector.
