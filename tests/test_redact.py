import re

import pytest

from avianki.redact import redact_name

REDACTED = "<em>[redacted]</em>"

# Real descriptions from birds.json, chosen for interesting redaction edge cases.
BIRDS: dict[str, str] = {
    # standalone last-word plural "Cardinals" is redacted
    "Northern Cardinal": (
        "The male Northern Cardinal is perhaps responsible for getting more people to open up a "
        "field guide than any other bird. They\u2019re a perfect combination of familiarity, "
        "conspicuousness, and style: a shade of red you can\u2019t take your eyes off. Even the "
        "brown females sport a sharp crest and warm red accents. Cardinals don\u2019t migrate and "
        "they don\u2019t molt into a dull plumage, so they\u2019re still breathtaking in winter\u2019s "
        "snowy backyards. In summer, their sweet whistles are one of the first sounds of the morning."
    ),
    # "blue" as a color adjective also gets redacted
    "Blue Jay": (
        "This common, large songbird is familiar to many people, with its perky crest; blue, "
        "white, and black plumage; and noisy calls. Blue Jays are known for their intelligence "
        "and complex social systems with tight family bonds. Their fondness for acorns is "
        "credited with helping spread oak trees after the last glacial period."
    ),
    # description opens with the full name plural
    "American Crow": (
        "American Crows are familiar over much of the continent: large, intelligent, all-black "
        "birds with hoarse, cawing voices. They are common sights in treetops, fields, and "
        "roadsides, and in habitats ranging from open woods and empty beaches to town centers. "
        "They usually feed on the ground and eat almost anything\u2014typically earthworms, "
        "insects and other small animals, seeds, and fruit; also garbage, carrion, and chicks "
        "they rob from nests. Their flight style is unique, a patient, methodical flapping that "
        "is rarely broken up with glides."
    ),
    # lowercase "woodpecker" mid-sentence should also be redacted
    "Downy Woodpecker": (
        "The active little Downy Woodpecker is a familiar sight at backyard feeders and in parks "
        "and woodlots, where it joins flocks of chickadees and nuthatches, barely outsizing them. "
        "An often acrobatic forager, this black-and-white woodpecker is at home on tiny branches "
        "or balancing on slender plant galls, sycamore seed balls, and suet feeders. Downies and "
        "their larger lookalike, the Hairy Woodpecker, are one of the first identification "
        "challenges that beginning bird watchers master."
    ),
    # "catty" must NOT be redacted — word boundary stops partial matches
    "Gray Catbird": (
        "If you\u2019re convinced you\u2019ll never be able to learn bird calls, start with the "
        "Gray Catbird. Once you\u2019ve heard its catty mew you won\u2019t forget it. Follow the "
        "sound into thickets and vine tangles and you\u2019ll be rewarded by a somber gray bird "
        "with a black cap and bright rusty feathers under the tail. Gray Catbirds are relatives "
        "of mockingbirds and thrashers, and they share that group\u2019s vocal abilities, copying "
        "the sounds of other species and stringing them together to make their own song."
    ),
    # hyphenated name; description opens with name plural
    "Dark-eyed Junco": (
        "Dark-eyed Juncos are neat, even flashy little sparrows that flit about forest floors of "
        "the western mountains and Canada, then flood the rest of North America for winter. "
        "They\u2019re easy to recognize by their crisp (though extremely variable) markings and "
        "the bright white tail feathers they habitually flash in flight. Dark-eyed Juncos are "
        "among the most abundant forest birds of North America. Look for them on woodland walks "
        "as well as in flocks at your feeders or on the ground beneath them."
    ),
    # "cattails" must NOT be redacted — word boundary stops partial matches
    "Red-winged Blackbird": (
        "One of the most abundant birds across North America, and one of the most boldly colored, "
        "the Red-winged Blackbird is a familiar sight atop cattails, along soggy roadsides, and "
        "on telephone wires. Glossy-black males have scarlet-and-yellow shoulder patches they can "
        "puff up or hide depending on how confident they feel. Females are a subdued, streaky "
        "brown, almost like a large, dark sparrow. Their early and tumbling song are happy "
        "indications of the return of spring."
    ),
    # irregular plural: "Goose" \u2192 "Geese"
    "Canada Goose": (
        "The big, black-necked Canada Goose with its signature white chinstrap mark is a familiar "
        "and widespread bird of fields and parks. Thousands of \u201chonkers\u201d migrate north "
        "and south each year, filling the sky with long V-formations. But as lawns have "
        "proliferated, more and more of these grassland-adapted birds are staying put in urban "
        "and suburban areas year-round, where some people regard them as pests."
    ),
    # lowercase "hummingbird" and "hummingbirds" mid-sentence should be redacted
    "Ruby-throated Hummingbird": (
        "A flash of green and red, the Ruby-throated Hummingbird is eastern North America\u2019s "
        "sole breeding hummingbird. These brilliant, tiny, precision-flying creatures glitter like "
        "jewels in the full sun, then vanish with a zip toward the next nectar source. Feeders and "
        "flower gardens are great ways to attract these birds, and some people turn their yards "
        "into buzzing clouds of hummingbirds each summer. Enjoy them while they\u2019re around; "
        "by early fall they\u2019re bound for Central America."
    ),
    # "bald" used as an adjective ("aren\u2019t really bald") also gets redacted
    "Bald Eagle": (
        "The Bald Eagle has been the national emblem of the United States since 1782 and a "
        "spiritual symbol for native people for far longer than that. These regal birds aren\u2019t "
        "really bald, but their white-feathered heads gleam in contrast to their chocolate-brown "
        "body and wings. Look for them soaring in solitude, chasing other birds for their food, "
        "or gathering by the hundreds in winter. Once endangered by hunting and pesticides, "
        "Bald Eagles have flourished under protection."
    ),
}


