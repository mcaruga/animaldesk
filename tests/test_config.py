import json

from animaldesk import config as cfg_mod
from animaldesk.config import Config


def test_salva_e_ricarica(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "config_dir", lambda: tmp_path)
    c = Config()
    c.size = 200
    c.speed = 1.8
    c.stats["fame"] = 42.0
    c.save()
    assert json.loads((tmp_path / "config.json").read_text())["size"] == 200
    again = Config.load()
    assert again.size == 200 and again.speed == 1.8 and again.stats["fame"] == 42.0


def test_valori_fuori_scala_vengono_corretti(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "config_dir", lambda: tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"size": 9999, "speed": 99, "stats": {"boh": 1}}))
    c = Config.load()
    assert c.size == 400 and c.speed == 3.0
    assert set(c.stats) == {"energia", "fame", "felicita"}


def test_file_rotto_non_fa_crashare(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "config_dir", lambda: tmp_path)
    (tmp_path / "config.json").write_text("{non json")
    assert Config.load().size == Config().size
