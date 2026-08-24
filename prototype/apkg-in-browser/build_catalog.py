"""PROTOTYPE — throwaway. Fetches a tiny real catalog (3 species) into catalog/.

Mimics what the build-time pipeline would publish: openly-licensed images from
Wikimedia Commons, openly-licensed audio from iNaturalist, audio pre-transcoded
to mp3 so the browser never has to touch ffmpeg.
"""
import json, subprocess, urllib.parse
from pathlib import Path

import requests

SESSION = requests.Session()

UA = "AviAnki-prototype/0.1 (https://github.com/Ian-Costa18/AviAnki; ibarish@stoneturn.com)"
OUT = Path(__file__).parent / "catalog"
OUT.mkdir(exist_ok=True)

SPECIES = [
    ("American Robin", "Turdus migratorius", 12727),
    ("Northern Cardinal", "Cardinalis cardinalis", 9083),
    ("Blue Jay", "Cyanocitta cristata", 8229),
]
OPEN = {"cc0", "cc-by", "cc-by-sa"}


def get(url):
    r = SESSION.get(url, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    return r.content


def _commons_thumb(name):
    q = urllib.parse.urlencode({"action": "query", "format": "json", "prop": "imageinfo",
                                "titles": name, "iiprop": "url|extmetadata",
                                "iiurlwidth": "800"})
    d = json.loads(get(f"https://commons.wikimedia.org/w/api.php?{q}"))
    p = next(iter(d["query"]["pages"].values()))
    ii = p.get("imageinfo", [{}])[0]
    lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
    if "thumburl" in ii and "fair" not in lic.lower():
        return ii["thumburl"], lic, name
    return None


def wiki_images(title, n=3):
    """Lead image first (Commons-curated), then more from the article."""
    q = urllib.parse.urlencode({"action": "query", "format": "json", "redirects": "1",
                                "prop": "pageimages|images", "piprop": "name",
                                "titles": title, "imlimit": "50"})
    data = json.loads(get(f"https://en.wikipedia.org/w/api.php?{q}"))
    page = next(iter(data["query"]["pages"].values()))
    names = []
    if page.get("pageimage"):
        names.append("File:" + page["pageimage"].replace("_", " "))
    names += [i["title"] for i in page.get("images", [])
              if i["title"].lower().endswith((".jpg", ".jpeg", ".png"))
              and "commons-logo" not in i["title"].lower()
              and "status_iucn" not in i["title"].lower().replace(" ", "_")]
    out, seen = [], set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        got = _commons_thumb(name)
        if got:
            out.append(got)
        if len(out) >= n:
            break
    return out


def inat_sound(taxon_id):
    q = urllib.parse.urlencode({"taxon_id": taxon_id, "sounds": "true",
                                "quality_grade": "research", "licensed": "true",
                                "per_page": "30", "order_by": "votes"})
    d = json.loads(get(f"https://api.inaturalist.org/v1/observations?{q}"))
    out = []
    for o in d["results"]:
        for s in o.get("sounds", []):
            if (s.get("license_code") or "").lower() in OPEN and s.get("file_url"):
                out.append((s["file_url"], s.get("attribution", ""), s["id"]))
    return out


manifest = []
for name, sci, taxon in SPECIES:
    slug = name.lower().replace(" ", "-")
    entry = {"name": name, "sciName": sci, "images": [], "audio": []}
    for i, (url, lic, title) in enumerate(wiki_images(name), 1):
        ext = ".png" if url.lower().endswith(".png") else ".jpg"
        fn = f"{slug}_img{i}{ext}"
        (OUT / fn).write_bytes(get(url))
        entry["images"].append({"file": fn, "licence": lic, "credit": title})
        print("img", fn, (OUT / fn).stat().st_size)
    for i, (url, attr, sid) in enumerate(inat_sound(taxon)[:3], 1):
        raw = OUT / f"_raw_{slug}_{i}"
        raw.write_bytes(get(url))
        fn = f"{slug}_audio{i}.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-t", "10",
                        "-af", "highpass=f=250,loudnorm=I=-18:TP=-1.5:LRA=11",
                        "-ac", "1", "-ar", "44100", "-b:a", "96k", str(OUT / fn)], check=True)
        raw.unlink()
        entry["audio"].append({"file": fn, "attribution": attr, "sourceId": sid})
        print("aud", fn, (OUT / fn).stat().st_size)
    manifest.append(entry)

(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print("wrote manifest with", len(manifest), "species")