@pytest.mark.parametrize("name,desc", BIRDS.items())
def test_name_absent(name, desc):
    result = redact_name(desc, name)
    for part in [name] + name.split():
        assert part not in result, f"'{part}' still present for {name!r}"


@pytest.mark.parametrize("name,desc", BIRDS.items())
def test_redacted_present(name, desc):
    result = redact_name(desc, name)
    assert REDACTED in result, f"nothing redacted for {name!r}"


# Spot-checks for specific interesting redaction behaviour.
# `present`: substring that must still appear in the result
# `gone`:    substring that must be absent from the result
@pytest.mark.parametrize(
    "name,present,gone",
    [
        (  # lowercase "blue" (color adjective) is redacted too — matching ignores case (#30)
            "Blue Jay",
            f"{REDACTED}, white, and black plumage",
            "blue",
        ),
        (  # lowercase "hummingbird" mid-sentence is redacted
            "Ruby-throated Hummingbird",
            "sole breeding",
            "hummingbird",
        ),
        (  # "catty" is NOT redacted — word boundary stops partial matches
            "Gray Catbird",
            "catty mew",
            "Catbird",
        ),
        (  # "cattails" is NOT redacted — word boundary stops partial matches
            "Red-winged Blackbird",
            "cattails",
            "Blackbird",
        ),
        (  # hyphenated name at start of description → result opens with REDACTED
            "Dark-eyed Junco",
            REDACTED,
            "Dark-eyed Junco",
        ),
        (  # lowercase "bald" (adjective) is redacted too — matching ignores case (#30)
            "Bald Eagle",
            f"aren\u2019t really {REDACTED},",
            "bald",
        ),
        (  # lowercase last word "woodpecker" is redacted
            "Downy Woodpecker",
            f"this black-and-white {REDACTED} is at home",
            "woodpecker",
        ),
    ],
)
def test_spot_checks(name, present, gone):
    result = redact_name(BIRDS[name], name)
    assert present in result, f"{name!r}: {present!r} missing from result"
    assert gone not in result, f"{name!r}: {gone!r} still present in result"


# Case-insensitivity (issue #30): prose sources such as Wikipedia lowercase the
# name mid-sentence, so every name word must be redacted in any case.
def _words_left(result: str, *words: str) -> list[str]:
    """Name words still present in `result` as whole words, ignoring case."""
    return [w for w in words if re.search(rf"\b{re.escape(w)}\b", result, re.IGNORECASE)]


def test_lowercase_prose_king_eider():
    result = redact_name("The king eider is a large sea duck.", "King Eider")
    assert _words_left(result, "king", "eider") == []
    assert result == f"The {REDACTED} is a large sea duck."


def test_any_case_green_heron():
    desc = "The green heron is a relatively small heron. GREEN plumage; Green Herons nest."
    result = redact_name(desc, "Green Heron")
    assert _words_left(result, "green", "heron", "herons") == []
    assert result == (
        f"The {REDACTED} is a relatively small {REDACTED}. {REDACTED} plumage; {REDACTED} nest."
    )


def test_plurals_any_case():
    result = redact_name("herons and Herons and HERONS", "Green Heron")
    assert result == f"{REDACTED} and {REDACTED} and {REDACTED}"


# Hyphenated names: the full hyphenated token is redacted in any case, and each
# hyphen part is also redacted as a standalone word ("dark", "eyed"). Prose
# often splits the compound ("a ruby throat", "dark eyes"), and over-redacting a
# generic word is a smaller harm than leaking half the name (PRD §7).
def test_hyphenated_name_parts_redacted():
    desc = "The dark-eyed junco is a dark sparrow. DARK-EYED JUNCOS have eyed looks; juncos flock."
    result = redact_name(desc, "Dark-eyed Junco")
    assert _words_left(result, "dark-eyed", "dark", "eyed", "junco", "juncos") == []
    assert result == (
        f"The {REDACTED} is a {REDACTED} sparrow. {REDACTED} have {REDACTED} looks; "
        f"{REDACTED} flock."
    )


def test_non_name_text_casing_untouched():
    desc = "The Green Heron hunts at DAWN along Quiet ponds."
    result = redact_name(desc, "Green Heron")
    assert result == f"The {REDACTED} hunts at DAWN along Quiet ponds."
