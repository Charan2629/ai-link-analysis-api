import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


class InvalidURLException(ValueError):
    """Raised when a provided URL is malformed, lacks required scheme, or is unreachable."""
    pass


class SSRFSecurityException(PermissionError):
    """Raised when a URL attempts to access private, loopback, or metadata network addresses."""
    pass


# Specific cloud metadata IP networks (AWS, GCP, Azure, DigitalOcean, etc.)
CLOUD_METADATA_NETWORKS = [
    ipaddress.ip_network("169.254.169.254/32"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fd00::/8"),
]

# Carrier-Grade NAT (RFC 6598)
CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def is_ip_restricted(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """
    Check if an IP address belongs to loopback, private, link-local,
    reserved, multicast, unspecified, or cloud metadata ranges.
    """
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True

    # Check Cloud Metadata IPs
    for net in CLOUD_METADATA_NETWORKS:
        if ip in net:
            return True

    # Check CGNAT
    if isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT_NETWORK:
        return True

    return False


def validate_and_sanitize_url(url: str) -> str:
    """
    Validate URL syntax, enforce http/https scheme, resolve DNS hostname,
    and prevent SSRF by ensuring all resolved IPs are publicly routable.

    Returns:
        Normalized URL string if valid.

    Raises:
        InvalidURLException: If URL scheme or syntax is invalid.
        SSRFSecurityException: If target hostname resolves to restricted IP.
    """
    if not url or not isinstance(url, str):
        raise InvalidURLException("URL must be a non-empty string.")

    cleaned_url = url.strip()

    try:
        parsed = urlsplit(cleaned_url)
    except Exception as exc:
        raise InvalidURLException(f"Malformed URL: {exc}") from exc

    # Scheme check
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise InvalidURLException(f"Invalid URL scheme '{parsed.scheme}'. Only 'http' and 'https' are allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise InvalidURLException("URL does not contain a valid hostname.")

    # Reject usernames/passwords in URLs
    if parsed.username or parsed.password:
        raise InvalidURLException("URLs with embedded user credentials are not permitted.")

    # Check for localhost / loopback names directly
    if hostname.lower() in ("localhost", "localhost.localdomain", "broadcasthost"):
        raise SSRFSecurityException("Access to localhost is strictly prohibited.")

    # Strip square brackets for IPv6 literal
    raw_host = hostname.strip("[]")

    resolved_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []

    # Check if host is direct IP literal
    try:
        direct_ip = ipaddress.ip_address(raw_host)
        resolved_ips.append(direct_ip)
    except ValueError:
        # Host is a domain name: resolve DNS
        try:
            addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
            for item in addr_info:
                sockaddr = item[4]
                ip_str = sockaddr[0]
                resolved_ips.append(ipaddress.ip_address(ip_str))
        except socket.gaierror as exc:
            raise InvalidURLException(f"Unable to resolve DNS for hostname '{hostname}': {exc}") from exc

    if not resolved_ips:
        raise InvalidURLException(f"Could not resolve any IP addresses for host '{hostname}'.")

    # Enforce SSRF restrictions across all resolved IPs
    for ip in resolved_ips:
        if is_ip_restricted(ip):
            raise SSRFSecurityException(
                f"Security violation (SSRF): Host '{hostname}' resolves to restricted address '{ip}'. "
                "Private, loopback, and metadata network targets are blocked."
            )

    # Reconstruct normalized URL
    normalized = urlunsplit((
        scheme,
        parsed.netloc.lower(),
        parsed.path or "/",
        parsed.query,
        "",  # drop fragment
    ))

    return normalized
