# Zombee Product Manager Desktop

Version: 0.3.4

A Windows companion app for the Zombee Product Manager WordPress plugin.
Manage simple and variable WooCommerce products locally with an easier
GUI than the WooCommerce admin, then either export a CSV in exactly the
format the plugin expects, or push a product straight to the live site
with one click.

## Status

109 tests passing (pytest-qt for GUI logic, plus real local HTTP servers
standing in for both image hosts and the WordPress site itself, rather
than mocking network calls -- see Design notes).

- Product list: search, add/edit/delete, click a row to preview it instantly
- Simple product form: name, descriptions, categories, tags, price/sale
  price/stock, main image + gallery, attributes, custom fields
- Variable product form: same, plus an attribute-driven variation grid that
  auto-generates combinations and smart-merges on regenerate (keeps
  existing variation data, only asks before removing stale combinations)
- Image compression (WebP/JPEG, configurable quality/size), SKU-based
  renaming, flat upload-images folder that's cleared-and-rebuilt per export
  (with confirmation)
- Download button to fetch an already-live image (from an imported CSV
  reference) locally for preview/editing
- CSV import/export, byte-for-byte compatible with the plugin's format,
  including the plugin's formula-injection escaping and its reversal
- **Save & Sync to Site**: saves locally, then pushes the product directly
  to your WooCommerce site via the plugin's REST API (see Design notes)
- Clear All Products, with a typed "DELETE" confirmation
- Factory Reset: wipes products, the saved site credential, and site
  connection settings together, with a typed "RESET" confirmation
- Current version always visible in the window title bar and Help > About
  -- no more guessing which build is actually running
- Global crash handler -- unexpected errors show a dialog and write a log
  file instead of silently vanishing (the packaged .exe has no console)
- Settings: output folder, compression, language, site connection
- App icon, PyInstaller build spec, GitHub Actions workflow to build the .exe

Not yet built: threaded/async sync (the UI briefly blocks during a sync
request), an "unsaved changes" guard when switching products mid-edit,
bulk sync (only one product at a time currently), direct media upload via
sync (images must already be live on the site -- see Design notes).

## Project layout

```
app/
  models.py             Product / Variation / Attribute / CustomField data classes
  db.py                 Local SQLite storage (source of truth for the GUI)
  csv_io.py             Import/export matching the plugin's exact CSV format
  image_manager.py      Compression, SKU-based renaming, flat upload-folder export
  image_downloader.py   Fetches a remote image URL locally for preview/editing
  site_sync.py          HTTP client for the plugin's REST API (Save & Sync to Site)
  credential_store.py   Stores the site Application Password via the OS keychain
  settings.py           Persisted app settings (output folder, compression, site, language)
  crash_handler.py      Global exception handler (dialog + log file, not a silent vanish)
  i18n.py                Locale loader (English only for now, ready for more)
  locales/en.json        UI strings
  ui/                     PySide6 windows/widgets
  assets/icon.ico         App icon
tests/                    pytest suite (98 tests, all passing)
main.py                   Application entry point
build.spec                 PyInstaller build configuration
.github/workflows/build-windows.yml   Builds the .exe on GitHub's Windows runners
```

## Development setup

```bash
pip install -r requirements.txt
pytest tests/ -v            # QT_QPA_PLATFORM=offscreen is needed on Linux/CI without a display
python main.py               # run the app (needs an actual display)
```

## Building the Windows .exe

**Recommended: GitHub Actions.** Push this repo to GitHub -- the included
workflow builds automatically on GitHub's free Windows runners. Download
`ZombeeProductManager.exe` from the workflow run's Artifacts once it
finishes. Nothing needs to be installed on your machine.

**Or locally, on a Windows PC:**
```
pip install -r requirements.txt
pyinstaller build.spec
```
The .exe appears in `dist/`.

The build is currently unsigned, so Windows SmartScreen will warn on first
run ("More info" -> "Run anyway"). See the project history/changelog for
the tradeoffs around code signing if that becomes worth revisiting.

## Design notes

- **Local-first by default, direct sync is opt-in.** The app's own
  database is always the source of truth -- CSV export/import remains the
  primary workflow and needs no credentials at all. "Save & Sync to Site"
  is a separate, explicit action that additionally pushes to your live
  site, only once a site connection is configured in Settings.
- **Sync authentication**: WordPress Application Passwords (core since WP
  5.6), entered in Settings and stored via the OS credential store
  (`keyring` -- Windows Credential Manager on Windows), never in the
  plaintext settings file. Revocable any time from the site's own
  wp-admin, independent of anything else on that account.
- **Sync reuses the plugin's CSV-import logic on the server side.** The
  desktop app doesn't talk to WooCommerce's generic REST API directly --
  it calls a small custom endpoint in the plugin that converts the
  request into the exact same data structure a CSV import produces, then
  runs the same import code. This guarantees a synced product behaves
  identically to a CSV-imported one (same validation, same attribute/
  category/tag handling, same security checks) rather than the two paths
  silently drifting apart over time.
- **Sync doesn't upload new media.** An image field is only included in a
  sync request if it already has a live URL (from a prior CSV import, or
  a locally-downloaded-then-still-referenced image) -- a brand new, never-
  uploaded local image is skipped with a warning, and still needs the CSV
  export + manual upload workflow. Direct media upload via sync is a
  natural next step, not yet built.
- **Images (local editing)**: originals are never modified. Compression/
  resizing/renaming happens fresh at export time into a single flat
  folder (no subfolders), cleared and repopulated with only the current
  export's images. The app will always ask before clearing that folder.
- **CSV compatibility**: `csv_io.py`'s column order and behavior must stay
  in lockstep with the plugin's `includes/class-vpci-exporter.php` and
  `includes/class-vpci-csv-parser.php`. If either side changes the format,
  update both together.
- **Testing philosophy**: prefer real I/O over mocks where practical --
  the test suite runs actual local HTTP servers (via Python's stdlib
  `http.server`) standing in for both remote image hosts and the
  WordPress site itself, and hits real public URLs for the image
  downloader tests (skipped automatically if no network is available).
  This catches real-world HTTP/JSON edge cases that mocking the transport
  layer would miss.
