import base64
from io import BytesIO
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from fastapi import HTTPException

from app.routers.admin import delete_product_image, update_product, upload_product_image
from app.schemas import ImageDeleteRequest, ImageUploadRequest, ProductUpdateRequest

from app.services.product_images import (
    MAX_PRODUCT_IMAGE_BYTES,
    ProductImageError,
    managed_image_path,
    normalize_product_image,
)


class ProductImageTests(unittest.TestCase):
    @staticmethod
    def _image(fmt: str, size: tuple[int, int], *, noisy: bool = False) -> bytes:
        image = Image.effect_noise(size, 90).convert("RGB") if noisy else Image.new("RGB", size, "#2fb865")
        output = BytesIO()
        image.save(output, format=fmt)
        return output.getvalue()

    def test_square_source_is_encoded_to_800_webp_under_500kb(self):
        result = normalize_product_image(self._image("PNG", (1200, 1200), noisy=True))

        self.assertLessEqual(len(result), MAX_PRODUCT_IMAGE_BYTES)
        with Image.open(BytesIO(result)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (800, 800))

    def test_non_square_source_is_rejected_until_client_crop_is_applied(self):
        with self.assertRaises(ProductImageError) as ctx:
            normalize_product_image(self._image("JPEG", (1200, 800)))
        self.assertIn("1:1", str(ctx.exception))

    def test_gif_is_not_accepted_for_product_images(self):
        with self.assertRaises(ProductImageError):
            normalize_product_image(self._image("GIF", (800, 800)))

    def test_highly_compressed_oversized_image_is_rejected_before_decode(self):
        output = BytesIO()
        Image.new("1", (5000, 5000), 1).save(output, format="PNG")
        with self.assertRaises(ProductImageError) as ctx:
            normalize_product_image(output.getvalue())
        self.assertIn("1,600만", str(ctx.exception))

    def test_only_current_merchant_storage_url_can_be_deleted(self):
        base = "https://sample.supabase.co"
        valid = f"{base}/storage/v1/object/public/merchant-images/merchant-1/products/item.webp"
        self.assertEqual(
            managed_image_path(valid, base, "merchant-images", "merchant-1"),
            "merchant-1/products/item.webp",
        )
        self.assertIsNone(managed_image_path(valid, base, "merchant-images", "merchant-2"))
        self.assertIsNone(managed_image_path("https://other.example/image.webp", base, "merchant-images", "merchant-1"))

    @patch("app.routers.admin._admin_merchant", return_value={"id": "merchant-1"})
    @patch("app.routers.admin._active_admin", return_value=SimpleNamespace(id="admin-1"))
    @patch("app.routers.admin.JoinRepository")
    def test_product_upload_reencodes_before_storage(self, repo_class, _active, _merchant):
        repo = repo_class.return_value
        repo.client.upload_public_object.return_value = "https://sample/image.webp"
        source = self._image("PNG", (800, 800), noisy=True)

        result = upload_product_image(ImageUploadRequest(
            filename="cropped.webp",
            content_type="image/webp",
            data_base64=base64.b64encode(source).decode(),
        ), "token")

        bucket, path, encoded, content_type = repo.client.upload_public_object.call_args.args
        self.assertEqual(bucket, "merchant-images")
        self.assertTrue(path.startswith("merchant-1/products/"))
        self.assertTrue(path.endswith(".webp"))
        self.assertEqual(content_type, "image/webp")
        self.assertLessEqual(len(encoded), MAX_PRODUCT_IMAGE_BYTES)
        self.assertEqual(result["data"]["width"], 800)

    @patch("app.routers.admin._admin_merchant", return_value={"id": "merchant-1"})
    @patch("app.routers.admin._active_admin", return_value=SimpleNamespace(id="admin-1"))
    @patch("app.routers.admin.JoinRepository")
    def test_explicit_cleanup_deletes_only_managed_object(self, repo_class, _active, _merchant):
        repo = repo_class.return_value
        repo.client.settings.supabase_url = "https://sample.supabase.co"
        repo.client.rest_get.side_effect = [[], []]
        image_url = "https://sample.supabase.co/storage/v1/object/public/merchant-images/merchant-1/products/new.webp"

        result = delete_product_image(ImageDeleteRequest(image_url=image_url), "token")

        repo.client.delete_public_objects.assert_called_once_with(
            "merchant-images", ["merchant-1/products/new.webp"]
        )
        self.assertTrue(result["data"]["deleted"])

    @patch("app.routers.admin._admin_merchant", return_value={"id": "merchant-1"})
    @patch("app.routers.admin._active_admin", return_value=SimpleNamespace(id="admin-1"))
    @patch("app.routers.admin.JoinRepository")
    def test_cleanup_refuses_image_still_referenced_by_product(self, repo_class, _active, _merchant):
        repo = repo_class.return_value
        repo.client.settings.supabase_url = "https://sample.supabase.co"
        repo.client.rest_get.return_value = [{"id": "product-1"}]
        image_url = "https://sample.supabase.co/storage/v1/object/public/merchant-images/merchant-1/products/live.webp"

        with self.assertRaises(HTTPException) as ctx:
            delete_product_image(ImageDeleteRequest(image_url=image_url), "token")

        self.assertEqual(ctx.exception.status_code, 409)
        repo.client.delete_public_objects.assert_not_called()

    @patch("app.routers.admin._ensure_product_belongs")
    @patch("app.routers.admin._admin_merchant", return_value={"id": "merchant-1"})
    @patch("app.routers.admin._active_admin", return_value=SimpleNamespace(id="admin-1"))
    @patch("app.routers.admin.JoinRepository")
    def test_replacing_product_image_removes_previous_storage_object(
        self, repo_class, _active, _merchant, ensure_product
    ):
        repo = repo_class.return_value
        repo.client.settings.supabase_url = "https://sample.supabase.co"
        old_url = "https://sample.supabase.co/storage/v1/object/public/merchant-images/merchant-1/products/old.webp"
        new_url = "https://sample.supabase.co/storage/v1/object/public/merchant-images/merchant-1/products/new.webp"
        ensure_product.return_value = {"id": "product-1", "image_url": old_url}
        repo.client.rest_patch.return_value = [{"id": "product-1", "image_url": new_url}]

        update_product("product-1", ProductUpdateRequest(image_url=new_url), "token")

        repo.client.delete_public_objects.assert_called_once_with(
            "merchant-images", ["merchant-1/products/old.webp"]
        )


if __name__ == "__main__":
    unittest.main()
