"""Collapsible sidebar section for TurtleStudio property panels."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """Header button that expands/collapses a content area."""

    def __init__(
        self,
        title: str,
        *,
        expanded: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._toggle = QToolButton(self)
        self._toggle.setText(title)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(expanded)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setSizePolicy(
            self._toggle.sizePolicy().horizontalPolicy(),
            self._toggle.sizePolicy().verticalPolicy(),
        )
        self._toggle.setStyleSheet(
            "QToolButton { border: none; font-weight: bold; padding: 6px 4px; text-align: left; }"
            "QToolButton:hover { background-color: rgba(255, 255, 255, 24); }"
        )
        self._toggle.clicked.connect(self._on_clicked)

        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 0, 0, 8)
        self._content_layout.setSpacing(4)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._toggle)
        layout.addWidget(self._content)

        self.set_expanded(expanded)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def is_expanded(self) -> bool:
        return self._toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._toggle.setChecked(expanded)
        self._content.setVisible(expanded)
        self._toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _on_clicked(self) -> None:
        self.set_expanded(self._toggle.isChecked())
