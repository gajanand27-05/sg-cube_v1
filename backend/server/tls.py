"""Self-signed TLS for the phone camera page.

Phone browsers only expose getUserMedia to secure contexts. The Chrome
insecure-origin flag proved unreliable in practice (and rots when the LAN IP
rotates), so the phone endpoints are also served over HTTPS on a second port.
The phone shows a one-time "connection not private" interstitial — after
Advanced → Proceed, the page is a secure context and the camera works.

The cert lives in certs/ (git-ignored) and is regenerated whenever it is
missing, expired, or no longer lists the machine's current LAN IP in its SAN —
the IP rotates with the hotspot, so this check runs at every boot.
"""
import datetime
import ipaddress
import logging
from pathlib import Path

log = logging.getLogger(__name__)

CERT_DIR = Path(__file__).resolve().parents[2] / "certs"
CERT_FILE = CERT_DIR / "sg_cube_cert.pem"
KEY_FILE = CERT_DIR / "sg_cube_key.pem"


def ensure_self_signed_cert(lan_ip: str | None) -> tuple[str, str] | None:
    """Return (cert_path, key_path), generating/rotating the pair if needed.
    Returns None if the cryptography package is unavailable."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        log.warning("cryptography not installed — phone HTTPS disabled")
        return None

    if CERT_FILE.exists() and KEY_FILE.exists() and _cert_still_valid(lan_ip):
        return str(CERT_FILE), str(KEY_FILE)

    log.info("Generating self-signed cert for phone HTTPS (lan_ip=%s)", lan_ip)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "SG Cube Onyx")])
    sans: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    if lan_ip:
        sans.append(x509.IPAddress(ipaddress.ip_address(lan_ip)))
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=730))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(key, hashes.SHA256())
    )
    CERT_DIR.mkdir(exist_ok=True)
    KEY_FILE.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(CERT_FILE), str(KEY_FILE)


def _cert_still_valid(lan_ip: str | None) -> bool:
    """Existing cert is usable iff unexpired AND lists the current LAN IP."""
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(CERT_FILE.read_bytes())
        now = datetime.datetime.now(datetime.timezone.utc)
        if now > cert.not_valid_after_utc - datetime.timedelta(days=7):
            return False
        if lan_ip:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            ips = {str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)}
            if lan_ip not in ips:
                return False
        return True
    except Exception:
        return False  # unreadable/garbled cert -> regenerate
