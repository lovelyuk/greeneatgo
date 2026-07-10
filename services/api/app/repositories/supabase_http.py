from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from app.config import Settings, get_settings


class SupabaseHttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"Supabase HTTP {status}: {body}")
        self.status = status
        self.body = body


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


class SupabaseHttpClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _request(self, method: str, path: str, *, key: str, body: Any | None = None, prefer: str | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        req = Request(f"{self.settings.supabase_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as response:
                text = response.read().decode("utf-8")
                return json.loads(text) if text else None
        except HTTPError as exc:
            raise SupabaseHttpError(exc.code, exc.read().decode("utf-8")) from exc

    def rest_get(self, table: str, params: dict[str, str], *, service: bool = True) -> list[dict[str, Any]]:
        query = urlencode(params, safe="*,.():")
        key = self.settings.supabase_service_role_key if service else self.settings.supabase_anon_key
        return self._request("GET", f"/rest/v1/{table}?{query}", key=key)

    def rest_post(self, table: str, rows: dict[str, Any] | list[dict[str, Any]], *, upsert: bool = False) -> Any:
        prefer = "return=representation"
        if upsert:
            prefer += ",resolution=merge-duplicates"
        return self._request("POST", f"/rest/v1/{table}", key=self.settings.supabase_service_role_key, body=rows, prefer=prefer)

    def rest_patch(self, table: str, params: dict[str, str], values: dict[str, Any]) -> Any:
        query = urlencode(params, safe="*,.():")
        return self._request("PATCH", f"/rest/v1/{table}?{query}", key=self.settings.supabase_service_role_key, body=values, prefer="return=representation")

    def rest_delete(self, table: str, params: dict[str, str]) -> Any:
        query = urlencode(params, safe="*,.():")
        return self._request("DELETE", f"/rest/v1/{table}?{query}", key=self.settings.supabase_service_role_key, prefer="return=representation")

    def rpc(self, function_name: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", f"/rest/v1/rpc/{function_name}", key=self.settings.supabase_service_role_key, body=payload)

    def upload_public_object(self, bucket: str, object_path: str, data: bytes, content_type: str) -> str:
        """Upload one object with service-role credentials and return its public URL."""
        key = self.settings.supabase_service_role_key
        encoded_bucket = quote(bucket, safe="")
        encoded_path = quote(object_path, safe="/")
        req = Request(
            f"{self.settings.supabase_url}/storage/v1/object/{encoded_bucket}/{encoded_path}",
            data=data,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": content_type,
                "x-upsert": "false",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=30) as response:
                response.read()
        except HTTPError as exc:
            raise SupabaseHttpError(exc.code, exc.read().decode("utf-8")) from exc
        return f"{self.settings.supabase_url}/storage/v1/object/public/{encoded_bucket}/{encoded_path}"

    def delete_public_objects(self, bucket: str, object_paths: list[str]) -> None:
        if not object_paths:
            return
        key = self.settings.supabase_service_role_key
        encoded_bucket = quote(bucket, safe="")
        data = json.dumps({"prefixes": object_paths}).encode("utf-8")
        req = Request(
            f"{self.settings.supabase_url}/storage/v1/object/{encoded_bucket}",
            data=data,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="DELETE",
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(req, timeout=30) as response:
                    response.read()
                return
            except HTTPError as exc:
                if exc.code == 404:
                    return
                raise SupabaseHttpError(exc.code, exc.read().decode("utf-8")) from exc
            except (URLError, TimeoutError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.25 * (2**attempt))
        raise SupabaseHttpError(0, f"Storage delete transport failure: {last_error}") from last_error

    def auth_get_user(self, access_token: str) -> AuthUser:
        headers = {
            "apikey": self.settings.supabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        req = Request(f"{self.settings.supabase_url}/auth/v1/user", headers=headers, method="GET")
        try:
            with urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise SupabaseHttpError(exc.code, exc.read().decode("utf-8")) from exc
        return AuthUser(id=data["id"], email=data.get("email"), metadata=data.get("user_metadata") or {})
