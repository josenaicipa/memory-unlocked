"""Generic channel-to-namespace rollout contracts with no product mappings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import Namespace


@dataclass(frozen=True)
class ChannelContract:
    channel: str
    namespace: Namespace
    status: str
    reason: str = ""


def build_channel_contracts(routes: dict[str, Namespace]) -> list[ChannelContract]:
    """Build deterministic ready contracts from an explicit caller-supplied map."""
    return [ChannelContract(channel, routes[channel], "ready") for channel in sorted(routes)]


def validate_channel_contracts(contracts: Iterable[ChannelContract]) -> list[dict[str, str]]:
    """Validate exact route bindings; duplicate channel names fail closed."""
    seen = set()
    findings = []
    for contract in contracts:
        if not contract.channel.strip():
            findings.append({"channel": contract.channel, "status": "invalid", "reason": "empty channel"})
        elif contract.channel in seen:
            findings.append({"channel": contract.channel, "status": "invalid", "reason": "duplicate channel"})
        else:
            seen.add(contract.channel)
            findings.append({"channel": contract.channel, "status": contract.status, "reason": contract.reason})
    return findings
