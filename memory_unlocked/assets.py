"""Small local registry for governed reusable assets, separate from memories."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .models import Namespace
from .policy import pii_reason, secret_reason

ASSET_STATUSES = ("candidate", "active", "archived", "rejected")


@dataclass(frozen=True)
class GovernedAsset:
    id: str
    namespace: str
    name: str
    content: str
    source_ref: str
    status: str = "candidate"
    version: int = 1


class AssetRegistry:
    """An explicit JSON registry with review-before-activation lifecycle."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self) -> list[GovernedAsset]:
        if not self.path.exists():
            return []
        rows = json.loads(self.path.read_text(encoding="utf-8"))
        return [GovernedAsset(**row) for row in rows]

    def _save(self, assets: Iterable[GovernedAsset]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(a) for a in assets], indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def create(self, namespace: Namespace, name: str, content: str, source_ref: str) -> GovernedAsset:
        if not name.strip() or not content.strip() or not source_ref.strip():
            raise ValueError("name, content, and source_ref are required")
        for value in (name, content, source_ref):
            if secret_reason(value):
                raise ValueError("asset content matched a secret pattern")
            if pii_reason(value):
                raise ValueError("asset content matched a personal-data pattern")
        token = hashlib.sha256((namespace.as_key() + name + source_ref).encode()).hexdigest()[:16]
        asset = GovernedAsset("asset_" + token, namespace.as_key(), name.strip(), content.strip(), source_ref.strip())
        assets = self._load()
        if any(item.id == asset.id for item in assets):
            raise ValueError("asset already exists")
        assets.append(asset)
        self._save(assets)
        return asset

    def set_status(self, asset_id: str, status: str) -> GovernedAsset:
        if status not in ASSET_STATUSES:
            raise ValueError(f"status must be one of {ASSET_STATUSES}")
        assets = self._load()
        for index, asset in enumerate(assets):
            if asset.id == asset_id:
                updated = GovernedAsset(**{**asdict(asset), "status": status, "version": asset.version + 1})
                assets[index] = updated
                self._save(assets)
                return updated
        raise KeyError(asset_id)

    def list(self, namespace: Namespace, include_inactive: bool = False) -> list[GovernedAsset]:
        statuses = ASSET_STATUSES if include_inactive else ("active",)
        return [a for a in self._load() if a.namespace == namespace.as_key() and a.status in statuses]
