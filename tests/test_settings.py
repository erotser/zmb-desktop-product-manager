from app.settings import AppSettings, SettingsStore


def test_load_creates_defaults_when_no_file_exists(tmp_path):
    store = SettingsStore(config_dir=tmp_path / "config")
    settings = store.load()
    assert settings.database_path
    assert settings.output_images_folder
    assert settings.compression_format == "webp"
    assert (tmp_path / "config" / "settings.json").exists()


def test_save_and_reload_round_trips(tmp_path):
    store = SettingsStore(config_dir=tmp_path / "config")
    settings = store.load()
    settings.compression_quality = 55
    settings.output_images_folder = str(tmp_path / "custom-output")
    store.save(settings)

    reloaded = store.load()
    assert reloaded.compression_quality == 55
    assert reloaded.output_images_folder == str(tmp_path / "custom-output")


def test_load_fills_in_missing_keys_from_an_older_settings_file(tmp_path):
    """If a future version adds a new setting, an old settings.json on disk
    shouldn't crash the loader -- missing keys should fall back to defaults."""
    import json
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.json").write_text(json.dumps({"compression_quality": 40}))

    store = SettingsStore(config_dir=config_dir)
    settings = store.load()
    assert settings.compression_quality == 40
    assert settings.compression_format == "webp"  # filled in from defaults
