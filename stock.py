"""Wikimedia Commons stills with explicit reusable-license metadata."""

import re
from html import unescape
from urllib.parse import urlsplit

import requests

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "ShortlistStudio/1.0 (local video editor; Wikimedia Commons B-roll)"}
LICENSE = re.compile(r"^(?:public domain|cc0(?: 1\.0)?|cc by [1-4]\.\d)$", re.I)


def text_value(metadata, key):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", metadata.get(key, {}).get("value", ""))).split())


def images(**selector):
    response = requests.get(API, params={
        "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|mime|extmetadata",
        "iiurlwidth": 960, **selector,
    }, headers=HEADERS, timeout=12)
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {}).values()
    results = []
    for page in sorted(pages, key=lambda item: item.get("index", 0)):
        photo = next(iter(page.get("imageinfo", ())), {})
        metadata = photo.get("extmetadata", {})
        license_name = text_value(metadata, "LicenseShortName")
        if not LICENSE.fullmatch(license_name) or photo.get("mime") not in {"image/jpeg", "image/png"}:
            continue
        thumbnail = photo.get("thumburl", "")
        url = urlsplit(thumbnail)
        if url.scheme != "https" or url.hostname not in {"upload.wikimedia.org", "thumb.wikimedia.org"}:
            continue
        results.append({
            "id": page["pageid"], "title": page["title"].removeprefix("File:"),
            "thumbnail": thumbnail, "author": text_value(metadata, "Artist") or "See source page",
            "license": license_name, "license_url": text_value(metadata, "LicenseUrl"),
            "source": f"https://commons.wikimedia.org/?curid={page['pageid']}",
        })
    return results


def lookup(keyword):
    results = images(generator="search", gsrsearch=f"{keyword} incategory:CC-BY-4.0 filetype:bitmap",
                     gsrnamespace=6, gsrlimit=18)
    return (results or images(generator="search", gsrsearch=f"{keyword} filetype:bitmap",
                             gsrnamespace=6, gsrlimit=18))[:8]


def download_still(identifier, directory):
    results = images(pageids=identifier)
    if not results:
        raise ValueError("That image is no longer available under a supported license.")
    image = results[0]
    with requests.get(image["thumbnail"], headers=HEADERS, timeout=15, stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError("Could not fetch the selected stock image.")
        content = response.headers.get("Content-Type", "").split(";")[0]
        suffix = {"image/jpeg": ".jpg", "image/png": ".png"}.get(content)
        if not suffix:
            raise ValueError("The stock response was not a supported image.")
        path = directory / ("stock" + suffix)
        size = 0
        try:
            with path.open("wb") as target:
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 10 * 1024**2:
                        raise ValueError("The stock image exceeds 10 MB.")
                    target.write(chunk)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    credit = "\n".join([image["title"], image["author"], image["license"], image["license_url"],
                        image["source"], "Changes: cropped and layered into the video."])
    return path, credit
