"""APS OSS v2 and Model Derivative client.

The adapter uses direct-to-S3 uploads and never exposes access tokens or signed URLs
outside this module.
"""

from __future__ import annotations

import base64
import math
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from v365_archviz.config import Settings
from v365_archviz.errors import ConfigurationError, ProviderError

MIN_PART_SIZE = 5 * 1024 * 1024
MAX_SIGNED_URLS = 25


@dataclass(frozen=True, slots=True)
class UploadedObject:
    object_id: str
    object_key: str
    size_bytes: int
    encoded_urn: str


@dataclass(frozen=True, slots=True)
class TranslationResult:
    encoded_urn: str
    derivative_urn: str
    status: str
    progress: str | None


def _encoded_urn(object_id: str) -> str:
    return base64.urlsafe_b64encode(object_id.encode()).decode().rstrip("=")


def _chunks(path: Path, part_size: int = MIN_PART_SIZE) -> Iterator[bytes]:
    with path.open("rb") as source:
        while chunk := source.read(part_size):
            yield chunk


def _find_ifc_derivative(value: Any) -> str | None:
    if isinstance(value, dict):
        urn = value.get("urn")
        role = value.get("role")
        if isinstance(urn, str) and role == "ifc":
            return urn
        for child in value.values():
            found = _find_ifc_derivative(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_ifc_derivative(child)
            if found:
                return found
    return None


class ApsModelDerivativeClient:
    """Small synchronous client suitable for a durable worker activity."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not settings.aps_configured:
            raise ConfigurationError(
                "APS_CLIENT_ID, APS_CLIENT_SECRET and APS_BUCKET_KEY are required"
            )
        self._settings = settings
        self._client_id = settings.aps_client_id or ""
        self._client_secret = settings.aps_client_secret or ""
        self._bucket_key = settings.aps_bucket_key or ""
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(180.0, connect=15.0), follow_redirects=True
        )
        self._owns_client = client is None
        self._sleep = sleep
        self._access_token: str | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ApsModelDerivativeClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        try:
            response = self._client.post(
                f"{self._settings.aps_base_url}/authentication/v2/token",
                auth=(self._client_id, self._client_secret),
                data={
                    "grant_type": "client_credentials",
                    "scope": "data:read data:write data:create bucket:create bucket:read",
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            token = response.json().get("access_token")
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("APS authentication failed") from exc
        if not isinstance(token, str) or not token:
            raise ProviderError("APS authentication response did not contain a token")
        self._access_token = token
        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/json",
        }

    def ensure_transient_bucket(self) -> None:
        url = f"{self._settings.aps_base_url}/oss/v2/buckets"
        try:
            response = self._client.post(
                url,
                headers=self._headers(),
                json={"bucketKey": self._bucket_key, "policyKey": "transient"},
            )
            if response.status_code != 409:
                response.raise_for_status()
            details = self._client.get(
                f"{url}/{quote(self._bucket_key, safe='')}/details",
                headers=self._headers(),
            )
            details.raise_for_status()
            policy = details.json().get("policyKey")
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("APS transient bucket setup failed") from exc
        if policy != "transient":
            raise ProviderError("configured APS bucket exists with a non-transient policy")

    def upload(self, source: Path, *, object_key: str | None = None) -> UploadedObject:
        if not source.is_file():
            raise ProviderError(f"source file does not exist: {source}")
        key = object_key or source.name
        size = source.stat().st_size
        part_count = max(1, math.ceil(size / MIN_PART_SIZE))
        upload_key: str | None = None
        content_parts = _chunks(source)
        endpoint = (
            f"{self._settings.aps_base_url}/oss/v2/buckets/"
            f"{quote(self._bucket_key, safe='')}/objects/{quote(key, safe='')}/signeds3upload"
        )

        try:
            for first_part in range(1, part_count + 1, MAX_SIGNED_URLS):
                batch_size = min(MAX_SIGNED_URLS, part_count - first_part + 1)
                params: dict[str, str | int] = {
                    "firstPart": first_part,
                    "parts": batch_size,
                }
                if upload_key:
                    params["uploadKey"] = upload_key
                signed = self._client.get(endpoint, headers=self._headers(), params=params)
                signed.raise_for_status()
                signed_body = signed.json()
                upload_key = signed_body.get("uploadKey")
                urls = signed_body.get("urls")
                if not isinstance(upload_key, str) or not isinstance(urls, list):
                    raise ProviderError("APS returned an invalid signed-upload response")
                if len(urls) != batch_size:
                    raise ProviderError("APS returned an unexpected number of signed URLs")
                for signed_url in urls:
                    if not isinstance(signed_url, str):
                        raise ProviderError("APS returned an invalid signed URL")
                    part = next(content_parts)
                    uploaded = self._client.put(
                        signed_url,
                        content=part,
                        headers={"Content-Type": "application/octet-stream"},
                    )
                    uploaded.raise_for_status()

            finalized = self._client.post(
                endpoint,
                headers=self._headers(),
                json={"uploadKey": upload_key},
            )
            finalized.raise_for_status()
            body = finalized.json()
            object_id = body.get("objectId")
        except (httpx.HTTPError, ValueError, StopIteration) as exc:
            raise ProviderError("APS source upload failed") from exc
        if not isinstance(object_id, str) or not object_id:
            raise ProviderError("APS upload response did not contain an object ID")
        return UploadedObject(
            object_id=object_id,
            object_key=key,
            size_bytes=size,
            encoded_urn=_encoded_urn(object_id),
        )

    def submit_ifc_translation(self, encoded_urn: str) -> None:
        try:
            response = self._client.post(
                f"{self._settings.aps_base_url}/modelderivative/v2/designdata/job",
                headers={**self._headers(), "x-ads-region": self._settings.aps_region},
                json={
                    "input": {"urn": encoded_urn},
                    "output": {"formats": [{"type": "ifc", "views": ["3d"]}]},
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError("APS IFC translation submission failed") from exc

    def wait_for_ifc(
        self,
        encoded_urn: str,
        *,
        poll_interval_seconds: float = 5.0,
        max_attempts: int = 120,
    ) -> TranslationResult:
        endpoint = (
            f"{self._settings.aps_base_url}/modelderivative/v2/designdata/"
            f"{quote(encoded_urn, safe='')}/manifest"
        )
        for attempt in range(max_attempts):
            try:
                response = self._client.get(endpoint, headers=self._headers())
                response.raise_for_status()
                manifest = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise ProviderError("APS manifest polling failed") from exc
            status = manifest.get("status")
            progress = manifest.get("progress")
            if status == "success":
                derivative_urn = _find_ifc_derivative(manifest)
                if not derivative_urn:
                    raise ProviderError("APS manifest succeeded without an IFC derivative")
                return TranslationResult(
                    encoded_urn=encoded_urn,
                    derivative_urn=derivative_urn,
                    status=status,
                    progress=progress if isinstance(progress, str) else None,
                )
            if status in {"failed", "timeout"}:
                raise ProviderError(f"APS IFC translation ended with status: {status}")
            if attempt + 1 < max_attempts:
                self._sleep(poll_interval_seconds)
        raise ProviderError("APS IFC translation polling timed out")

    def download_derivative(self, result: TranslationResult) -> bytes:
        derivative = quote(result.derivative_urn, safe="")
        endpoint = (
            f"{self._settings.aps_base_url}/modelderivative/v2/designdata/"
            f"{quote(result.encoded_urn, safe='')}/manifest/{derivative}"
        )
        try:
            response = self._client.get(endpoint, headers=self._headers())
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError("APS IFC derivative download failed") from exc
        return response.content

