import re

def sanitize_logo_url(logo_url: str) -> str:
    """
    Sanitizes and cleans VOD logo URLs.
    1. Normalizes duplicate slashes in URL paths (e.g., http://domain/movies//file.jpg -> http://domain/movies/file.jpg).
    2. Detects TMDB image paths originating from broken IPTV CDN proxy domains (e.g., exchange-cdn, images/movies, images/series)
       or TMDB hashes and remaps them to the official TMDB CDN (https://image.tmdb.org/t/p/w500/{filename}).
    """
    if not logo_url or not isinstance(logo_url, str):
        return logo_url

    logo_url = logo_url.strip()
    if not logo_url:
        return logo_url

    # Normalize double slashes in URL path, preserving protocol http:// or https://
    logo_url = re.sub(r'(?<!:)/{2,}', '/', logo_url)

    # Check for image filename pattern at the end of the URL
    match = re.search(r'/([^/]+\.(?:jpg|jpeg|png|webp))$', logo_url, re.IGNORECASE)
    if match and "image.tmdb.org" not in logo_url:
        filename = match.group(1)
        # Check if URL comes from known broken IPTV CDNs or contains TMDB poster filename patterns
        is_broken_cdn = "exchange-cdn" in logo_url or "images/movies" in logo_url or "images/series" in logo_url
        is_tmdb_hash = len(filename) >= 20 or (len(filename) >= 15 and filename.startswith(('t', 'v', 'p', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'q', 'r', 's', 'u', 'w', 'x', 'y', 'z')))
        
        if is_broken_cdn and (is_tmdb_hash or len(filename) >= 15):
            logo_url = f"https://image.tmdb.org/t/p/w500/{filename}"

    return logo_url
