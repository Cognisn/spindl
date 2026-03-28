"""Get devices tool -- demonstrates a read tool with spooler auto-detect."""

from typing import Any, Optional

from pydantic import BaseModel, Field

from spindl import BaseTool, ResponseEnvelope, ResponseMetadata

# Fake device inventory data
DEVICES = [
    {"id": f"DEV-{i:04d}", "hostname": f"srv-{i:04d}.corp.local",
     "os": os, "status": status, "ip": f"10.0.{i // 256}.{i % 256}",
     "location": loc, "owner": owner, "cpu_cores": cores, "ram_gb": ram}
    for i, (os, status, loc, owner, cores, ram) in enumerate([
        ("Ubuntu 22.04", "online", "us-east-1", "platform-team", 8, 32),
        ("Windows Server 2022", "online", "us-east-1", "infra-team", 16, 64),
        ("RHEL 9", "online", "eu-west-1", "data-team", 32, 128),
        ("Ubuntu 22.04", "degraded", "eu-west-1", "platform-team", 8, 32),
        ("macOS 14", "online", "us-west-2", "eng-team", 10, 16),
        ("Windows Server 2019", "offline", "us-east-1", "legacy-team", 4, 16),
        ("Ubuntu 20.04", "online", "ap-south-1", "platform-team", 8, 32),
        ("RHEL 8", "online", "eu-west-1", "data-team", 64, 256),
        ("Ubuntu 22.04", "online", "us-west-2", "eng-team", 8, 32),
        ("Windows Server 2022", "degraded", "us-east-1", "infra-team", 16, 64),
        ("Debian 12", "online", "ap-south-1", "platform-team", 4, 16),
        ("Ubuntu 22.04", "online", "eu-west-1", "eng-team", 8, 32),
        ("RHEL 9", "offline", "us-east-1", "data-team", 32, 128),
        ("Windows Server 2022", "online", "us-west-2", "infra-team", 16, 64),
        ("Ubuntu 22.04", "online", "ap-south-1", "platform-team", 8, 32),
        ("macOS 14", "online", "us-west-2", "eng-team", 10, 16),
        ("RHEL 9", "online", "eu-west-1", "data-team", 32, 128),
        ("Ubuntu 22.04", "degraded", "us-east-1", "platform-team", 8, 32),
        ("Windows Server 2022", "online", "eu-west-1", "infra-team", 16, 64),
        ("Ubuntu 20.04", "online", "us-west-2", "eng-team", 8, 32),
    ], start=0)
]


class GetDevicesTool(BaseTool):
    """List devices in the inventory with optional filtering."""

    name = "get_devices"
    description = "List devices in the inventory with optional filtering"
    category = "inventory"
    spooler_auto_detect = True      # let the spooler find arrays automatically

    class InputModel(BaseModel):
        status: Optional[str] = Field(
            default=None,
            description="Filter by device status: online, offline, degraded",
        )
        location: Optional[str] = Field(
            default=None,
            description="Filter by AWS region (e.g. us-east-1)",
        )
        limit: int = Field(
            default=50,
            ge=1,
            le=500,
            description="Maximum number of devices to return",
        )

    def guide(self) -> str:
        return (
            "# @get_devices\n\n"
            "Returns a list of devices from the inventory. Results may be "
            "spooled if the response is large -- use @spooler_query to "
            "page through spooled results.\n\n"
            "## Parameters\n\n"
            "- **status** (optional): Filter by status "
            "(online / offline / degraded)\n"
            "- **location** (optional): Filter by AWS region\n"
            "- **limit** (optional): Max devices to return "
            "(default: 50, max: 500)\n\n"
            "## Workflow\n\n"
            "1. Call @get_devices to list devices\n"
            "2. If results are spooled, use @spooler_query with "
            "the spool_id to filter and paginate\n"
            "3. Use @spooler_aggregate to group devices by status "
            "or location\n"
            "4. Use @get_vulnerabilities to check a device's "
            "vulnerability posture\n"
        )

    async def execute(self, **params: Any) -> dict:
        validated = self.InputModel(**params)

        results = DEVICES[:]

        if validated.status:
            results = [d for d in results if d["status"] == validated.status]
        if validated.location:
            results = [d for d in results if d["location"] == validated.location]

        results = results[: validated.limit]

        return ResponseEnvelope(
            success=True,
            data={"devices": results},
            metadata=ResponseMetadata(
                total_results=len(results),
                returned_results=len(results),
            ),
        ).to_dict()
