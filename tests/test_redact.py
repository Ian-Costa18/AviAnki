from avianki.redact import redact_name

# Real descriptions from the 3 integration-test birds (House Sparrow, American Robin,
# American Herring Gull), used to pin redaction behaviour against live data.

HOUSE_SPARROW_DESC = (
    "You can find House Sparrows most places where there are houses (or other buildings), "
    "and few places where there aren\u2019t. Along with two other introduced species, the "
    "European Starling and the Rock Pigeon, these are some of our most common birds. Their "
    "constant presence outside our doors makes them easy to overlook, and their tendency to "
    "displace native birds from nest boxes causes some people to resent them. But House "
    "Sparrows, with their capacity to live so intimately with us, are just beneficiaries of "
    "our own success."
)

AMERICAN_ROBIN_DESC = (
    "The quintessential early bird, American Robins are common sights on lawns across North "
    "America, where you often see them tugging earthworms out of the ground. Robins are "
    "popular birds for their warm orange breast, cheery song, and early appearance at the end "
    "of winter. Though they\u2019re familiar town and city birds, American Robins are at home "
    "in wilder areas, too, including mountain forests and Alaskan wilderness."
)

AMERICAN_HERRING_GULL_DESC = (
    "Spiraling above a fishing boat or squabbling at a dock or parking lot, American Herring "
    "Gulls are the quintessential gray-and-white, pink-legged \u201cseagulls.\u201d They\u2019re "
    "the most familiar gulls of the North Atlantic and can be found across much of coastal "
    "North America in winter. A variety of plumages worn in their first four years can make "
    "identification tricky\u2014so begin by learning to recognize their beefy size and shape."
)


def test_redact_house_sparrow_removes_name():
    result = redact_name(HOUSE_SPARROW_DESC, "House Sparrow")
    assert "House Sparrow" not in result
    assert "House Sparrows" not in result


def test_redact_house_sparrow_replaces_plural():
    result = redact_name(HOUSE_SPARROW_DESC, "House Sparrow")
    # mid-sentence → lowercase
    assert "You can find these birds most places" in result
    assert "But these birds, with their capacity" in result


def test_redact_american_robin_removes_name():
    result = redact_name(AMERICAN_ROBIN_DESC, "American Robin")
    assert "American Robin" not in result
    assert "American Robins" not in result


def test_redact_american_robin_replaces_full_and_last_word():
    result = redact_name(AMERICAN_ROBIN_DESC, "American Robin")
    # mid-sentence after comma → lowercase
    assert "these birds are common sights" in result
    # after a period → capitalised
    assert "These birds are popular birds" in result


def test_redact_american_herring_gull_removes_name():
    result = redact_name(AMERICAN_HERRING_GULL_DESC, "American Herring Gull")
    assert "American Herring Gull" not in result
    assert "American Herring Gulls" not in result


def test_redact_american_herring_gull_replaces_plural():
    result = redact_name(AMERICAN_HERRING_GULL_DESC, "American Herring Gull")
    # mid-sentence after comma → lowercase; generic "gulls" becomes "type of these birds"
    assert "these birds are the quintessential" in result
    assert "the most familiar type of these birds of the North Atlantic" in result


def test_redact_consumes_the_article():
    # Regression: "The [Name]'s" was producing "The this bird's" before the fix.
    desc = "The American Robin's orange breast is striking. the American Robin sings at dawn."
    result = redact_name(desc, "American Robin")
    assert "The this bird" not in result
    assert "the this bird" not in result
    # sentence-start "The [Name]'s" → "This bird's"
    assert result.startswith("This bird")
    # after a period "the [Name]" → capitalised "This bird"
    assert "This bird sings at dawn" in result
