"""Offline asset acquisition checks; no external requests."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acquire_image_sample import run, valid_url, validate_image
from PIL import Image, UnidentifiedImageError

from klegal_gold.storage.files import FileStore


class Reply(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.code = 200
        self.headers = {"Content-Type": "application/x-octetstream"}


class AssetTests(unittest.TestCase):
    def setUp(self):
        image = Image.new("RGB", (2, 3), "red")
        stream = io.BytesIO()
        image.save(stream, format="GIF")
        self.body = stream.getvalue()

    def mapping(self, directory):
        store = FileStore(directory)
        html = store.put(b"synthetic parent")
        urls = [
            "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?x=" + str(i)
            for i in range(2)
        ]
        refs = [{"order": i, "resolved_url": url} for i, url in enumerate([*urls, urls[0]])]
        (directory / "mapping.json").write_text(
            json.dumps(
                {
                    "source_id": "123",
                    "html_storage_key": html.storage_key,
                    "html_sha256": html.sha256,
                    "observation": {"images": refs},
                }
            )
        )
        return urls

    def test_no_current_images_is_not_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.mapping(directory)
            path = directory / "mapping.json"
            mapping = json.loads(path.read_text())
            mapping["observation"]["images"] = []
            path.write_text(json.dumps(mapping))
            with patch("acquire_image_sample.build_opener") as opener:
                run("123", directory, directory / "result.json", 1)
                opener.assert_not_called()
            result = json.loads((directory / "result.json").read_text())
            self.assertEqual(result["occurrences"], 0)
            self.assertFalse(result["all_occurrences_linked"])

    def test_decode_and_invalid_response(self):
        self.assertEqual(validate_image(self.body)["size"], [2, 3])
        with self.assertRaises(UnidentifiedImageError):
            validate_image(b"<html>error page</html>")

    def test_url_boundary(self):
        self.assertTrue(valid_url("https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?x=1"))
        for url in [
            "http://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on",
            "https://portal.scourt.go.kr.evil.example/pgp/pgp003/downloadImgFile.on",
            "https://portal.scourt.go.kr/other",
            "file:///tmp/a",
        ]:
            self.assertFalse(valid_url(url))

    def test_checkpoint_resume_reuse_and_repeat_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.mapping(directory)
            with (
                patch("acquire_image_sample.build_opener") as opener,
                patch("acquire_image_sample.time.sleep"),
            ):
                opener.return_value.open.side_effect = lambda *a, **kw: Reply(self.body)
                run("123", directory, directory / "result.json", 1)
                self.assertEqual(opener.return_value.open.call_count, 1)
                run("123", directory, directory / "result.json", 2)
                self.assertEqual(opener.return_value.open.call_count, 2)
                run("123", directory, directory / "result.json", 2)
                self.assertEqual(opener.return_value.open.call_count, 2)
            result = json.loads((directory / "result.json").read_text())
            self.assertEqual(result["verified_reused"], 2)
            self.assertEqual(result["unique_binary_hashes"], 1)
            self.assertEqual(result["occurrences"], 3)
            self.assertTrue(result["all_occurrences_linked"])

    def test_html_200_is_failed_and_stop_leaves_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.mapping(directory)
            with (
                patch("acquire_image_sample.build_opener") as opener,
                patch("acquire_image_sample.time.sleep"),
            ):
                opener.return_value.open.return_value = Reply(b"<html>not an image</html>")
                run("123", directory, directory / "result.json", 1)
            result = json.loads((directory / "result.json").read_text())
            self.assertEqual(result["failed_urls"], 1)
            self.assertFalse(result["all_occurrences_linked"])
            (directory / "STOP").touch()
            with patch("acquire_image_sample.build_opener") as opener:
                run("123", directory, directory / "result.json", 2)
                opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
