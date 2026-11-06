"""Acknowledge finding tool: a write tool that checks reach before writing."""

from typing import Any

from pydantic import BaseModel, Field
from tools.get_devices import DEVICE_LOCATIONS
from tools.get_vulnerabilities import VULNERABILITIES
from tools.reach import ReachAwareTool, out_of_reach

from spindl import ResponseEnvelope

# Acknowledgements recorded this run, keyed by (finding_id, subject).
ACKNOWLEDGEMENTS: dict[tuple[str, str], str] = {}


class AcknowledgeFindingTool(ReachAwareTool):
    """Record that the caller has seen a finding and is acting on it."""

    name = "acknowledge_finding"
    description = "Record that you have seen a vulnerability finding"
    category = "security"
    title = "Acknowledge finding"
    read_only = False
    destructive = False  # adds a record; overwrites and deletes nothing
    idempotent = True  # acknowledging twice records it once
    open_world = False
    permissions = ["inventory:write"]

    class InputModel(BaseModel):
        finding_id: str = Field(description="The finding to acknowledge (e.g. F-007)")
        note: str = Field(default="", max_length=500, description="Optional note")

    def guide(self) -> str:
        return (
            "# @acknowledge_finding\n\n"
            "Records that you have seen a finding from @get_vulnerabilities. "
            "Needs a key that may write, and the finding's device must be at "
            "one of your sites.\n"
        )

    async def execute(self, **params: Any) -> dict[str, Any]:
        validated = self.validate_input(params)
        reach = self.caller_reach()
        # Permission to call this tool was checked before it ran. Whether this
        # caller may write, and where, is reach, and only the tool can check it.
        if reach is None or not reach.can_write:
            return out_of_reach("This credential may not write.")
        finding = next(
            (v for v in VULNERABILITIES if v["finding_id"] == validated.finding_id),
            None,
        )
        if finding is None:
            return out_of_reach(f"No finding {validated.finding_id} at your sites.")
        if DEVICE_LOCATIONS.get(finding["device_id"]) not in reach.locations:
            # Answered as not found, so the caller learns nothing about it.
            return out_of_reach(f"No finding {validated.finding_id} at your sites.")

        context = self.context
        subject = (
            context.identity.subject
            if context is not None and context.identity is not None
            else "local"
        )
        ACKNOWLEDGEMENTS[(validated.finding_id, subject)] = validated.note
        return ResponseEnvelope(
            success=True,
            data={"finding_id": validated.finding_id, "acknowledged_by": subject},
        ).to_dict()
