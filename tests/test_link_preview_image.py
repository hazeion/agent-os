from __future__ import annotations

from io import BytesIO
import unittest

from PIL import Image, PngImagePlugin, features

from link_preview_image import LinkPreviewImageError, transform_image


def encoded_image(format_name: str, *, size=(64, 48), mode="RGB", metadata=False) -> bytes:
    image = Image.new(mode, size, (15, 120, 60, 128) if mode == "RGBA" else (15, 120, 60))
    output = BytesIO()
    options = {}
    if metadata and format_name == "JPEG":
        exif = Image.Exif()
        exif[270] = "private description"
        options["exif"] = exif
    if metadata and format_name == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("private", "secret")
        options["pnginfo"] = info
    image.save(output, format_name, **options)
    return output.getvalue()


@unittest.skipUnless(features.check("webp"), "packaged Pillow has no WebP support")
class LinkPreviewImageTests(unittest.TestCase):
    def test_jpeg_png_and_static_webp_reencode_to_bounded_webp(self):
        fixtures = (
            (encoded_image("JPEG", metadata=True), "image/jpeg"),
            (encoded_image("PNG", mode="RGBA", metadata=True), "image/png"),
            (encoded_image("WEBP"), "image/webp"),
        )
        for source, mime in fixtures:
            with self.subTest(mime=mime):
                result = transform_image(source, mime)
                self.assertIsNotNone(result)
                self.assertLessEqual(len(result or b""), 512 * 1024)
                decoded = Image.open(BytesIO(result or b""))
                self.assertEqual(decoded.format, "WEBP")
                self.assertEqual(getattr(decoded, "n_frames", 1), 1)
                self.assertFalse(decoded.info.get("exif"))
                self.assertNotIn("private", decoded.info)

    def test_dimensions_pixels_and_output_fit_are_bounded(self):
        large = encoded_image("PNG", size=(1600, 800))
        result = transform_image(large, "image/png")
        decoded = Image.open(BytesIO(result or b""))
        self.assertLessEqual(decoded.width, 1200)
        self.assertLessEqual(decoded.height, 1200)
        with self.assertRaises(LinkPreviewImageError):
            transform_image(encoded_image("PNG", size=(2049, 1)), "image/png")
        with self.assertRaises(LinkPreviewImageError):
            transform_image(encoded_image("PNG", size=(2001, 2000)), "image/png")

    def test_mime_magic_and_format_must_agree(self):
        png = encoded_image("PNG")
        with self.assertRaises(LinkPreviewImageError):
            transform_image(png, "image/jpeg")
        with self.assertRaises(LinkPreviewImageError):
            transform_image(b"<svg><script>alert(1)</script></svg>", "image/png")
        with self.assertRaises(LinkPreviewImageError):
            transform_image(png, "image/svg+xml")
        with self.assertRaises(LinkPreviewImageError):
            transform_image(b"", "image/png")
        with self.assertRaises(LinkPreviewImageError):
            transform_image(b"x" * (2 * 1024 * 1024 + 1), "image/png")

    def test_animated_images_are_rejected(self):
        frames = [Image.new("RGBA", (16, 16), color) for color in ((255, 0, 0, 255), (0, 0, 255, 255))]
        output = BytesIO()
        frames[0].save(output, "WEBP", save_all=True, append_images=frames[1:], duration=100, loop=0)
        with self.assertRaises(LinkPreviewImageError):
            transform_image(output.getvalue(), "image/webp")

    def test_truncated_and_corrupt_images_are_rejected(self):
        source = encoded_image("JPEG")
        with self.assertRaises(LinkPreviewImageError):
            transform_image(source[:20], "image/jpeg")
        corrupt = bytearray(encoded_image("PNG"))
        corrupt[-8:] = b"corrupt!"
        with self.assertRaises(LinkPreviewImageError):
            transform_image(bytes(corrupt), "image/png")


if __name__ == "__main__":
    unittest.main()
