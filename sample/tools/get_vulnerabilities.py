"""Get vulnerabilities tool -- demonstrates explicit spooler_array_paths."""

import random
from typing import Any, Optional

from pydantic import BaseModel, Field

from spindl import BaseTool, ResponseEnvelope, ResponseMetadata

# Generate fake vulnerability data
_SEVERITIES = ["critical", "high", "medium", "low", "informational"]
_CVE_PREFIXES = ["CVE-2024-", "CVE-2023-", "CVE-2025-"]
_TITLES = [
    "Remote code execution in OpenSSL",
    "Privilege escalation via sudo misconfiguration",
    "SQL injection in web admin panel",
    "Cross-site scripting in dashboard",
    "Denial of service in DNS resolver",
    "Buffer overflow in kernel module",
    "Authentication bypass in SSH daemon",
    "Information disclosure via SNMP",
    "Insecure default credentials",
    "Path traversal in file upload handler",
    "XML external entity injection",
    "Deserialization vulnerability in Java runtime",
    "Weak TLS cipher suite configuration",
    "Unpatched Log4j dependency",
    "Memory corruption in image parser",
]

random.seed(42)  # deterministic for demo purposes
VULNERABILITIES = [  # NOSONAR - PRNG is intentional for deterministic sample data, not cryptographic use
    {
        "cve_id": f"{random.choice(_CVE_PREFIXES)}{random.randint(1000, 9999)}",
        "title": random.choice(_TITLES),
        "severity": random.choice(_SEVERITIES),
        "cvss_score": round(random.uniform(1.0, 10.0), 1),
        "device_id": f"DEV-{random.randint(0, 19):04d}",
        "status": random.choice(["open", "mitigated", "accepted"]),
        "first_seen": f"2024-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
    }
    for _ in range(80)
]


class GetVulnerabilitiesTool(BaseTool):
    """Retrieve vulnerability findings across devices."""

    name = "get_vulnerabilities"
    description = "Retrieve vulnerability findings across devices"
    category = "security"
    spooler_array_paths = ["vulnerabilities"]   # explicit path declaration

    class InputModel(BaseModel):
        device_id: Optional[str] = Field(
            default=None,
            description="Filter by device ID (e.g. DEV-0001)",
        )
        severity: Optional[str] = Field(
            default=None,
            description="Filter by severity: critical, high, medium, low, informational",
        )
        status: Optional[str] = Field(
            default=None,
            description="Filter by status: open, mitigated, accepted",
        )
        limit: int = Field(
            default=100,
            ge=1,
            le=500,
            description="Maximum number of vulnerabilities to return",
        )

    def guide(self) -> str:
        return (
            "# @get_vulnerabilities\n\n"
            "Returns vulnerability findings. With 80 records in the demo "
            "dataset, results will typically be spooled.\n\n"
            "## Parameters\n\n"
            "- **device_id** (optional): Filter to a single device\n"
            "- **severity** (optional): Filter by severity level\n"
            "- **status** (optional): Filter by remediation status\n"
            "- **limit** (optional): Max results (default: 100)\n\n"
            "## Workflow\n\n"
            "1. Call @get_vulnerabilities to fetch findings\n"
            "2. Use @spooler_aggregate to group by severity or device_id\n"
            "3. Use @spooler_query to filter for critical findings\n"
            "4. Use @spooler_distinct on the severity column to see "
            "the distribution\n"
            "5. Use @get_devices to look up device details\n"
        )

    async def execute(self, **params: Any) -> dict:
        validated = self.InputModel(**params)

        results = VULNERABILITIES[:]

        if validated.device_id:
            results = [v for v in results if v["device_id"] == validated.device_id]
        if validated.severity:
            results = [v for v in results if v["severity"] == validated.severity]
        if validated.status:
            results = [v for v in results if v["status"] == validated.status]

        results = results[: validated.limit]

        return ResponseEnvelope(
            success=True,
            data={"vulnerabilities": results},
            metadata=ResponseMetadata(
                total_results=len(results),
                returned_results=len(results),
            ),
        ).to_dict()
