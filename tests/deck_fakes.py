"""Small hand-built catalog objects for the deck tests."""

from __future__ import annotations

from avianki.catalog.format import (
    DatasetCredit,
    Manifest,
    MediaRef,
    RegionRef,
    SpeciesEntry,
    SpeciesFile,
)

ROBIN_PHOTO = MediaRef(
    "media/1a2b3c4d5e6f7a8b.webp",
    12,
    'Photo: <i>Turdus-migratorius-002</i> by <b>Mdf</b> · '
    '<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a> · '
    '<a href="https://commons.wikimedia.org/wiki/File:T.jpg">source</a> · resized',
)
ROBIN_AUDIO = MediaRef(
    "media/9f8e7d6c5b4a3921.mp3",
    9,
    'Recording: <b>Jane Doe</b> · '
    '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a> · '
    '<a href="https://example.org/rec/1">source</a>',
)
CARDINAL_PHOTO = MediaRef("media/00112233445566aa.webp", 10, "Photo: cardinal credit")
CARDINAL_AUDIO = MediaRef("media/aabbccddeeff0011.mp3", 8, "Recording: cardinal credit")
JAY_PHOTO = MediaRef("media/1111111111111111.webp", 5, "Photo: jay credit")
JAY_PHOTO2 = MediaRef("media/2222222222222222.webp", 5, "Photo: jay second credit")
WREN_AUDIO = MediaRef("media/3333333333333333.mp3", 5, "Recording: wren credit")


def species_file() -> SpeciesFile:
    return SpeciesFile(
        {
            "turdus-migratorius": SpeciesEntry(
                "American Robin", "Turdus migratorius", [ROBIN_PHOTO], [ROBIN_AUDIO]
            ),
            "cardinalis-cardinalis": SpeciesEntry(
                "Northern Cardinal", "Cardinalis cardinalis", [CARDINAL_PHOTO], [CARDINAL_AUDIO]
            ),
            # Photo only, and a second photo that must never be used.
            "cyanocitta-cristata": SpeciesEntry(
                "Blue Jay", "Cyanocitta cristata", [JAY_PHOTO, JAY_PHOTO2], []
            ),
            # Audio only.
            "troglodytes-aedon": SpeciesEntry(
                "House Wren", "Troglodytes aedon", [], [WREN_AUDIO]
            ),
            # Neither: a species with no media at all makes no note.
            "empty-bird": SpeciesEntry("Empty Bird", "Vacuus avis", [], []),
            # Markup characters in the names must be escaped in the fields. It also has an IOC name.
            "tom-and-jerry": SpeciesEntry("Tom & <Jerry>", "Muris <x> & y", [JAY_PHOTO], [], "Ioc <Tom> & Jerry"),
        }
    )


def manifest(*, ioc: bool = False) -> Manifest:
    credits = [
        DatasetCredit(
            "eBird Observation Dataset, Cornell Lab of Ornithology, via GBIF",
            "CC-BY-4.0",
            "https://doi.org/10.15468/aomfnb",
            "filtered and ranked by region",
        )
    ]
    if ioc:
        credits.append(
            DatasetCredit(
                "IOC World Bird List v15.1 & friends",
                "CC-BY-4.0",
                "https://www.worldbirdnames.org/",
                "",
            )
        )
    return Manifest(
        catalog_version="2026-09-30",
        base_url="https://example.org/catalog/",
        gadm_version="4.1",
        species_file="species.3f9a0c21.json",
        regions=[
            RegionRef("us-ma", "Massachusetts", "US", "regions/us-ma.8c1e44d0.json", 3)
        ],
        dataset_credits=credits,
        total_bytes=1000,
    )
