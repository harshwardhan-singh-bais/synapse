"""
TUI Layout Engine — four node kinds for composing the Synapse interface.

Node kinds:
- Panel: A container with a title and border
- Split: Divides space horizontally or vertically between children
- Spacer: An empty space filler
- Widget: A leaf node wrapping a Textual widget
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class NodeKind(str, Enum):
    PANEL = "panel"
    SPLIT = "split"
    SPACER = "spacer"
    WIDGET = "widget"


class Direction(str, Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


@dataclass
class LayoutNode:
    """A node in the layout tree."""
    kind: NodeKind
    name: str = ""
    title: str = ""
    direction: Direction = Direction.VERTICAL
    children: list[LayoutNode] = field(default_factory=list)
    widget_id: str = ""
    size: str = "1fr"  # CSS-like size: "1fr", "200", "30%", etc.
    min_size: Optional[str] = None
    max_size: Optional[str] = None
    visible: bool = True
    style: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


def panel(name: str, title: str = "", children: list[LayoutNode] | None = None,
          size: str = "1fr", **style: str) -> LayoutNode:
    """Create a Panel node."""
    return LayoutNode(
        kind=NodeKind.PANEL,
        name=name,
        title=title,
        children=children or [],
        size=size,
        style=dict(style),
    )


def split(direction: Direction, children: list[LayoutNode] | None = None,
          size: str = "1fr", name: str = "") -> LayoutNode:
    """Create a Split node."""
    return LayoutNode(
        kind=NodeKind.SPLIT,
        name=name,
        direction=direction,
        children=children or [],
        size=size,
    )


def widget(name: str, widget_id: str, size: str = "1fr") -> LayoutNode:
    """Create a Widget leaf node."""
    return LayoutNode(
        kind=NodeKind.WIDGET,
        name=name,
        widget_id=widget_id,
        size=size,
    )


def spacer(size: str = "0") -> LayoutNode:
    """Create a Spacer node."""
    return LayoutNode(kind=NodeKind.SPACER, size=size)


def horizontal(*children: LayoutNode, name: str = "", size: str = "1fr") -> LayoutNode:
    """Convenience: create a horizontal split."""
    return split(Direction.HORIZONTAL, list(children), size=size, name=name)


def vertical(*children: LayoutNode, name: str = "", size: str = "1fr") -> LayoutNode:
    """Convenience: create a vertical split."""
    return split(Direction.VERTICAL, list(children), size=size, name=name)


class LayoutEngine:
    """Manages a layout tree and converts it to Textual CSS."""

    def __init__(self) -> None:
        self.root: Optional[LayoutNode] = None

    def set_root(self, node: LayoutNode) -> None:
        self.root = node

    def to_css(self) -> str:
        """Generate Textual CSS from the layout tree."""
        if self.root is None:
            return ""
        lines: list[str] = [f"/* Auto-generated layout CSS */"]
        self._node_to_css(self.root, lines, "")
        return "\n".join(lines)

    def _node_to_css(self, node: LayoutNode, lines: list[str], prefix: str) -> None:
        selector = f"{prefix}#{node.name}" if node.name else prefix

        if node.kind == NodeKind.WIDGET:
            if node.widget_id:
                lines.append(f"#{node.widget_id} {{")
                lines.append(f"    width: {node.size};")
                if node.min_size:
                    lines.append(f"    min-width: {node.min_size};")
                if node.max_size:
                    lines.append(f"    max-width: {node.max_size};")
                for k, v in node.style.items():
                    lines.append(f"    {k}: {v};")
                lines.append("}")

        elif node.kind == NodeKind.PANEL:
            if selector:
                lines.append(f"{selector} {{")
                lines.append(f"    width: {node.size};")
                for k, v in node.style.items():
                    lines.append(f"    {k}: {v};")
                lines.append("}")

        elif node.kind == NodeKind.SPLIT:
            layout_value = "horizontal" if node.direction == Direction.HORIZONTAL else "vertical"
            if selector:
                lines.append(f"{selector} {{")
                lines.append(f"    layout: {layout_value};")
                lines.append(f"    width: {node.size};")
                lines.append("}")

        for child in node.children:
            self._node_to_css(child, lines, prefix)

    def flatten(self) -> list[LayoutNode]:
        """Flatten the tree into a list of all nodes."""
        if self.root is None:
            return []
        result: list[LayoutNode] = []
        self._flatten(self.root, result)
        return result

    def _flatten(self, node: LayoutNode, result: list[LayoutNode]) -> None:
        result.append(node)
        for child in node.children:
            self._flatten(child, result)

    def find(self, name: str) -> Optional[LayoutNode]:
        """Find a node by name."""
        if self.root is None:
            return None
        return self._find(self.root, name)

    def _find(self, node: LayoutNode, name: str) -> Optional[LayoutNode]:
        if node.name == name:
            return node
        for child in node.children:
            found = self._find(child, name)
            if found:
                return found
        return None

    def toggle(self, name: str) -> bool:
        """Toggle visibility of a node by name. Returns the new visibility state."""
        node = self.find(name)
        if node:
            node.visible = not node.visible
            return node.visible
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Default Synapse layout
# ──────────────────────────────────────────────────────────────────────────────


def default_synapse_layout() -> LayoutNode:
    """Return the default Synapse TUI layout."""
    return horizontal(
        vertical(
            widget("Sidebar", "sidebar", size="28"),
        ),
        vertical(
            widget("Tabs", "main-tabs", size="1fr"),
        ),
        name="app-layout",
        size="1fr",
    )
