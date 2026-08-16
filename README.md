# Zombee Product Manager Desktop

A Windows companion app for the Zombee Product Manager WordPress plugin.
Manage simple and variable WooCommerce products locally with an easier
GUI than the WooCommerce admin, then export a CSV in exactly the format the
plugin expects (and import one back in for editing).

## Status

Full MVP built and tested (55 tests passing, including a headless end-to-end
smoke test that exercises the real GUI: add both product types, edit,
delete, export CSV with the image-folder confirmation flow, wipe the DB,
re-import, verify nothing was lost).

- Product list with search, add/edit/delete
- Simple product form: name, descriptions, categories, tags, price/sale
  price/stock, main image + gallery, attributes, custom fields
- Variable product form: same, plus an attribute-driven variation grid that
  auto-generates combinations and smart-merges on regenerate (keeps
  existing variation data, only asks before removing stale combinations)
- Image compression (WebP/JPEG, configurable quality/size), SKU-based
  renaming, flat upload-images folder that's cleared-and-rebuilt per export
  (with confirmation)
- CSV import/export, byte-for-byte compatible with the plugin's format
- Settings (output folder, compression, language) persisted between runs
- PyInstaller build spec + GitHub Actions workflow to build the .exe

Not yet built: application icon, in-app image preview polish, a proper
CSV-import warnings dialog UI (currently a plain message box).

## Project layout

```
app/
  models.py         Product / Variation / Attribute / CustomField data classes
  db.py             Local SQLite storage (source of truth for the GUI)
  csv_io.py         Import/export matching the plugin's exact CSV format
  image_manager.py  Compression, SKU-based renaming, flat upload-folder export
  settings.py       Persisted app settings (output folder, compression, language)
  i18n.py           Locale loader (English only for now, ready for more)
  locales/en.json   UI strings
  ui/               PySide6 windows/widgets
tests/              pytest suite (55 tests, all passing)
main.py             Application entry point
build.spec          PyInstaller build configuration
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

## Design notes

- **Local-first, no site credentials.** This app never talks to your
  WooCommerce site directly. It's a local editor that speaks the plugin's
  CSV format -- you export a CSV, upload images to the Media Library
  manually, then import the CSV through the plugin's admin page.
- **Images**: originals are never modified. Compression/resizing/renaming
  happens fresh at export time into a single flat folder (no subfolders),
  cleared and repopulated with only the current export's images. The app
  will always ask before clearing that folder.
- **CSV compatibility**: `csv_io.py`'s column order and behavior must stay
  in lockstep with the plugin's `includes/class-vpci-exporter.php` and
  `includes/class-vpci-csv-parser.php`. If either side changes the format,
  update both together.
