"""Self-signed cert lifecycle for phone HTTPS (backend/server/tls.py)."""
import ssl

import pytest

from backend.server import tls


@pytest.fixture()
def tmp_cert_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(tls, "CERT_DIR", tmp_path)
    monkeypatch.setattr(tls, "CERT_FILE", tmp_path / "cert.pem")
    monkeypatch.setattr(tls, "KEY_FILE", tmp_path / "key.pem")
    return tmp_path


def _san_ips(cert_path):
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    return {str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)}


def test_generates_cert_with_lan_ip_in_san(tmp_cert_paths):
    pair = tls.ensure_self_signed_cert("192.168.1.50")
    assert pair is not None
    cert_path, key_path = pair
    assert _san_ips(tls.CERT_FILE) >= {"192.168.1.50", "127.0.0.1"}
    # loadable by the ssl module — what uvicorn will do with it
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)


def test_reuses_valid_cert(tmp_cert_paths):
    tls.ensure_self_signed_cert("192.168.1.50")
    first = tls.CERT_FILE.read_bytes()
    tls.ensure_self_signed_cert("192.168.1.50")
    assert tls.CERT_FILE.read_bytes() == first


def test_rotates_when_lan_ip_changes(tmp_cert_paths):
    tls.ensure_self_signed_cert("10.87.137.111")
    first = tls.CERT_FILE.read_bytes()
    tls.ensure_self_signed_cert("10.230.64.111")  # hotspot IP rotated
    assert tls.CERT_FILE.read_bytes() != first
    assert "10.230.64.111" in _san_ips(tls.CERT_FILE)


def test_garbled_cert_regenerated(tmp_cert_paths):
    tls.CERT_FILE.write_text("not a cert")
    tls.KEY_FILE.write_text("not a key")
    pair = tls.ensure_self_signed_cert("192.168.1.50")
    assert pair is not None
    assert "192.168.1.50" in _san_ips(tls.CERT_FILE)


def test_phone_url_prefers_https(monkeypatch):
    from backend.server.routes import phone_stream
    from backend.server.config import settings
    monkeypatch.setattr(phone_stream, "_lan_ip", lambda: "192.168.1.50")
    monkeypatch.setattr(settings, "enable_phone_tls", True)
    assert phone_stream._phone_url() == f"https://192.168.1.50:{settings.phone_tls_port}/phone"
    monkeypatch.setattr(settings, "enable_phone_tls", False)
    assert phone_stream._phone_url() == f"http://192.168.1.50:{settings.app_port}/phone"
