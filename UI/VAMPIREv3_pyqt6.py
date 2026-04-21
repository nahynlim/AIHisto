"""
PyQt6-based VAMPIRE GUI.

This is a separate entrypoint from VAMPIREv2.py so the current Tkinter GUI
remains untouched. The new GUI adds a startup checklist that lets the user
choose which workflows to show:
    - Segmentation
    - Masking
    - Build Model
    - Apply Model
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from generate_vampire_input_csv import create_vampire_input_csv
from matlab_mask_runner import run_matlab_mask_job
from vampire.getboundary import getboundary
from vampire.mainbody import mainbody


IMAGE_EXTENSIONS = {".tiff", ".tif", ".jpeg", ".jpg", ".png", ".bmp", ".gif"}
MASK_SUFFIX_MAP = {
    "damaged": "_BWdam",
    "undamaged": "_BWnotDam",
    "low_shg": "_BWlowSHG",
    "high_shg": "_BWhighSHG",
}


def iter_image_files(folder, tag=None):
    folder_path = Path(folder)
    if not folder_path.exists():
        return []

    tag_text = str(tag).lower().strip() if tag is not None else ""
    image_paths = []
    for path in sorted(folder_path.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if tag_text and tag_text not in path.name.lower():
            continue
        image_paths.append(path)
    return image_paths


def collect_image_paths(image_input):
    if not image_input:
        return []

    if isinstance(image_input, (list, tuple)):
        image_paths = []
        for item in image_input:
            path = Path(item)
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                image_paths.append(path)
        return sorted(image_paths)

    path = Path(image_input)
    if path.is_dir():
        return iter_image_files(path)
    if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
        return [path]
    return []


def configure_cellprofiler_pipeline(pipeline_path, output_dir, export_mode):
    pipeline_path = Path(pipeline_path)
    if pipeline_path.suffix.lower() != ".cppipe":
        return str(pipeline_path)

    export_flags = {
        "Both": (True, True),
        "Images Only": (True, False),
        "Spreadsheet Only": (False, True),
    }
    save_images, save_spreadsheet = export_flags.get(export_mode, (True, True))
    output_dir = str(Path(output_dir).resolve()).replace("\\", "/")

    lines = pipeline_path.read_text(encoding="utf-8").splitlines()
    updated_lines = []
    current_module = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("ExportToSpreadsheet:["):
            current_module = "ExportToSpreadsheet"
            line = line.replace("|enabled:True|", f"|enabled:{'True' if save_spreadsheet else 'False'}|")
        elif stripped.startswith("SaveImages:["):
            current_module = "SaveImages"
            line = line.replace("|enabled:True|", f"|enabled:{'True' if save_images else 'False'}|")
        elif stripped.endswith(":[module_num:1|svn_version:'Unknown'|variable_revision_number:2|show_window:False|notes:['To begin creating your project, use the Images module to compile a list of files and/or folders that you want to analyze. You can also specify a set of rules to include only the desired files in your selected folders.']|batch_state:array([], dtype=uint8)|enabled:True|wants_pause:False]"):
            current_module = "Images"
        elif stripped and not line.startswith(" ") and not line.startswith("\t"):
            current_module = None

        if current_module in {"ExportToSpreadsheet", "SaveImages"} and stripped.startswith("Output file location:"):
            line = f"    Output file location:Elsewhere...|{output_dir}"

        updated_lines.append(line)

    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".cppipe",
        prefix="segmentation_run_",
        delete=False,
        encoding="utf-8",
        dir=output_dir,
    )
    try:
        temp_file.write("\n".join(updated_lines) + "\n")
    finally:
        temp_file.close()
    return temp_file.name


def prepare_cellprofiler_input_dir(image_input, image_paths, output_dir):
    if not image_input:
        raise ValueError("Image input is required.")

    if isinstance(image_input, (list, tuple)):
        selected_paths = [Path(path) for path in image_paths]
        if not selected_paths:
            raise ValueError("No valid images were selected.")

        source_dirs = {str(path.parent.resolve()) for path in selected_paths}
        if len(source_dirs) != 1:
            raise ValueError("Selected images must come from the same folder.")

        staging_dir = Path(output_dir) / "_cellprofiler_input"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        for source_path in selected_paths:
            shutil.copy2(source_path, staging_dir / source_path.name)
        return str(staging_dir)

    image_input_path = Path(image_input)
    if image_input_path.is_dir():
        return str(image_input_path)
    if image_input_path.is_file():
        staging_dir = Path(output_dir) / "_cellprofiler_input"
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_input_path, staging_dir / image_input_path.name)
        return str(staging_dir)

    raise ValueError("Could not prepare CellProfiler input directory.")


def cleanup_cellprofiler_temp_artifacts(image_input, input_dir, original_pipeline_path, configured_pipeline_path):
    input_dir_path = Path(input_dir) if input_dir else None
    original_pipeline = Path(original_pipeline_path).resolve() if original_pipeline_path else None
    configured_pipeline = Path(configured_pipeline_path).resolve() if configured_pipeline_path else None

    uses_direct_folder_input = not isinstance(image_input, (list, tuple)) and Path(image_input).is_dir()
    if input_dir_path is not None and not uses_direct_folder_input:
        if input_dir_path.name == "_cellprofiler_input" and input_dir_path.exists():
            shutil.rmtree(input_dir_path, ignore_errors=True)

    if (
        configured_pipeline is not None
        and configured_pipeline.exists()
        and configured_pipeline.suffix.lower() == ".cppipe"
        and configured_pipeline.name.startswith("segmentation_run_")
        and configured_pipeline != original_pipeline
    ):
        try:
            configured_pipeline.unlink()
        except OSError:
            pass


def get_default_cp_executable():
    windows_lnk = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\CellProfiler.lnk"
    if os.path.isfile(windows_lnk):
        return windows_lnk
    mac_app = "/Applications/CellProfiler.app"
    if os.path.isdir(mac_app):
        return mac_app
    mac_cp = "/Applications/CellProfiler.app/Contents/MacOS/cp"
    if os.path.isfile(mac_cp):
        return mac_cp
    return "cellprofiler"


def resolve_cp_executable(cp_exec):
    if not cp_exec:
        return cp_exec
    if sys.platform == "darwin" and cp_exec.lower().endswith(".app"):
        inner_cp = os.path.join(cp_exec, "Contents", "MacOS", "cp")
        if os.path.isfile(inner_cp):
            return inner_cp
        return cp_exec
    if not cp_exec.lower().endswith(".lnk"):
        return cp_exec

    escaped = cp_exec.replace("'", "''")
    ps_cmd = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{escaped}'); "
        "Write-Output $s.TargetPath"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        text=True,
    )
    target = (result.stdout or "").strip()
    if result.returncode == 0 and target:
        return target
    return cp_exec


def cp_executable_exists(cp_exec):
    if not cp_exec:
        return False
    if sys.platform == "darwin":
        if cp_exec.lower().endswith(".app"):
            return os.path.isdir(cp_exec)
        if cp_exec in {"cellprofiler", "CellProfiler"} and shutil.which("open") is not None:
            return True
    return os.path.isfile(cp_exec) or shutil.which(cp_exec) is not None


def build_cp_command(cp_exec, pipeline_path=None):
    if sys.platform == "darwin":
        if cp_exec.lower().endswith(".app"):
            cmd = ["open", cp_exec]
            if pipeline_path:
                cmd.extend(["--args", "-p", pipeline_path])
            return cmd
        if cp_exec in {"cellprofiler", "CellProfiler"} and shutil.which(cp_exec) is None and shutil.which("open") is not None:
            cmd = ["open", "-a", "CellProfiler"]
            if pipeline_path:
                cmd.extend(["--args", "-p", pipeline_path])
            return cmd

    cmd = [cp_exec]
    if pipeline_path:
        cmd.extend(["-p", pipeline_path])
    return cmd


def resolve_masking_pipeline_preset():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "pipelines", "Masking_pipeline.cpproj"),
        os.path.join(base_dir, "pipelines", "Masking_pipeline.cppipe"),
        os.path.join(base_dir, "Masking_pipeline.cpproj"),
        os.path.join(base_dir, "Masking_pipeline.cppipe"),
        os.path.join(os.getcwd(), "pipelines", "Masking_pipeline.cpproj"),
        os.path.join(os.getcwd(), "pipelines", "Masking_pipeline.cppipe"),
        os.path.join(os.getcwd(), "Masking_pipeline.cpproj"),
        os.path.join(os.getcwd(), "Masking_pipeline.cppipe"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


class LegacyTextAdapter:
    def __init__(self, getter=None, setter=None):
        self._getter = getter or (lambda: "")
        self._setter = setter

    def get(self):
        return self._getter()

    def delete(self, *_):
        if self._setter is not None:
            self._setter("")

    def insert(self, _, value):
        if self._setter is not None:
            self._setter(str(value))


class QtProgressAdapter:
    def __init__(self, status_callback, status_message_getter):
        self.status_callback = status_callback
        self.status_message_getter = status_message_getter
        self.value = 0

    def __setitem__(self, key, value):
        if key == "value":
            self.value = max(0, min(100, int(float(value))))
            self.status_callback(
                self.status_message_getter() or "Processing...",
                "processing",
                self.value,
            )

    def update(self):
        return


class WorkerSignals(QObject):
    status = pyqtSignal(str, str, int)
    info = pyqtSignal(str, str)
    error = pyqtSignal(str, str)
    modelBuilt = pyqtSignal(dict)


class PathPicker(QWidget):
    def __init__(self, label, mode="file", file_filter="All Files (*)", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.file_filter = file_filter
        self._value = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.label = QLabel(label)
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.button = QPushButton("Browse")
        self.button.clicked.connect(self.choose_path)

        row = QHBoxLayout()
        row.addWidget(self.edit, 1)
        row.addWidget(self.button)

        layout.addWidget(self.label)
        layout.addLayout(row)

    def choose_path(self):
        if self.mode == "folder":
            folder = QFileDialog.getExistingDirectory(self, "Choose Folder")
            if folder:
                self.set_value(folder)
        elif self.mode == "files":
            files, _ = QFileDialog.getOpenFileNames(self, "Choose Files", "", self.file_filter)
            if files:
                self.set_value(files)
        else:
            file_path, _ = QFileDialog.getOpenFileName(self, "Choose File", "", self.file_filter)
            if file_path:
                self.set_value(file_path)

    def set_value(self, value):
        self._value = value
        if isinstance(value, (list, tuple)):
            if not value:
                self.edit.clear()
            elif len(value) == 1:
                self.edit.setText(str(value[0]))
            else:
                self.edit.setText(f"{len(value)} files selected")
        else:
            self.edit.setText(str(value))

    def value(self):
        return self._value


class StartupChecklistDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose Workflow Panels")
        self.setModal(True)
        self.resize(420, 260)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose what you want to do in this session. "
            "The GUI will only show the panels you need."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.segmentation = QCheckBox("Segmentation")
        self.masking = QCheckBox("Masking")
        self.mask_pipeline = QCheckBox("Apply Mask")
        self.build_model = QCheckBox("Build Model")
        self.apply_model = QCheckBox("Apply Model")

        for checkbox in (self.segmentation, self.masking, self.mask_pipeline, self.build_model, self.apply_model):
            checkbox.setChecked(True)
            layout.addWidget(checkbox)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        continue_btn = QPushButton("Continue")
        cancel_btn.clicked.connect(self.reject)
        continue_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(continue_btn)
        layout.addStretch(1)
        layout.addLayout(buttons)

    def selected_panels(self):
        return {
            "segmentation": self.segmentation.isChecked(),
            "masking": self.masking.isChecked(),
            "mask_pipeline": self.mask_pipeline.isChecked(),
            "build_model": self.build_model.isChecked(),
            "apply_model": self.apply_model.isChecked(),
        }


class PanelBox(QGroupBox):
    def __init__(self, title, subtitle=None, parent=None):
        super().__init__(title.upper(), parent)
        self.setStyleSheet(
            """
            QGroupBox {
                font-weight: 700;
            }
            """
        )
        layout = QVBoxLayout(self)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setStyleSheet("color: white; font-size: 14px;")
            layout.addWidget(subtitle_label)
        self.body_layout = layout


class NoWheelComboBox(QComboBox):
    """Prevent accidental value changes while scrolling the main window."""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoWheelSpinBox(QSpinBox):
    """Prevent accidental value changes while scrolling the main window."""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


def make_info_label(text: str) -> QLabel:
    label = QLabel("i")
    label.setToolTip(text)
    label.setStyleSheet(
        "color: white; background: transparent; font-weight: 700; "
        "padding: 0 2px; min-width: 10px;"
    )
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def add_labeled_row(layout: QFormLayout, label_text: str, widget, tooltip: Optional[str] = None):
    label_widget = QWidget()
    row = QHBoxLayout(label_widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    text_label = QLabel(label_text)
    row.addWidget(text_label)
    if tooltip:
        row.addWidget(make_info_label(tooltip))
    row.addStretch(1)
    layout.addRow(label_widget, widget)


def add_checkbox_with_info(layout, checkbox: QCheckBox, tooltip: str):
    row_widget = QWidget()
    row = QHBoxLayout(row_widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(checkbox)
    row.addWidget(make_info_label(tooltip))
    row.addStretch(1)
    layout.addWidget(row_widget)


class SegmentationPanel(PanelBox):
    def __init__(self, status_callback, parent=None):
        super().__init__(
            "Segmentation",
            "Run CellProfiler headlessly or open it interactively with the chosen segmentation pipeline.",
            parent,
        )
        self.status_callback = status_callback
        self.valid_pipeline_ext = {".cppipe"}
        self.pipeline_presets = {
            "Blue Stained DAPI": "Blue_Nuclei_Segmentation_Pipeline.cppipe",
            "Normal Staining": "Nuclei_Segmentation_Pipeline.cppipe",
        }
        self.launch_option = "Open CellProfiler Only"

        self.images_picker = PathPicker(
            "Images",
            mode="files",
            file_filter="Images (*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.gif)",
        )
        self.body_layout.addWidget(self.images_picker)
        self.images_picker.label.setToolTip(
            "Choose one or more image files. If you select files, CellProfiler will stage only those files for the run."
        )

        form = QFormLayout()
        self.run_mode = NoWheelComboBox()
        self.run_mode.addItems(["Run Headless", "Open CellProfiler"])
        self.export_mode = NoWheelComboBox()
        self.export_mode.addItems(["Both", "Images Only", "Spreadsheet Only"])
        self.pipeline_choice = NoWheelComboBox()
        self.pipeline_choice.addItems(list(self.pipeline_presets.keys()) + [self.launch_option])
        self.cp_executable = QLineEdit(get_default_cp_executable())
        cp_exec_row = QHBoxLayout()
        cp_exec_row.addWidget(self.cp_executable, 1)
        cp_exec_browse = QPushButton("Browse")
        cp_exec_browse.clicked.connect(self.browse_cp_executable)
        cp_exec_row.addWidget(cp_exec_browse)
        add_labeled_row(
            form,
            "Run Mode",
            self.run_mode,
            "Run Headless executes the selected pipeline automatically. Open CellProfiler launches the app for manual review or execution.",
        )
        add_labeled_row(
            form,
            "Export Mode",
            self.export_mode,
            "Both saves segmented images and spreadsheet outputs. Images Only saves only image exports. Spreadsheet Only saves only measurement tables.",
        )
        add_labeled_row(
            form,
            "Pipeline",
            self.pipeline_choice,
            "Choose the segmentation pipeline preset. Headless mode requires a .cppipe pipeline.",
        )
        add_labeled_row(
            form,
            "CellProfiler Executable",
            cp_exec_row,
            "Path to CellProfiler, such as CellProfiler.exe on Windows or CellProfiler.app / Contents/MacOS/cp on macOS.",
        )
        self.body_layout.addLayout(form)

        self.output_picker = PathPicker("Segmented Output Folder", mode="folder")
        self.output_picker.set_value(str(Path("./results/segmentation").resolve()))
        self.output_picker.label.setToolTip("Choose where CellProfiler should write segmented images and exported tables.")
        self.body_layout.addWidget(self.output_picker)

        start_btn = QPushButton("Start Segmentation")
        start_btn.clicked.connect(self.start_segmentation)
        self.body_layout.addWidget(start_btn)

    def browse_cp_executable(self):
        exe, _ = QFileDialog.getOpenFileName(self, "Choose CellProfiler Executable")
        if exe:
            self.cp_executable.setText(exe)

    def build_cp_command(self, cp_exec, pipeline_path=None, *, run_headless=False, input_dir=None, output_dir=None):
        if run_headless:
            cmd = [cp_exec, "-c", "-r"]
            if pipeline_path:
                cmd.extend(["-p", pipeline_path])
            if input_dir:
                cmd.extend(["-i", input_dir])
            if output_dir:
                cmd.extend(["-o", output_dir])
            return cmd

        if sys.platform == "darwin":
            if cp_exec.lower().endswith(".app"):
                cmd = ["open", cp_exec]
                if pipeline_path:
                    cmd.extend(["--args", "-p", pipeline_path])
                return cmd
            if cp_exec in {"cellprofiler", "CellProfiler"} and shutil.which(cp_exec) is None and shutil.which("open") is not None:
                cmd = ["open", "-a", "CellProfiler"]
                if pipeline_path:
                    cmd.extend(["--args", "-p", pipeline_path])
                return cmd

        cmd = [cp_exec]
        if pipeline_path:
            cmd.extend(["-p", pipeline_path])
        return cmd

    def resolve_preset_pipeline(self, filename):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base_dir, "pipelines", filename),
            os.path.join(base_dir, filename),
            os.path.join(os.getcwd(), "pipelines", filename),
            os.path.join(os.getcwd(), filename),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None

    def resolve_pipeline_path(self):
        choice = self.pipeline_choice.currentText()
        if choice == self.launch_option:
            return None
        preset_filename = self.pipeline_presets.get(choice)
        return self.resolve_preset_pipeline(preset_filename) if preset_filename else None

    def start_segmentation(self):
        cp_exec = resolve_cp_executable(self.cp_executable.text().strip())
        pipeline_choice = self.pipeline_choice.currentText()
        pipeline_path = self.resolve_pipeline_path()
        run_headless = self.run_mode.currentText() == "Run Headless"
        image_input = self.images_picker.value()
        output_dir = self.output_picker.value()
        export_mode = self.export_mode.currentText()

        if not cp_executable_exists(cp_exec):
            QMessageBox.critical(self, "CellProfiler Not Found", f"CellProfiler executable not found:\n{cp_exec}")
            return

        if pipeline_choice != self.launch_option:
            if not pipeline_path or not os.path.isfile(pipeline_path):
                QMessageBox.critical(self, "Pipeline Not Found", "Please choose a valid .cppipe segmentation pipeline.")
                return
            if Path(pipeline_path).suffix.lower() not in self.valid_pipeline_ext:
                QMessageBox.critical(self, "Invalid Pipeline", "Segmentation pipeline must be a .cppipe file.")
                return

        image_paths = collect_image_paths(image_input)
        if not image_paths:
            QMessageBox.critical(self, "No Images Found", "Please select one or more supported image files.")
            return

        if not output_dir:
            QMessageBox.critical(self, "Missing Output Folder", "Please choose a segmentation output folder.")
            return

        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Output Error", f"Could not create output folder:\n{exc}")
            return

        try:
            input_dir = prepare_cellprofiler_input_dir(image_input, image_paths, output_dir)
        except Exception as exc:
            QMessageBox.critical(self, "Input Preparation Failed", str(exc))
            return

        if run_headless and pipeline_choice == self.launch_option:
            QMessageBox.critical(self, "Pipeline Required", "Headless mode requires a segmentation pipeline.")
            return

        configured_pipeline_path = pipeline_path
        if pipeline_path:
            try:
                configured_pipeline_path = configure_cellprofiler_pipeline(pipeline_path, output_dir, export_mode)
            except Exception as exc:
                QMessageBox.critical(self, "Pipeline Configuration Failed", str(exc))
                return

        signals = WorkerSignals()
        signals.status.connect(self.status_callback)
        signals.info.connect(lambda title, text: QMessageBox.information(self, title, text))
        signals.error.connect(lambda title, text: QMessageBox.critical(self, title, text))

        def process():
            signals.status.emit("Initializing CellProfiler...", "processing", 10)
            env = os.environ.copy()
            env["MPLBACKEND"] = "Agg"
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)

            cmd = self.build_cp_command(
                cp_exec,
                configured_pipeline_path,
                run_headless=run_headless,
                input_dir=input_dir,
                output_dir=output_dir,
            )
            signals.status.emit(
                "Running CellProfiler headlessly..." if run_headless else "Launching CellProfiler interactively...",
                "processing",
                40,
            )
            try:
                if run_headless:
                    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
                else:
                    subprocess.Popen(cmd, env=env)
                    result = None
            except Exception as exc:
                signals.error.emit("Segmentation Failed", f"Could not start CellProfiler.\n\n{exc}")
                if run_headless:
                    cleanup_cellprofiler_temp_artifacts(image_input, input_dir, pipeline_path, configured_pipeline_path)
                return

            if run_headless and result and result.returncode != 0:
                stderr_tail = (result.stderr or "").strip()
                if len(stderr_tail) > 1200:
                    stderr_tail = stderr_tail[-1200:]
                cleanup_cellprofiler_temp_artifacts(image_input, input_dir, pipeline_path, configured_pipeline_path)
                signals.error.emit(
                    "Segmentation Failed",
                    f"Return code: {result.returncode}\n\nstderr:\n{stderr_tail or '(empty)'}",
                )
                return

            if run_headless:
                cleanup_cellprofiler_temp_artifacts(image_input, input_dir, pipeline_path, configured_pipeline_path)
                signals.status.emit("CellProfiler segmentation completed", "success", 100)
                signals.info.emit(
                    "Segmentation Complete",
                    f"Output folder:\n{output_dir}\n\nPipeline:\n{pipeline_choice}\nExport mode:\n{export_mode}",
                )
            else:
                signals.status.emit("CellProfiler launched", "success", 100)
                signals.info.emit(
                    "CellProfiler Launched",
                    f"CellProfiler: {cp_exec}\n"
                    f"Pipeline: {configured_pipeline_path if configured_pipeline_path else 'Choose in CellProfiler'}\n"
                    f"Output folder:\n{output_dir}",
                )

        threading.Thread(target=process, daemon=True).start()


class MaskingPanel(PanelBox):
    def __init__(self, status_callback, parent=None):
        super().__init__(
            "Masking",
            "Run the MATLAB-based SHG masking workflow and save only the outputs you need.",
            parent,
        )
        self.status_callback = status_callback
        self.rotation_mode_map = {
            "None": "none",
            "Vertical +90 Counterclockwise": "vertical",
            "Horizontal -90 Clockwise": "horizontal",
            "User Angle": "user",
        }

        self.images_picker = PathPicker(
            "SHG Images",
            mode="files",
            file_filter="Images (*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.gif)",
        )
        self.images_picker.label.setToolTip("Select one or more SHG image files for MATLAB masking.")
        self.body_layout.addWidget(self.images_picker)

        form = QFormLayout()
        self.bundle_width = QLineEdit("15")
        self.bundle_height = QLineEdit("15")
        self.low_shg = QLineEdit("10")
        self.mask_type = NoWheelComboBox()
        self.mask_type.addItems(["all", "damaged", "undamaged", "low_shg", "high_shg"])
        self.roi_mode = NoWheelComboBox()
        self.roi_mode.addItems(["auto", "draw", "none"])
        self.rotation_mode = NoWheelComboBox()
        self.rotation_mode.addItems(list(self.rotation_mode_map.keys()))
        self.user_angle = QLineEdit("0")
        add_labeled_row(
            form,
            "Bundle Width",
            self.bundle_width,
            "Tile size in pixels used for FFT orientation analysis. Larger values smooth more but reduce local detail.",
        )
        add_labeled_row(
            form,
            "Bundle Height",
            self.bundle_height,
            "Tile height in pixels used for FFT orientation analysis.",
        )
        add_labeled_row(
            form,
            "Low SHG Percentile",
            self.low_shg,
            "Threshold percentile derived from normalized SHG intensity. Lower values make the low-SHG mask more selective.",
        )
        add_labeled_row(
            form,
            "Mask Output Type",
            self.mask_type,
            "Choose which mask family to save. 'all' writes every supported mask output from the MATLAB run.",
        )
        add_labeled_row(
            form,
            "ROI Mode",
            self.roi_mode,
            "auto uses MATLAB ROI autodetection, draw opens a MATLAB polygon tool, and none analyzes the full image.",
        )
        rotation_widget = QWidget()
        rotation_layout = QHBoxLayout(rotation_widget)
        rotation_layout.setContentsMargins(0, 0, 0, 0)
        rotation_layout.setSpacing(8)
        rotation_layout.addWidget(self.rotation_mode, 1)
        angle_label = QLabel("User Angle")
        angle_label.setToolTip("Custom angle in degrees used when Rotation Mode is set to User Angle.")
        rotation_layout.addWidget(angle_label)
        self.user_angle.setMaximumWidth(90)
        rotation_layout.addWidget(self.user_angle)
        add_labeled_row(
            form,
            "Rotation Mode",
            rotation_widget,
            "Rotate the SHG image before analysis. Use User Angle for custom rotation in degrees.",
        )
        self.body_layout.addLayout(form)

        self.enhance = QCheckBox("Enhance Images")
        self.create_masks_box = QCheckBox("Create Masks")
        self.create_masks_box.setChecked(True)
        self.save_figures = QCheckBox("Save Figures")
        self.save_figures.setChecked(True)
        self.save_stats = QCheckBox("Save Stats TXT")
        self.save_stats.setChecked(True)
        self.save_roi = QCheckBox("Save ROI TIF")
        self.save_roi.setChecked(True)
        self.overwrite = QCheckBox("Overwrite Existing Files")
        self.overwrite.setChecked(True)
        checks_top = QHBoxLayout()
        add_checkbox_with_info(
            checks_top,
            self.enhance,
            "Apply sharpening and enhancement before MATLAB masking analysis.",
        )
        add_checkbox_with_info(
            checks_top,
            self.create_masks_box,
            "Create and save the selected mask outputs from the MATLAB run.",
        )
        add_checkbox_with_info(
            checks_top,
            self.save_figures,
            "Save MATLAB-generated QC figures such as quiver and histogram plots.",
        )
        self.body_layout.addLayout(checks_top)

        checks_bottom = QHBoxLayout()
        add_checkbox_with_info(
            checks_bottom,
            self.save_stats,
            "Write summary text outputs from the MATLAB masking workflow.",
        )
        add_checkbox_with_info(
            checks_bottom,
            self.save_roi,
            "Save the ROI mask image as a TIF output.",
        )
        add_checkbox_with_info(
            checks_bottom,
            self.overwrite,
            "Replace existing outputs if files with the same names already exist.",
        )
        self.body_layout.addLayout(checks_bottom)

        self.output_picker = PathPicker("Mask Output Folder", mode="folder")
        self.output_picker.set_value(str(Path("./results/masks").resolve()))
        self.output_picker.label.setToolTip("Choose where MATLAB should save masks, figures, and stats outputs.")
        self.body_layout.addWidget(self.output_picker)

        start_btn = QPushButton("Create Masks")
        start_btn.clicked.connect(self.create_masks)
        self.body_layout.addWidget(start_btn)

    def create_masks(self):
        shg_input = self.images_picker.value()
        out_dir = self.output_picker.value()
        if not shg_input:
            QMessageBox.critical(self, "Missing SHG Images", "Please select SHG images.")
            return
        if not out_dir:
            QMessageBox.critical(self, "Missing Output Folder", "Please select a mask output folder.")
            return

        try:
            bundle_width = float(self.bundle_width.text().strip() or "15")
            bundle_height = float(self.bundle_height.text().strip() or "15")
            low_shg_percentile = float(self.low_shg.text().strip() or "10")
            user_angle = float(self.user_angle.text().strip() or "0")
        except ValueError:
            QMessageBox.critical(self, "Invalid Parameters", "Bundle size, percentile, and angle must be valid numbers.")
            return

        roi_mode = self.roi_mode.currentText()
        rot_mode = self.rotation_mode_map.get(self.rotation_mode.currentText(), "none")

        signals = WorkerSignals()
        signals.status.connect(self.status_callback)
        signals.info.connect(lambda title, text: QMessageBox.information(self, title, text))
        signals.error.connect(lambda title, text: QMessageBox.critical(self, title, text))

        def process():
            try:
                if roi_mode == "draw":
                    signals.status.emit("MATLAB will open an ROI window for polygon drawing...", "processing", 50)
                run_matlab_mask_job(
                    shg_input,
                    out_dir,
                    bundle_width=bundle_width,
                    bundle_height=bundle_height,
                    do_enhance=self.enhance.isChecked(),
                    do_mask=self.create_masks_box.isChecked(),
                    save_figure=self.save_figures.isChecked(),
                    save_stats=self.save_stats.isChecked(),
                    save_roi=self.save_roi.isChecked(),
                    roi_mode=roi_mode,
                    mask_verts=None,
                    low_shg_percentile=low_shg_percentile,
                    rot_mode=rot_mode,
                    user_angle=user_angle,
                    mask_types=self.mask_type.currentText(),
                    overwrite_flag=self.overwrite.isChecked(),
                    status_callback=lambda msg, kind, prog: signals.status.emit(msg, kind, prog),
                )
                signals.info.emit("Masking Complete", f"MATLAB masking finished.\nOutput saved to:\n{out_dir}")
            except Exception as exc:
                signals.error.emit("Masking Failed", f"Error during MATLAB masking:\n{exc}")

        threading.Thread(target=process, daemon=True).start()


class MaskPipelinePanel(PanelBox):
    def __init__(self, status_callback, parent=None):
        super().__init__(
            "Apply Mask",
            "Open CellProfiler with the masking pipeline so SHG masks can be applied to staining images when needed.",
            parent,
        )
        self.status_callback = status_callback
        self.valid_pipeline_ext = {".cpproj", ".cppipe"}

        form = QFormLayout()
        cp_exec_row = QHBoxLayout()
        self.mask_cp_executable = QLineEdit(get_default_cp_executable())
        self.mask_cp_executable.setToolTip(
            "Path to CellProfiler, such as CellProfiler.exe on Windows or CellProfiler.app / Contents/MacOS/cp on macOS."
        )
        cp_exec_browse = QPushButton("Browse")
        cp_exec_browse.clicked.connect(self.browse_mask_cp_executable)
        cp_exec_row.addWidget(self.mask_cp_executable, 1)
        cp_exec_row.addWidget(cp_exec_browse)
        add_labeled_row(
            form,
            "CellProfiler Executable",
            cp_exec_row,
            "Executable used to open CellProfiler for the mask-application pipeline.",
        )

        preset_pipeline = resolve_masking_pipeline_preset()
        self.mask_pipeline_choice = NoWheelComboBox()
        self.mask_pipeline_choice.addItems(["Masking Pipeline", "Open CellProfiler"])
        self.mask_pipeline_choice.setCurrentText("Masking Pipeline" if preset_pipeline else "Open CellProfiler")
        add_labeled_row(
            form,
            "Masking Pipeline Option",
            self.mask_pipeline_choice,
            "Use the bundled masking pipeline preset when available, or simply open CellProfiler without a preset.",
        )
        self.body_layout.addLayout(form)

        launch_btn = QPushButton("Open Masking Pipeline")
        launch_btn.clicked.connect(self.start_masking_pipeline)
        self.body_layout.addWidget(launch_btn)

    def browse_mask_cp_executable(self):
        exe, _ = QFileDialog.getOpenFileName(self, "Choose CellProfiler Executable")
        if exe:
            self.mask_cp_executable.setText(exe)

    def resolve_selected_masking_pipeline(self):
        if self.mask_pipeline_choice.currentText() == "Open CellProfiler":
            return None
        return resolve_masking_pipeline_preset()

    def start_masking_pipeline(self):
        cp_exec = resolve_cp_executable(self.mask_cp_executable.text().strip())
        pipeline_path = self.resolve_selected_masking_pipeline()

        if not cp_executable_exists(cp_exec):
            QMessageBox.critical(self, "CellProfiler Not Found", f"CellProfiler executable not found:\n{cp_exec or '(empty)'}")
            return

        if self.mask_pipeline_choice.currentText() != "Open CellProfiler" and not pipeline_path:
            QMessageBox.critical(self, "Missing Pipeline", "Please place Masking_pipeline.cpproj or Masking_pipeline.cppipe in the project or pipelines folder.")
            return

        if pipeline_path and Path(pipeline_path).suffix.lower() not in self.valid_pipeline_ext:
            QMessageBox.critical(self, "Invalid Pipeline", "Masking pipeline must be a .cpproj or .cppipe file.")
            return

        signals = WorkerSignals()
        signals.status.connect(self.status_callback)
        signals.info.connect(lambda title, text: QMessageBox.information(self, title, text))
        signals.error.connect(lambda title, text: QMessageBox.critical(self, title, text))

        def process():
            signals.status.emit("Launching CellProfiler masking pipeline...", "processing", 20)
            cmd = build_cp_command(cp_exec, pipeline_path)
            try:
                subprocess.Popen(cmd)
            except Exception as exc:
                signals.error.emit("CellProfiler Launch Failed", f"Could not start CellProfiler.\n\n{exc}")
                return

            pipeline_text = f"Masking pipeline: {pipeline_path}\n" if pipeline_path else "Mode: Open CellProfiler only\n"
            signals.status.emit("CellProfiler masking pipeline launched", "success", 100)
            signals.info.emit(
                "CellProfiler Launched",
                f"CellProfiler: {cp_exec}\n{pipeline_text}Choose the staining-image input folder, mask folder, and output folder inside CellProfiler.",
            )

        threading.Thread(target=process, daemon=True).start()


class BuildModelPanel(PanelBox):
    def __init__(self, status_callback, on_model_built, parent=None):
        super().__init__(
            "Build Model",
            "Build a VAMPIRE shape model from a dataset CSV or directly from an image folder.",
            parent,
        )
        self.status_callback = status_callback
        self.on_model_built = on_model_built

        input_mode_form = QFormLayout()
        self.build_input_mode = NoWheelComboBox()
        self.build_input_mode.addItems(["CSV", "Folder"])
        self.build_input_mode.currentTextChanged.connect(self._toggle_inputs)
        add_labeled_row(
            input_mode_form,
            "Build Model Input Type",
            self.build_input_mode,
            "Choose whether Build Model should read a dataset CSV directly or auto-generate one from an image folder.",
        )
        self.body_layout.addLayout(input_mode_form)

        self.csv_picker = PathPicker("CSV File Input", mode="file", file_filter="CSV Files (*.csv)")
        self.image_picker = PathPicker("Image Folder", mode="folder")
        self.csv_picker.label.setToolTip("Upload a CSV file with headers like set ID/setID, condition, set location, tag, and note.")
        self.image_picker.label.setToolTip("Optional direct folder input. If no CSV is provided, the GUI will auto-generate a build-model CSV from this folder.")
        self.body_layout.addWidget(self.csv_picker)
        self.body_layout.addWidget(self.image_picker)

        form = QFormLayout()
        self.num_coords = QLineEdit("50")
        self.shape_modes = NoWheelSpinBox()
        self.shape_modes.setRange(1, 10)
        self.shape_modes.setValue(5)
        self.model_name = QLineEdit()
        add_labeled_row(
            form,
            "Number of Coordinates",
            self.num_coords,
            "Number of coordinate points used to define each boundary shape.",
        )
        add_labeled_row(
            form,
            "Number of Shape Modes",
            self.shape_modes,
            "Number of principal shape variations to capture in the model.",
        )
        add_labeled_row(
            form,
            "Model Name",
            self.model_name,
            "Name used when saving the built model pickle and related outputs.",
        )
        self.body_layout.addLayout(form)

        self.output_picker = PathPicker("Model Output Folder", mode="folder")
        self.output_picker.set_value(str(Path("./models/output").resolve()))
        self.output_picker.label.setToolTip("Directory where the built model and example figures will be saved.")
        self.body_layout.addWidget(self.output_picker)

        start_btn = QPushButton("Build Model")
        start_btn.clicked.connect(self.build_model)
        self.body_layout.addWidget(start_btn)
        self._toggle_inputs(self.build_input_mode.currentText())

    def _toggle_inputs(self, mode):
        self.csv_picker.setVisible(mode == "CSV")
        self.image_picker.setVisible(mode != "CSV")

    def create_build_dataset_csv(self, image_folder, output_folder):
        image_folder = os.path.abspath(image_folder)
        output_folder = os.path.abspath(output_folder)
        os.makedirs(output_folder, exist_ok=True)

        folder_name = os.path.basename(os.path.normpath(image_folder)) or "dataset"
        csv_path = os.path.join(output_folder, f"{folder_name}_build_dataset.csv")
        return create_vampire_input_csv(
            [image_folder],
            [folder_name],
            csv_path,
            tag="",
            mode="build",
            note="Auto-generated from Build Model folder selection",
        )

    def build_model(self):
        csv_path = None
        image_folder = None
        if self.build_input_mode.currentText() == "CSV":
            csv_path = self.csv_picker.value()
            if not csv_path:
                QMessageBox.critical(self, "Missing CSV", "Please select a model-build CSV file.")
                return
        else:
            image_folder = self.image_picker.value()
            if not image_folder:
                QMessageBox.critical(self, "Missing Folder", "Please select an image folder for model building.")
                return

        model_name = self.model_name.text().strip()
        outpth = self.output_picker.value()
        if not model_name:
            QMessageBox.critical(self, "Missing Model Name", "Please provide a model name.")
            return
        if not outpth:
            QMessageBox.critical(self, "Missing Output Folder", "Please provide a model output folder.")
            return

        num_coords = self.num_coords.text().strip() or "50"
        clnum = str(self.shape_modes.value())
        if self.build_input_mode.currentText() != "CSV":
            csv_path = self.create_build_dataset_csv(image_folder, outpth)

        signals = WorkerSignals()
        signals.status.connect(self.status_callback)
        signals.info.connect(lambda title, text: QMessageBox.information(self, title, text))
        signals.error.connect(lambda title, text: QMessageBox.critical(self, title, text))
        signals.modelBuilt.connect(self.on_model_built)

        def process():
            status_state = {"message": "Initializing model build..."}

            def set_status_from_legacy(text):
                status_state["message"] = text
                status_type = "error" if str(text).lower().startswith("error") else "processing"
                signals.status.emit(text, status_type, 0)

            entries = {
                "Image sets to build": LegacyTextAdapter(getter=lambda: csv_path),
                "Number of coordinates": LegacyTextAdapter(getter=lambda: num_coords),
                "Number of shape modes": LegacyTextAdapter(getter=lambda: clnum),
                "Model output folder": LegacyTextAdapter(getter=lambda: outpth),
                "Model name": LegacyTextAdapter(getter=lambda: model_name),
                "Status": LegacyTextAdapter(getter=lambda: status_state["message"], setter=set_status_from_legacy),
                "Model to apply": LegacyTextAdapter(getter=lambda: ""),
            }
            progress_adapter = QtProgressAdapter(lambda m, k, p: signals.status.emit(m, k, p), lambda: status_state["message"])

            try:
                signals.status.emit("Extracting boundaries...", "processing", 5)
                getboundary(csv_path, progress_adapter, entries)
                signals.status.emit("Building model...", "processing", 60)
                mainbody(True, csv_path, entries, outpth, clnum, progress_adapter)

                model_dir = os.path.join(outpth, model_name)
                pickle_candidates = []
                if os.path.isdir(model_dir):
                    pickle_candidates = [
                        os.path.join(model_dir, f)
                        for f in os.listdir(model_dir)
                        if f.lower().endswith(".pickle") and f.startswith(model_name)
                    ]
                model_path = max(pickle_candidates, key=os.path.getmtime) if pickle_candidates else None

                model_data = {
                    "name": model_name,
                    "shape_modes": int(clnum),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "path": model_path,
                }
                signals.modelBuilt.emit(model_data)
                signals.status.emit("Model built and saved successfully!", "success", 100)
                signals.info.emit(
                    "Build Complete",
                    f"Model built successfully.\nModel name: {model_name}\nModel path: {model_path if model_path else 'Created (path not resolved)'}",
                )
            except Exception as exc:
                signals.error.emit("Model Build Failed", f"Error during model build: {exc}")

        threading.Thread(target=process, daemon=True).start()


class ApplyModelPanel(PanelBox):
    def __init__(self, status_callback, built_model_getter, parent=None):
        super().__init__(
            "Apply Model",
            "Apply a saved VAMPIRE model using either a dataset CSV or a segmented image folder.",
            parent,
        )
        self.status_callback = status_callback
        self.built_model_getter = built_model_getter

        self.model_notice_frame = QFrame()
        self.model_notice_frame.setStyleSheet("background: #1b5e20; border: 1px solid #0f3d13;")
        notice_layout = QHBoxLayout(self.model_notice_frame)
        notice_icon = QLabel("Model Ready")
        notice_icon.setStyleSheet("font-weight: 700; color: white;")
        self.model_notice = QLabel("No built model available yet.")
        self.model_notice.setWordWrap(True)
        self.model_notice.setStyleSheet("color: white;")
        self.use_built_model = QCheckBox("Use this model")
        self.use_built_model.setChecked(False)
        self.use_built_model.toggled.connect(self._toggle_model_picker)
        self.use_built_model.setStyleSheet("color: white;")
        notice_layout.addWidget(notice_icon)
        notice_layout.addWidget(self.model_notice, 1)
        notice_layout.addWidget(self.use_built_model)
        self.body_layout.addWidget(self.model_notice_frame)
        self.model_notice_frame.hide()

        self.model_picker = PathPicker("Model to Apply", mode="file", file_filter="Pickle Files (*.pkl *.pickle)")
        self.model_picker.label.setToolTip("Upload a previously saved model file to apply to the selected images.")
        self.body_layout.addWidget(self.model_picker)

        form = QFormLayout()
        self.input_mode = NoWheelComboBox()
        self.input_mode.addItems(["CSV", "Folder"])
        self.input_mode.currentTextChanged.connect(self._toggle_inputs)
        add_labeled_row(
            form,
            "Segmented Image Input Type",
            self.input_mode,
            "Choose whether Apply Model should read a dataset CSV directly or generate one from a segmented image folder.",
        )
        self.body_layout.addLayout(form)

        self.csv_picker = PathPicker("CSV File Input", mode="file", file_filter="CSV Files (*.csv)")
        self.image_picker = PathPicker("Image Folder", mode="folder")
        self.csv_picker.label.setToolTip("Upload a CSV file containing set ID, condition, set location, tag, and note columns.")
        self.image_picker.label.setToolTip("Select the folder containing the segmented images you want to analyze with the model.")
        self.body_layout.addWidget(self.csv_picker)
        self.body_layout.addWidget(self.image_picker)

        self.output_picker = PathPicker("Result Output Folder", mode="folder")
        self.output_picker.set_value(str(Path("./results/model_output").resolve()))
        self.output_picker.label.setToolTip("Directory where analysis results will be saved.")
        self.body_layout.addWidget(self.output_picker)

        start_btn = QPushButton("Apply Model")
        start_btn.clicked.connect(self.apply_model)
        self.body_layout.addWidget(start_btn)

        self._toggle_inputs(self.input_mode.currentText())
        self._toggle_model_picker(self.use_built_model.isChecked())
        self.update_model_notice(self.built_model_getter())

    def update_model_notice(self, model_data):
        if model_data:
            self.model_notice.setText(
                f"Model '{model_data['name']}' is ready to use.\n"
                f"Created: {model_data['timestamp']} | {model_data['shape_modes']} shape modes"
            )
            self.model_notice_frame.show()
        else:
            self.model_notice.setText("No built model available yet.")
            self.model_notice_frame.hide()

    def _toggle_inputs(self, mode):
        self.csv_picker.setVisible(mode == "CSV")
        self.image_picker.setVisible(mode != "CSV")

    def _toggle_model_picker(self, checked):
        self.model_picker.setVisible(not checked)

    def create_apply_dataset_csv(self, image_folder, output_folder):
        image_folder = os.path.abspath(image_folder)
        output_folder = os.path.abspath(output_folder)
        os.makedirs(output_folder, exist_ok=True)

        folder_name = os.path.basename(os.path.normpath(image_folder)) or "dataset"
        csv_path = os.path.join(output_folder, f"{folder_name}_apply_dataset.csv")
        return create_vampire_input_csv(
            [image_folder],
            [folder_name],
            csv_path,
            tag="",
            mode="apply",
            note="Auto-generated from Apply Model folder selection",
        )

    def apply_model(self):
        csv_path = None
        image_folder = None
        if self.input_mode.currentText() == "CSV":
            csv_path = self.csv_picker.value()
            if not csv_path:
                QMessageBox.critical(self, "Missing CSV", "Please select an image set CSV file.")
                return
        else:
            image_folder = self.image_picker.value()
            if not image_folder:
                QMessageBox.critical(self, "Missing Folder", "Please select an image folder.")
                return

        built_model = self.built_model_getter()
        if self.use_built_model.isChecked():
            model_path = built_model.get("path") if built_model else None
            if not model_path:
                QMessageBox.critical(self, "Missing Model", "Built model path is unavailable. Select a model pickle file.")
                return
        else:
            model_path = self.model_picker.value()
            if not model_path:
                QMessageBox.critical(self, "Missing Model", "Please select a model pickle file.")
                return

        outpth = self.output_picker.value()
        if not outpth:
            QMessageBox.critical(self, "Missing Output Folder", "Please provide a result output folder.")
            return

        if self.input_mode.currentText() != "CSV":
            csv_path = self.create_apply_dataset_csv(image_folder, outpth)

        signals = WorkerSignals()
        signals.status.connect(self.status_callback)
        signals.info.connect(lambda title, text: QMessageBox.information(self, title, text))
        signals.error.connect(lambda title, text: QMessageBox.critical(self, title, text))

        def process():
            status_state = {"message": "Initializing model application..."}

            def set_status_from_legacy(text):
                status_state["message"] = text
                status_type = "error" if str(text).lower().startswith("error") else "processing"
                signals.status.emit(text, status_type, 0)

            entries = {
                "Image sets to apply": LegacyTextAdapter(getter=lambda: csv_path),
                "Result output folder": LegacyTextAdapter(getter=lambda: outpth),
                "Model to apply": LegacyTextAdapter(getter=lambda: model_path),
                "Number of coordinates": LegacyTextAdapter(getter=lambda: "50"),
                "Status": LegacyTextAdapter(getter=lambda: status_state["message"], setter=set_status_from_legacy),
            }
            progress_adapter = QtProgressAdapter(lambda m, k, p: signals.status.emit(m, k, p), lambda: status_state["message"])

            try:
                signals.status.emit("Extracting boundaries...", "processing", 5)
                getboundary(csv_path, progress_adapter, entries)
                signals.status.emit("Applying model to image set...", "processing", 60)
                mainbody(False, csv_path, entries, outpth, None, progress_adapter)
                signals.status.emit("Model applied successfully!", "success", 100)
                signals.info.emit("Apply Complete", f"Model application finished.\nResults saved to:\n{outpth}")
            except Exception as exc:
                signals.error.emit("Model Apply Failed", f"Error during model application: {exc}")

        threading.Thread(target=process, daemon=True).start()


class StatusBarWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        self.message = QLabel("Ready")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.message, 1)
        layout.addWidget(self.progress)

    def set_status(self, message, status_type="processing", progress=0):
        color_map = {
            "processing": "#1565c0",
            "success": "#2e7d32",
            "error": "#c62828",
        }
        self.message.setText(message)
        self.message.setStyleSheet(f"color: {color_map.get(status_type, '#333333')};")
        self.progress.setValue(max(0, min(100, int(progress))))


class VampireAnalysisQtApp(QMainWindow):
    def __init__(self, selected_panels):
        super().__init__()
        self.setWindowTitle("VAMPIRE Analysis - PyQt6")
        self.resize(900, 760)
        self.built_model = None

        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("background: #b71c1c; color: white;")
        header_layout = QVBoxLayout(header)
        title = QLabel("VAMPIRE Analysis")
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: white;")
        subtitle = QLabel("PyQt6 workflow shell for segmentation, masking, model build, and model application")
        subtitle.setStyleSheet("color: #ffcdd2;")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root_layout.addWidget(header)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, 1)

        main_scroll, self.main_content_layout = self._create_tab_page()
        unused_scroll, self.unused_content_layout = self._create_tab_page()
        self.tabs.addTab(main_scroll, "Main Workflow")
        self.tabs.addTab(unused_scroll, "Other Unused Features")

        self.status_bar_widget = StatusBarWidget()
        root_layout.addWidget(self.status_bar_widget)

        self.setCentralWidget(central)

        self.segmentation_panel = SegmentationPanel(self.update_status)
        self.masking_panel = MaskingPanel(self.update_status)
        self.mask_pipeline_panel = MaskPipelinePanel(self.update_status)
        self.build_panel = BuildModelPanel(self.update_status, self.on_model_built)
        self.apply_panel = ApplyModelPanel(self.update_status, self.get_built_model)

        panels = [
            ("segmentation", self.segmentation_panel),
            ("masking", self.masking_panel),
            ("mask_pipeline", self.mask_pipeline_panel),
            ("build_model", self.build_panel),
            ("apply_model", self.apply_panel),
        ]

        for key, panel in panels:
            if selected_panels.get(key):
                self.main_content_layout.addWidget(panel)
            else:
                self.unused_content_layout.addWidget(panel)

        self.main_content_layout.addStretch(1)
        self.unused_content_layout.addStretch(1)

        if all(selected_panels.get(key) for key, _panel in panels):
            self.tabs.setTabVisible(1, False)
        else:
            self.tabs.setTabVisible(1, True)

    def _create_tab_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(16)
        scroll.setWidget(scroll_content)
        return scroll, content_layout

    def update_status(self, message, status_type="processing", progress=0):
        self.status_bar_widget.set_status(message, status_type, progress)

    def on_model_built(self, model_data):
        self.built_model = model_data
        if hasattr(self, "apply_panel"):
            self.apply_panel.update_model_notice(model_data)

    def get_built_model(self):
        return self.built_model


def main():
    app = QApplication(sys.argv)
    checklist = StartupChecklistDialog()
    if checklist.exec() != QDialog.DialogCode.Accepted:
        return 0

    selected = checklist.selected_panels()
    if not any(selected.values()):
        QMessageBox.information(None, "No Panels Selected", "Select at least one workflow panel to continue.")
        return 0

    window = VampireAnalysisQtApp(selected)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
