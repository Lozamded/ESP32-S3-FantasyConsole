"""Play tab: corre el juego real (Lua 5.4, colision, camara) en vivo sobre el estado
en memoria del proyecto -- sin build/flash/SD, sin emulador. Ver
spec/lua/firmware-bridge-v0.md y play_runtime.py/play_lua_bridge.py para el porte del
runtime de firmware/TurtleReader/turtle_scene.cpp a Python."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QKeyEvent, QPainter
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from turtlestudio import play_lua_bridge as plb
from turtlestudio import play_runtime as pr
from turtlestudio.i18n import tr
from turtlestudio.project import MANIFEST_NAME, manifest_path, parse_viewport_from_manifest
from turtlestudio.scene_editor import _normalize_row, _rgba_floats_to_qimage
from turtlestudio.tiles import parse_tile_px_from_manifest

# Arrow keys -> D-pad; Z/X/C/V -> A/B/C/D (convencion tipo emulador SNES9x).
_KEYMAP: dict[int, int] = {
    Qt.Key.Key_Left: pr.BTN_LEFT,
    Qt.Key.Key_Right: pr.BTN_RIGHT,
    Qt.Key.Key_Up: pr.BTN_UP,
    Qt.Key.Key_Down: pr.BTN_DOWN,
    Qt.Key.Key_Z: pr.BTN_A,
    Qt.Key.Key_X: pr.BTN_B,
    Qt.Key.Key_C: pr.BTN_C,
    Qt.Key.Key_V: pr.BTN_D,
}


class PlayCanvas(QWidget):
    """Pinta el ultimo frame RGBA y mantiene el set de botones sostenidos via teclado."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image = None
        self._fw = pr.VIEWPORT_PIXEL_W
        self._fh = pr.VIEWPORT_PIXEL_H
        self.zoom = 2
        self.held_indices: set[int] = set()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(self._fw * self.zoom, self._fh * self.zoom)

    def set_frame(self, image, fw: int, fh: int) -> None:
        self._image = image
        self._fw, self._fh = fw, fh
        self.setMinimumSize(max(1, fw) * self.zoom, max(1, fh) * self.zoom)
        self.update()

    def clear_frame(self) -> None:
        self._image = None
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._fw * self.zoom, self._fh * self.zoom)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self._image is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            target = self._image.scaled(
                self._fw * self.zoom,
                self._fh * self.zoom,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            painter.drawImage(0, 0, target)
        painter.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.isAutoRepeat():
            return
        btn = _KEYMAP.get(event.key())
        if btn is not None:
            self.held_indices.add(btn)
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.isAutoRepeat():
            return
        btn = _KEYMAP.get(event.key())
        if btn is not None:
            self.held_indices.discard(btn)
            return
        super().keyReleaseEvent(event)

    def reset_input(self) -> None:
        self.held_indices.clear()


class PlayWidget(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self._scenes: list[dict[str, Any]] = []
        self._active_id = ""
        self._project_target_fps = 30
        self._project_anim_fps = 8
        self._tile_px = 16
        self._viewport_w = pr.VIEWPORT_PIXEL_W
        self._viewport_h = pr.VIEWPORT_PIXEL_H
        self._entry_relpath = "scripts/global.lua"

        self.session: pr.PlaySession | None = None
        self._run_actor_scripts = None
        self._actor_bridge: plb.ActorLuaBridge | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._log_len = 0

        self._build_ui()

    # -- API publica, igual que los demas tabs -------------------------

    def set_project_root(self, root: Path) -> None:
        self.stop()
        self.project_root = root
        self.refresh()

    def refresh(self) -> None:
        try:
            data = json.loads(manifest_path(self.project_root).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.warning(self, tr("play.read_error_title"), tr("play.read_error_msg", manifest=MANIFEST_NAME, e=e))
            return
        self._tile_px = parse_tile_px_from_manifest(data)
        self._viewport_w, self._viewport_h = parse_viewport_from_manifest(data)
        self._project_target_fps = int(data.get("target_fps", 30) or 30)
        self._project_anim_fps = int(data.get("default_anim_fps", 8) or 8)
        raw_scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []
        self._scenes = [s for s in raw_scenes if isinstance(s, dict) and s.get("id")]
        self._active_id = str(data.get("active_scene", "")).strip()
        self._entry_relpath = str(data.get("entry", "scripts/global.lua"))
        self._refresh_scene_combo()
        self._update_availability()

    def stop_on_tab_away(self) -> None:
        self.stop()

    # -- ui ---------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #c0392b;")
        self._status_label.setVisible(False)
        outer.addWidget(self._status_label)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(tr("play.scene_label")))
        self.scene_combo = QComboBox()
        self.scene_combo.currentIndexChanged.connect(self._on_scene_changed)
        toolbar.addWidget(self.scene_combo, stretch=1)

        self.play_button = QPushButton(tr("play.play_button"))
        self.play_button.clicked.connect(self._on_play_clicked)
        self.play_button.setEnabled(False)
        toolbar.addWidget(self.play_button)

        self.pause_button = QPushButton(tr("play.pause_button"))
        self.pause_button.clicked.connect(self._on_pause_clicked)
        self.pause_button.setEnabled(False)
        toolbar.addWidget(self.pause_button)

        self.stop_button = QPushButton(tr("play.stop_button"))
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        toolbar.addWidget(self.stop_button)

        outer.addLayout(toolbar)

        legend = QLabel(tr("play.keymap_legend"))
        legend.setStyleSheet("color: #888; font-size: 11px;")
        outer.addWidget(legend)

        body = QHBoxLayout()
        self.canvas = PlayCanvas()
        body.addWidget(self.canvas, stretch=1)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumWidth(320)
        self.log_view.setPlaceholderText(tr("play.log_placeholder"))
        body.addWidget(self.log_view)

        outer.addLayout(body, stretch=1)

    def _update_availability(self) -> None:
        if not plb.lupa_available():
            self._status_label.setText(tr("play.lupa_unavailable", error=plb.lupa_import_error()))
            self._status_label.setVisible(True)
            self.play_button.setEnabled(False)
        else:
            self._status_label.setVisible(False)
            self.play_button.setEnabled(self.scene_combo.count() > 0)

    def _refresh_scene_combo(self) -> None:
        self.scene_combo.blockSignals(True)
        self.scene_combo.clear()
        ids = [s["id"] for s in self._scenes]
        for sid in ids:
            self.scene_combo.addItem(sid)
        if self._active_id in ids:
            self.scene_combo.setCurrentIndex(ids.index(self._active_id))
        elif ids:
            self.scene_combo.setCurrentIndex(0)
        self.scene_combo.blockSignals(False)

    def _on_scene_changed(self, _index: int) -> None:
        self.stop()

    # -- lifecycle ----------------------------------------------------

    def _on_play_clicked(self) -> None:
        if self.session is not None and self.session.active:
            self._timer.start(max(1, int(1000 / max(1, self._project_target_fps))))
            self.play_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.canvas.setFocus()
            return
        self._begin_session()

    def _begin_session(self) -> None:
        sid = self.scene_combo.currentText().strip()
        row_raw = next((s for s in self._scenes if s.get("id") == sid), None)
        if row_raw is None:
            return
        try:
            row = _normalize_row(row_raw, self._tile_px, viewport_w=self._viewport_w, viewport_h=self._viewport_h)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("common.error"), str(e))
            return

        self.session = pr.PlaySession(self.project_root)
        try:
            self.session.begin(
                row,
                self._tile_px,
                project_target_fps=self._project_target_fps,
                project_anim_fps=self._project_anim_fps,
                viewport_w=self._viewport_w,
                viewport_h=self._viewport_h,
            )
            entry_bridge = plb.EntryLuaBridge(self.session)
            entry_bridge.run(self._entry_relpath)
            self._run_actor_scripts, self._actor_bridge = plb.make_run_actor_scripts(self.session)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("play.start_error_title"), str(e))
            self.session = None
            return

        self._log_len = 0
        self.log_view.clear()
        self.canvas.reset_input()
        self.canvas.setFocus()
        self._flush_log()

        self.play_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.scene_combo.setEnabled(False)
        self._timer.start(max(1, int(1000 / max(1, self._project_target_fps))))

    def _on_pause_clicked(self) -> None:
        self._timer.stop()
        self.play_button.setEnabled(True)
        self.pause_button.setEnabled(False)

    def stop(self) -> None:
        self._timer.stop()
        if self.session is not None:
            self.session.stop()
        self.session = None
        self._run_actor_scripts = None
        self._actor_bridge = None
        self.canvas.clear_frame()
        self.canvas.reset_input()
        self.play_button.setEnabled(self.scene_combo.count() > 0 and plb.lupa_available())
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.scene_combo.setEnabled(True)

    def _on_tick(self) -> None:
        if self.session is None or not self.session.active:
            self._timer.stop()
            return
        dt = max(1, int(1000 / max(1, self._project_target_fps))) / 1000.0
        try:
            self.session.input.set_held_indices(self.canvas.held_indices)
            self.session.tick(dt, self._run_actor_scripts)
            rgba, w, h = self.session.render_rgba()
        except Exception as e:  # noqa: BLE001
            self._timer.stop()
            QMessageBox.critical(self, tr("play.runtime_error_title"), str(e))
            self.stop()
            return
        image = _rgba_floats_to_qimage(rgba, w, h)
        self.canvas.set_frame(image, w, h)
        self._flush_log()

    def _flush_log(self) -> None:
        if self.session is None:
            return
        new = self.session.log[self._log_len :]
        if not new:
            return
        self._log_len = len(self.session.log)
        for line in new:
            self.log_view.appendPlainText(line)
