"""allaboutbirds.org scraper, kept but dormant (ADR 0002).

Nothing registers it and nothing in the 1.0 pipeline imports it: allaboutbirds.org's terms do
not allow republishing its text or media, so it can never feed the published catalog. It is
here so the parsing work is not lost if that ever changes. ``scrape`` holds the old 0.9
functions unchanged; the tests in ``tests/sources/`` keep them working against saved HTML.
"""
