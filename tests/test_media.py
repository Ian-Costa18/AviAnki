from unittest.mock import MagicMock, patch

import requests

from avianki import media


def test_find_cached_returns_none_when_missing(tmp_media_dir):
    assert media.find_cached(tmp_media_dir, "bird_robin", [".mp3", ".wav"]) is None


def test_find_cached_returns_filename_when_exists(tmp_media_dir):
    (tmp_media_dir / "bird_robin.mp3").touch()
    result = media.find_cached(tmp_media_dir, "bird_robin", [".mp3", ".wav"])
    assert result == "bird_robin.mp3"


def test_find_cached_returns_first_matching_ext(tmp_media_dir):
    (tmp_media_dir / "bird_robin.wav").touch()
    result = media.find_cached(tmp_media_dir, "bird_robin", [".mp3", ".wav"])
    assert result == "bird_robin.wav"


def test_find_cached_image_matches_jpg(tmp_media_dir):
    (tmp_media_dir / "bird_robin_img1.jpg").touch()
    assert media.find_cached_image(tmp_media_dir, "bird_robin_img1") == "bird_robin_img1.jpg"


def test_find_cached_audio_matches_mp3(tmp_media_dir):
    (tmp_media_dir / "bird_robin_call.mp3").touch()
    assert media.find_cached_audio(tmp_media_dir, "bird_robin_call") == "bird_robin_call.mp3"


def test_download_file_success(tmp_path):
    dest = tmp_path / "file.mp3"
    mock_resp = MagicMock()
    mock_resp.content = b"audio data"
    mock_resp.raise_for_status = MagicMock()

    with patch("avianki.media.requests.get", return_value=mock_resp):
        result = media.download_file("http://example.com/file.mp3", dest)

    assert result is True
    assert dest.read_bytes() == b"audio data"


def test_download_file_returns_false_on_http_error(tmp_path):
    dest = tmp_path / "file.mp3"
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests.HTTPError("404")

    with patch("avianki.media.requests.get", return_value=mock_resp):
        result = media.download_file("http://example.com/file.mp3", dest)

    assert result is False


def test_download_file_returns_false_on_exception(tmp_path):
    dest = tmp_path / "file.mp3"
    with patch("avianki.media.requests.get", side_effect=ConnectionError("no network")):
        result = media.download_file("http://example.com/file.mp3", dest)

    assert result is False


def test_trim_to_mp3_success(tmp_path):
    src = tmp_path / "src.mp3"
    dst = tmp_path / "dst.mp3"
    mock_segment = MagicMock()
    mock_segment.__getitem__ = MagicMock(return_value=mock_segment)

    with patch("avianki.media.AudioSegment.from_file", return_value=mock_segment):
        result = media.trim_to_mp3(src, dst)

    assert result is True
    mock_segment.export.assert_called_once_with(dst, format="mp3")


def test_trim_to_mp3_failure(tmp_path):
    src = tmp_path / "src.mp3"
    dst = tmp_path / "dst.mp3"

    with patch("avianki.media.AudioSegment.from_file", side_effect=Exception("decode error")):
        result = media.trim_to_mp3(src, dst)

    assert result is False
