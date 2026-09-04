"""Export tab — wraps build.py's full project -> `.turtlecart`/SD-package pipeline."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from turtlestudio.build import (
    DEFAULT_PACKAGE_DIR_NAME,
    clean_export_package_dir,
    collect_studio_bundle_files,
    format_cart_package_log,
    inject_globals_into_lua,
    write_cart_package,
)
from turtlestudio.i18n import tr
from turtlestudio.palette_policy import TRANSPARENT_PALETTE_INDEX
from turtlestudio.project import manifest_path
from turtlestudio.verify_package import verify_package_dir

_VALID_LUA_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GV_TYPES = ("int", "float", "string", "bool")


class _GVRow(QWidget):
    """One row in the global vars table: name | type dropdown | array checkbox | delete."""

    def __init__(
        self,
        on_change,
        on_delete,
        *,
        name: str = "",
        type_: str = "int",
        is_array: bool = False,
        default: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.edit_name = QLineEdit(name)
        self.edit_name.setPlaceholderText(tr("build.gv_name_placeholder"))
        self.edit_name.editingFinished.connect(on_change)
        row.addWidget(self.edit_name, stretch=2)

        self.combo_type = QComboBox()
        self.combo_type.addItems(_GV_TYPES)
        if type_ in _GV_TYPES:
            self.combo_type.setCurrentText(type_)
        self.combo_type.currentTextChanged.connect(self._on_type_changed)
        self.combo_type.currentTextChanged.connect(on_change)
        row.addWidget(self.combo_type, stretch=1)

        self.edit_default = QLineEdit(default)
        self.edit_default.editingFinished.connect(on_change)
        row.addWidget(self.edit_default, stretch=1)

        self.chk_array = QCheckBox(tr("build.gv_col_array"))
        self.chk_array.setChecked(is_array)
        self.chk_array.stateChanged.connect(self._on_array_changed)
        self.chk_array.stateChanged.connect(on_change)
        row.addWidget(self.chk_array)

        btn_del = QPushButton("×")
        btn_del.setFixedWidth(26)
        btn_del.setToolTip(tr("build.gv_delete_tooltip"))
        btn_del.clicked.connect(on_delete)
        row.addWidget(btn_del)

        self._update_default_placeholder()

    def _type_default_placeholder(self) -> str:
        if self.chk_array.isChecked():
            return "{}"
        return {"int": "0", "float": "0.0", "string": '""', "bool": "false"}.get(
            self.combo_type.currentText(), "0"
        )

    def _update_default_placeholder(self) -> None:
        self.edit_default.setPlaceholderText(self._type_default_placeholder())

    def _on_type_changed(self) -> None:
        self._update_default_placeholder()

    def _on_array_changed(self) -> None:
        self._update_default_placeholder()

    def to_dict(self) -> dict | None:
        name = self.edit_name.text().strip()
        if not _VALID_LUA_IDENT.match(name):
            return None
        default = self.edit_default.text().strip()
        return {
            "name": name,
            "type": self.combo_type.currentText(),
            "is_array": self.chk_array.isChecked(),
            "default": default,
        }


class BuildDialogWidget(QWidget):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_root = project_root
        self._gv_rows: list[_GVRow] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_project_root(self, root: Path) -> None:
        self.project_root = root
        self.refresh()

    def refresh(self) -> None:
        data = self._read_manifest()
        self.edit_name.setText(str(data.get("name", "")))
        self.edit_shortname.setText(str(data.get("short_name", "")))
        self.combo_scene.blockSignals(True)
        self.combo_scene.clear()
        scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []
        ids = [str(s.get("id", "")).strip() for s in scenes if isinstance(s, dict) and s.get("id")]
        self.combo_scene.addItems(ids)
        active = str(data.get("active_scene", "")).strip()
        idx = self.combo_scene.findText(active)
        self.combo_scene.setCurrentIndex(max(0, idx))
        self.combo_scene.blockSignals(False)
        if not self.edit_output.text().strip():
            self.edit_output.setText(str(self.project_root / DEFAULT_PACKAGE_DIR_NAME))
        self._load_global_vars_ui(data.get("global_vars", []))
        self.log.clear()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr("build.name_label")))
        self.edit_name = QLineEdit()
        self.edit_name.editingFinished.connect(self._on_name_edited)
        name_row.addWidget(self.edit_name, stretch=1)
        name_row.addWidget(QLabel(tr("build.short_name_label")))
        self.edit_shortname = QLineEdit()
        self.edit_shortname.editingFinished.connect(self._on_shortname_edited)
        name_row.addWidget(self.edit_shortname, stretch=1)
        outer.addLayout(name_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel(tr("build.output_label")))
        self.edit_output = QLineEdit()
        out_row.addWidget(self.edit_output, stretch=1)
        self.btn_browse = QPushButton(tr("build.browse"))
        self.btn_browse.clicked.connect(self._action_browse_output)
        out_row.addWidget(self.btn_browse)
        outer.addLayout(out_row)

        scene_row = QHBoxLayout()
        scene_row.addWidget(QLabel(tr("build.initial_scene_label")))
        self.combo_scene = QComboBox()
        self.combo_scene.setMinimumWidth(160)
        scene_row.addWidget(self.combo_scene)
        scene_row.addStretch()
        outer.addLayout(scene_row)

        # --- Global variables section ---
        gv_group = QGroupBox(tr("build.global_vars_group"))
        gv_outer = QVBoxLayout(gv_group)
        gv_outer.setContentsMargins(6, 6, 6, 6)
        gv_outer.setSpacing(4)

        hdr_row = QHBoxLayout()
        hdr_row.addWidget(QLabel(tr("build.gv_col_name")), stretch=2)
        hdr_row.addWidget(QLabel(tr("build.gv_col_type")), stretch=1)
        hdr_row.addWidget(QLabel(tr("build.gv_col_default")), stretch=1)
        hdr_row.addSpacing(80)  # array checkbox + delete button
        gv_outer.addLayout(hdr_row)

        self._gv_scroll = QScrollArea()
        self._gv_scroll.setWidgetResizable(True)
        self._gv_scroll.setMaximumHeight(140)
        self._gv_container = QWidget()
        self._gv_layout = QVBoxLayout(self._gv_container)
        self._gv_layout.setContentsMargins(0, 0, 0, 0)
        self._gv_layout.setSpacing(2)
        self._gv_layout.addStretch(1)
        self._gv_scroll.setWidget(self._gv_container)
        gv_outer.addWidget(self._gv_scroll)

        btn_add = QPushButton(tr("build.gv_add"))
        btn_add.clicked.connect(self._action_add_global_var)
        gv_outer.addWidget(btn_add)

        outer.addWidget(gv_group)
        # --------------------------------

        self.chk_clean = QCheckBox(tr("build.clean_checkbox"))
        self.chk_clean.setChecked(True)
        outer.addWidget(self.chk_clean)

        btn_row = QHBoxLayout()
        self.btn_export = QPushButton(tr("build.export_button"))
        self.btn_export.clicked.connect(self._action_export)
        btn_row.addWidget(self.btn_export)
        self.btn_open_folder = QPushButton(tr("build.open_folder"))
        self.btn_open_folder.clicked.connect(self._action_open_folder)
        btn_row.addWidget(self.btn_open_folder)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet("font-family: monospace;")
        outer.addWidget(self.log, stretch=1)

    # ------------------------------------------------------------------
    # Global vars helpers
    # ------------------------------------------------------------------

    def _load_global_vars_ui(self, raw: object) -> None:
        for row in list(self._gv_rows):
            self._remove_row_widget(row)
        self._gv_rows.clear()
        if not isinstance(raw, list):
            return
        for v in raw:
            if not isinstance(v, dict):
                continue
            self._append_row(
                name=str(v.get("name", "")),
                type_=str(v.get("type", "int")),
                is_array=bool(v.get("is_array", False)),
                default=str(v.get("default", "")),
            )

    def _append_row(self, *, name: str = "", type_: str = "int", is_array: bool = False, default: str = "") -> _GVRow:
        row = _GVRow(
            self._on_global_vars_changed,
            lambda: self._action_delete_global_var(row),
            name=name,
            type_=type_,
            is_array=is_array,
            default=default,
        )
        self._gv_rows.append(row)
        # insert before the trailing stretch
        self._gv_layout.insertWidget(self._gv_layout.count() - 1, row)
        return row

    def _remove_row_widget(self, row: _GVRow) -> None:
        self._gv_layout.removeWidget(row)
        row.setParent(None)  # type: ignore[arg-type]
        row.deleteLater()

    def _collect_global_vars(self) -> list[dict]:
        result = []
        seen: set[str] = set()
        for row in self._gv_rows:
            d = row.to_dict()
            if d is None or d["name"] in seen:
                continue
            seen.add(d["name"])
            result.append(d)
        return result

    def _on_global_vars_changed(self) -> None:
        self._write_manifest_field("global_vars", self._collect_global_vars())

    def _action_add_global_var(self) -> None:
        self._append_row()
        self._on_global_vars_changed()

    def _action_delete_global_var(self, row: _GVRow) -> None:
        if row in self._gv_rows:
            self._gv_rows.remove(row)
        self._remove_row_widget(row)
        self._on_global_vars_changed()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_manifest(self) -> dict:
        try:
            return json.loads(manifest_path(self.project_root).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def _write_manifest_field(self, key: str, value) -> None:
        mp = manifest_path(self.project_root)
        data = self._read_manifest()
        data[key] = value
        mp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # Slots / actions
    # ------------------------------------------------------------------

    def _on_name_edited(self) -> None:
        name = self.edit_name.text().strip()
        if not name:
            self.edit_name.setText(str(self._read_manifest().get("name", "")))
            return
        self.edit_name.setText(name)
        self._write_manifest_field("name", name)

    def _on_shortname_edited(self) -> None:
        short_name = self.edit_shortname.text().strip()
        self.edit_shortname.setText(short_name)
        self._write_manifest_field("short_name", short_name)

    def _action_browse_output(self) -> None:
        start = self.edit_output.text().strip() or str(self.project_root)
        path = QFileDialog.getExistingDirectory(self, tr("build.browse_title"), start)
        if path:
            self.edit_output.setText(path)

    def _action_open_folder(self) -> None:
        folder = Path(self.edit_output.text().strip() or str(self.project_root / DEFAULT_PACKAGE_DIR_NAME))
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _action_export(self) -> None:
        self.log.clear()
        if not manifest_path(self.project_root).is_file():
            QMessageBox.warning(self, tr("build.export_error_title"), tr("build.no_project_msg"))
            return
        data = self._read_manifest()
        if not data:
            QMessageBox.warning(self, tr("build.export_error_title"), tr("build.no_project_msg"))
            return

        entry_rel = str(data.get("entry", "scripts/global.lua")).strip() or "scripts/global.lua"
        entry_path = self.project_root / entry_rel
        if not entry_path.is_file():
            QMessageBox.warning(
                self, tr("build.export_error_title"), tr("build.entry_missing_msg", path=entry_path)
            )
            return
        entry_body = entry_path.read_text(encoding="utf-8")

        global_vars = self._collect_global_vars()
        entry_body = inject_globals_into_lua(entry_body, global_vars)

        scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []
        chosen_scene = self.combo_scene.currentText().strip() or str(data.get("active_scene", "")).strip()
        if not chosen_scene:
            QMessageBox.warning(self, tr("build.export_error_title"), tr("build.no_scenes_msg"))
            return

        pal_rel = data.get("default_palette")
        pal_path = (self.project_root / pal_rel).resolve() if isinstance(pal_rel, str) and pal_rel else None

        output_text = self.edit_output.text().strip() or str(self.project_root / DEFAULT_PACKAGE_DIR_NAME)
        output = Path(output_text)

        try:
            if self.chk_clean.isChecked():
                clean_export_package_dir(output, project_root=self.project_root)

            pkg = collect_studio_bundle_files(
                self.project_root,
                scenes=scenes,
                active_scene=chosen_scene,
                transparent_index=TRANSPARENT_PALETTE_INDEX,
                entry_relpath=entry_rel,
            )
            result = write_cart_package(
                output,
                entry_relpath=entry_rel,
                main_lua_body=entry_body,
                palette_path=pal_path,
                embedded_files=pkg.embedded,
                sidecar_files=pkg.sidecar,
                initial_scene=chosen_scene,
            )
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, tr("build.export_error_title"), str(e))
            self._append_log(f"ERROR: {e}")
            return

        self._append_log(format_cart_package_log(result, initial_scene=chosen_scene))
        if pkg.lua_export_notes:
            self._append_log(tr("build.lua_notes_header"))
            for note in pkg.lua_export_notes:
                self._append_log(note)

        errors = verify_package_dir(result.package_dir)
        if errors:
            self._append_log(tr("build.verify_failed_header", n=len(errors)))
            for e in errors:
                self._append_log(f"  - {e}")
        else:
            self._append_log(tr("build.verify_ok"))
