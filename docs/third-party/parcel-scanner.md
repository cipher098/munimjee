# Parcel barcode decoder provenance

The native parcel scanner reuses the existing Parcel Desk barcode result/carrier logic and the installed `zxing-wasm` 3.1.5 reader. No remote CDN/module loader is used. `parcel_barcode_reader.js` is an esbuild browser ESM bundle of the isolated copy's `src/label-barcode.js`, with the WASM path explicitly set to `/static/parcel_zxing_reader.wasm`. The bundled WASM hash matches the installed 3.1.5 reader artifact. The original tracker project and its dependency files are read only.

`backend/static/parcel_scanner_LICENSE.txt` retains MIT text and Apache-2.0 text/attribution. The generated bundle carries a notice pointing to that file. Upstream: https://github.com/Sec-ant/zxing-wasm and https://github.com/zxing-cpp/zxing-cpp. Browser camera frames are decoded locally; physical camera acceptance remains separate from synthetic-frame tests.
