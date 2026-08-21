"""Base tool class for spindl MCP servers.

Tool authors subclass BaseTool to define their MCP tools. Each tool
declares its name, description, category, and an optional Pydantic
InputModel for parameter validation.

Tool guides use @tool_name placeholder syntax which is resolved to
fully prefixed wire names by the PrefixResolver at render time.
"""

import logging
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class BaseTool:
    """Base class for all spindl MCP tools.

    Subclass this to create a new tool. At minimum, override `name`,
    `description`, `category`, and `execute()`.

    Example::

        class GetDevices(BaseTool):
            name = "get_devices"
            description = "List all devices in the inventory"
            category = "inventory"
            spooler_auto_detect = True

            class InputModel(BaseModel):
                limit: int = Field(default=50, ge=1, le=500)

            def guide(self) -> str:
                return (
                    "Use @get_devices to list devices. "
                    "Query large results with @spooler_query."
                )

            async def execute(self, **params) -> dict:
                validated = self.InputModel(**params)
                ...
    """

    name: str = ""
    description: str = ""
    category: str = ""
    spooler_array_paths: list[str] | None = None
    spooler_auto_detect: bool = False
    InputModel: type[BaseModel] | None = None  # NOSONAR - PascalCase: class type

    @property
    def input_schema(self) -> dict[str, Any]:
        """Return JSON Schema for this tool's input parameters.

        Auto-generated from the InputModel Pydantic class if defined.
        """
        if self.InputModel is not None:
            return self.InputModel.model_json_schema()
        return {"type": "object", "properties": {}}

    def guide(self) -> str:
        """Return a usage guide for this tool.

        Default implementation introspects InputModel fields.
        Override to provide rich guide text with @placeholder
        references to other tools.
        """
        lines = [
            f"# {self.name}",
            "",
            f"**Category:** {self.category}",
            f"**Description:** {self.description}",
            "",
        ]

        if self.InputModel is not None:
            lines.append("## Parameters")
            lines.append("")
            for field_name, field_info in self.InputModel.model_fields.items():
                required = "required" if field_info.is_required() else "optional"
                field_desc = field_info.description or "No description"
                default_str = ""
                if not field_info.is_required() and field_info.default is not None:
                    default_str = f" (default: {field_info.default})"
                lines.append(
                    f"- **{field_name}** ({required}): {field_desc}{default_str}"
                )
            lines.append("")
        else:
            lines.append("*No parameters required.*")
            lines.append("")

        return "\n".join(lines)

    async def execute(self, **params: Any) -> dict[str, Any]:
        """Execute the tool with the given parameters.

        Must be overridden by subclasses.
        """
        raise NotImplementedError(f"Tool '{self.name}' must implement execute()")
