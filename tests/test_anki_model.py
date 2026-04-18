from avianki import anki_model


def test_stable_id_is_deterministic():
    assert anki_model._stable_id("seed") == anki_model._stable_id("seed")


def test_stable_id_different_seeds():
    assert anki_model._stable_id("seed_a") != anki_model._stable_id("seed_b")


def test_stable_id_is_int():
    assert isinstance(anki_model._stable_id("anything"), int)


def test_model_has_correct_fields():
    field_names = [f["name"] for f in anki_model.FIELDS]
    assert field_names == ["BirdName", "SciName", "Image1", "Image2", "Call", "Song", "Description", "DescriptionRedacted"]


def test_model_has_two_templates():
    assert len(anki_model.TEMPLATES) == 2


def test_model_template_names():
    names = [t["name"] for t in anki_model.TEMPLATES]
    assert "Picture → Name" in names
    assert "Description → Name" in names
