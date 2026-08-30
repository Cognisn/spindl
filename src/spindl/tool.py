"""Base tool class for spindl MCP servers.

Tool authors subclass BaseTool to define their MCP tools. Each tool
declares its name, description, category, and an optional Pydantic
InputModel for parameter validation.

Tool guides use @tool_name placeholder syntax which is resolved to
fully prefixed wire names by the PrefixResolver at render time.
"""

import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from spindl.responses.errors import ErrorDetail, StructuredError

logger = logging.getLogger(__name__)


class ToolInputError(Exception):
    """Raised when tool arguments do not match the declared input schema.

    Spindl tools are called by language models, which recover well from
    an explicit error and badly from a plausible untruth. Silently
    discarding an unexpected argument lets the caller believe a
    constraint was applied, so an argument mismatch is raised rather
    than ignored, and rendered as a structured error naming both the
    rejected keys and the accepted ones.
    """

    def __init__(self, message: str, suggestion: str) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion

    def to_dict(self) -> dict[str, Any]:
        """Render the error as a structured MCP response."""
        return StructuredError(
            error=ErrorDetail(
                error_code="INVALID_ARGUMENTS",
                error_message=self.message,
                retry_eligible=True,
                suggestion=self.suggestion,
            ),
        ).to_dict()


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
                validated = self.validate_input(params)
                ...
    """

    name: str = ""
    description: str = ""
    category: str = ""
    spooler_array_paths: list[str] | None = None
    spooler_auto_detect: bool = False
    InputModel: type[BaseModel] | None = None  # NOSONAR - PascalCase: class type
    reject_unknown_arguments: bool = True

    def accepted_arguments(self) -> list[str]:
        """Return the argument names this tool accepts, sorted.

        Taken from the ``InputModel`` fields, using each field's alias
        where one is set. A tool with no ``InputModel`` accepts nothing.
        """
        if self.InputModel is None:
            return []
        return sorted(
            info.alias or field_name
            for field_name, info in self.InputModel.model_fields.items()
        )

    def check_arguments(self, params: dict[str, Any]) -> None:
        """Raise :class:`ToolInputError` for arguments this tool does not accept.

        Called at the MCP boundary before ``execute``, so a tool that
        does not validate its own parameters is still protected. Set
        ``reject_unknown_arguments = False`` on a tool that deliberately
        takes free-form arguments.
        """
        if not self.reject_unknown_arguments:
            return
        accepted = self.accepted_arguments()
        unknown = sorted(set(params) - set(accepted))
        if not unknown:
            return
        rejected = ", ".join(repr(key) for key in unknown)
        accepted_text = ", ".join(accepted) if accepted else "none"
        raise ToolInputError(
            message=(
                f"Tool '{self.name}' does not accept the argument(s) "
                f"{rejected}. They were not applied."
            ),
            suggestion=(
                f"Accepted parameters: {accepted_text}. Remove the "
                f"rejected argument(s) and call the tool again, or use "
                f"a tool that supports them."
            ),
        )

    def validate_input(self, params: dict[str, Any]) -> Any:
        """Validate ``params`` and return the populated ``InputModel``.

        Rejects unknown arguments first, then applies the ``InputModel``
        field constraints. Both failures raise :class:`ToolInputError`,
        so the caller sees one recoverable error shape rather than an
        internal error. Returns ``None`` when the tool declares no
        ``InputModel``.
        """
        self.check_arguments(params)
        if self.InputModel is None:
            return None
        try:
            return self.InputModel(**params)
        except ValidationError as exc:
            raise ToolInputError(
                message=f"Invalid arguments for '{self.name}': {_summarise(exc)}",
                suggestion=(
                    f"Accepted parameters: "
                    f"{', '.join(self.accepted_arguments()) or 'none'}. "
                    f"Correct the reported field(s) and call the tool again."
                ),
            ) from exc

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


def _summarise(exc: ValidationError) -> str:
    """Render pydantic errors as a short, model-readable sentence."""
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "input"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
