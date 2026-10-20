"""xeRAbora LAN proxy listener selection regression tests."""
import importlib.util
from pathlib import Path

source = Path(__file__).resolve().parents[1] / "integrations" / "xerabora" / "lan_proxy.py"
spec = importlib.util.spec_from_file_location("lan_proxy", source)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

def test_follows_profile_switch_to_another_web_port():
    before = 'LISTEN 0 8 127.0.0.1:18280 0.0.0.0:* users:(("xerabora-linux-",pid=111,fd=4))'
    after = 'LISTEN 0 8 127.0.0.1:18281 0.0.0.0:* users:(("xerabora-linux-",pid=222,fd=4))'
    assert proxy.parse_xerabora_port(before) == 18280
    assert proxy.parse_xerabora_port(after) == 18281

def test_unrelated_listener_is_not_exposed():
    data = '\n'.join([
        'LISTEN 0 8 127.0.0.1:18280 0.0.0.0:* users:(("other-service",pid=123,fd=4))',
        'LISTEN 0 8 127.0.0.1:18281 0.0.0.0:* users:(("xerabora-linux-",pid=456,fd=5))',
    ])
    assert proxy.parse_xerabora_port(data) == 18281

def test_no_xerabora_listener_means_no_forwarding():
    data = 'LISTEN 0 8 127.0.0.1:18280 0.0.0.0:* users:(("other-service",pid=123,fd=4))'
    assert proxy.parse_xerabora_port(data) is None
