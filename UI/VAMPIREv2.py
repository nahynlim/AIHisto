"""
Vampire Analysis - Tkinter Implementation v2
Advanced shape mode analysis and model application tool for SHG microscopy images

Updated with integrated CellProfiler segmentation and enhanced masking workflow
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont
import threading
import time
from datetime import datetime
from typing import Optional, Callable
import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
from generate_vampire_input_csv import create_vampire_input_csv
from matlab_mask_runner import run_matlab_mask_job
from vampire.mainbody import mainbody
from vampire.getboundary import getboundary


class LegacyTextAdapter:
    """Minimal Entry-like adapter for legacy pipeline functions."""
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


class LegacyProgressAdapter:
    """Progressbar-like adapter expected by getboundary/mainbody."""
    def __init__(self, widget, status_callback, status_message_getter):
        self.widget = widget
        self.status_callback = status_callback
        self.status_message_getter = status_message_getter
        self.value = 0

    def __setitem__(self, key, value):
        if key == "value":
            self.value = max(0, min(100, int(float(value))))
            if threading.current_thread() is threading.main_thread():
                self.status_callback(
                    self.status_message_getter() or "Processing...",
                    "processing",
                    self.value
                )
            else:
                self.widget.after(0, lambda: self.status_callback(
                    self.status_message_getter() or "Processing...",
                    "processing",
                    self.value
                ))

    def update(self):
        return


IMAGE_EXTENSIONS = {".tiff", ".tif", ".jpeg", ".jpg", ".png", ".bmp", ".gif"}
MASK_SUFFIX_MAP = {
    "damaged": "_BWdam",
    "undamaged": "_BWnotDam",
    "low_shg": "_BWlowSHG",
    "high_shg": "_BWhighSHG",
}


def iter_image_files(folder, tag=None):
    """Yield supported image paths from a folder, optionally filtered by tag."""
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
    """Return supported image paths from a folder path or selected file list."""
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
    """Create a temporary pipeline copy with run-specific output settings."""
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
    """Return the input directory CellProfiler should read from for this run."""
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
    """Remove temporary staging artifacts created for a headless CellProfiler run."""
    input_dir_path = Path(input_dir) if input_dir else None
    original_pipeline = Path(original_pipeline_path).resolve() if original_pipeline_path else None
    configured_pipeline = Path(configured_pipeline_path).resolve() if configured_pipeline_path else None

    # Remove staged input only when the GUI created a temporary folder.
    uses_direct_folder_input = not isinstance(image_input, (list, tuple)) and Path(image_input).is_dir()
    if input_dir_path is not None and not uses_direct_folder_input:
        if input_dir_path.name == "_cellprofiler_input" and input_dir_path.exists():
            shutil.rmtree(input_dir_path, ignore_errors=True)

    # Remove the run-specific temporary pipeline copy, never the source pipeline.
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


def normalize_mask_key(stem):
    """Normalize a filename stem to a base key for image/mask matching."""
    normalized = str(stem)
    for suffix in MASK_SUFFIX_MAP.values():
        if normalized.lower().endswith(suffix.lower()):
            return normalized[:-len(suffix)]
    return normalized


def build_mask_index(mask_folder):
    """Index masks by normalized base filename."""
    mask_dir = Path(mask_folder)
    if not mask_dir.exists():
        return {}

    mask_index = {}
    for path in mask_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        base_key = normalize_mask_key(path.stem).lower()
        suffix_key = ""
        stem_lower = path.stem.lower()
        for mask_name, suffix in MASK_SUFFIX_MAP.items():
            if stem_lower.endswith(suffix.lower()):
                suffix_key = mask_name
                break
        mask_index.setdefault(base_key, {})
        mask_index[base_key][suffix_key] = path
    return mask_index


def apply_mask_to_image_array(image_array, mask_array):
    """Apply a binary mask to an image array while preserving dtype."""
    if image_array.ndim == 2:
        return image_array * mask_array.astype(image_array.dtype)
    expanded_mask = mask_array[..., None].astype(image_array.dtype)
    return image_array * expanded_mask


def apply_masks_for_csv_dataset(csv_path, mask_folder, output_root, mask_choice, status_callback=None):
    """Apply masks to each source image listed in the dataset CSV."""
    ui = pd.read_csv(csv_path)
    mask_index = build_mask_index(mask_folder)
    if not mask_index:
        raise FileNotFoundError(f"No mask images were found in: {mask_folder}")

    output_root = Path(output_root)
    masked_root = output_root / "masked_source_images"
    masked_root.mkdir(parents=True, exist_ok=True)

    processed = 0
    missing = []
    resized = []

    setpaths = ui["set location"]
    tags = ui["tag"] if "tag" in ui.columns else [None] * len(ui)
    conditions = ui["condition"] if "condition" in ui.columns else [None] * len(ui)

    total_sets = max(len(setpaths), 1)
    for set_idx, setfolder in enumerate(setpaths):
        tag = tags.iloc[set_idx] if hasattr(tags, "iloc") else tags[set_idx]
        condition = conditions.iloc[set_idx] if hasattr(conditions, "iloc") else conditions[set_idx]
        image_paths = iter_image_files(setfolder, tag)
        set_name = str(condition).strip() if pd.notna(condition) and str(condition).strip() else Path(setfolder).name
        set_output = masked_root / set_name
        set_output.mkdir(parents=True, exist_ok=True)

        for image_path in image_paths:
            key = image_path.stem.lower()
            candidates = [
                key,
                normalize_mask_key(image_path.stem).lower(),
            ]

            mask_path = None
            for candidate in candidates:
                mask_options = mask_index.get(candidate, {})
                if mask_choice in mask_options:
                    mask_path = mask_options[mask_choice]
                    break
                if "" in mask_options:
                    mask_path = mask_options[""]
                    break

            if mask_path is None:
                missing.append(image_path.name)
                continue

            image_array = np.array(Image.open(image_path))
            mask_array = np.array(Image.open(mask_path))
            if mask_array.ndim == 3:
                mask_array = mask_array[..., 0]
            mask_bool = mask_array > 0

            if mask_bool.shape != image_array.shape[:2]:
                resized.append(f"{image_path.name} <- {mask_path.name}")
                mask_img = Image.fromarray((mask_bool.astype(np.uint8) * 255))
                mask_img = mask_img.resize((image_array.shape[1], image_array.shape[0]), Image.Resampling.NEAREST)
                mask_bool = np.array(mask_img) > 0

            masked_array = apply_mask_to_image_array(image_array, mask_bool)
            Image.fromarray(masked_array).save(set_output / image_path.name)
            processed += 1

        if status_callback is not None:
            progress = 60 + int(((set_idx + 1) / total_sets) * 35)
            status_callback(
                f"Applying masks to source images ({set_idx + 1}/{total_sets} sets)...",
                "processing",
                progress,
            )

    return {
        "processed": processed,
        "missing": missing,
        "resized": resized,
        "output_folder": str(masked_root),
    }


class ToolTip:
    """Tooltip widget for displaying help text on hover"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)
    
    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert") if hasattr(self.widget, 'bbox') else (0, 0, 0, 0)
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                        background="#333333", foreground="white",
                        relief=tk.SOLID, borderwidth=1,
                        font=("Arial", 9), padx=8, pady=6)
        label.pack()
    
    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class DragDropUploadField(ttk.Frame):
    """Custom drag-and-drop upload field widget"""
    def __init__(self, parent, label, placeholder, accept, help_text, icon='file', allow_multiple=False):
        super().__init__(parent)
        self.file_path = None
        self.placeholder = placeholder
        self.accept = accept
        self.allow_multiple = allow_multiple
        
        # Label with help tooltip
        label_frame = ttk.Frame(self)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(label_frame, text=label, font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" ℹ️", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(help_btn, help_text)
        
        # Upload area
        self.upload_frame = tk.Frame(self, bg="#f0f0f0", relief=tk.RIDGE, bd=2)
        self.upload_frame.pack(fill=tk.BOTH, expand=True, ipady=20)
        
        # Initial state - empty
        self.empty_label = ttk.Label(self.upload_frame, text=f"📁 {placeholder}\nClick to browse",
                                     background="#f0f0f0", justify=tk.CENTER)
        self.empty_label.pack(expand=True)
        
        # File selected state (hidden initially)
        self.file_frame = ttk.Frame(self.upload_frame)
        
        # Bind click event
        self.upload_frame.bind("<Button-1>", lambda e: self.browse_file())
        self.empty_label.bind("<Button-1>", lambda e: self.browse_file())
    def browse_file(self):
        """Open file browser dialog"""
        # For image fields with multi-select enabled, allow selecting image files directly.
        if self.allow_multiple and "image" in self.accept:
            filetypes = [("Image files", "*.tiff *.tif *.jpeg *.jpg *.png *.bmp *.gif"), ("All files", "*.*")]
            file_path = filedialog.askopenfilenames(filetypes=filetypes)
        elif 'folder' in self.placeholder.lower():
            file_path = filedialog.askdirectory()
        else:
            filetypes = [("All files", "*.*")]
            if ".csv" in self.accept:
                filetypes = [("CSV files", "*.csv"), ("All files", "*.*")]
            elif "image" in self.accept:
                filetypes = [("Image files", "*.tiff *.tif *.jpeg *.jpg *.png *.bmp *.gif"), ("All files", "*.*")]
            elif ".pkl" in self.accept:
                filetypes = [("Pickle files", "*.pkl *.pickle"), ("All files", "*.*")]

            file_path = filedialog.askopenfilename(filetypes=filetypes)

        if file_path:
            self.set_file(file_path)
    def set_file(self, file_path):
        """Set the selected file and update UI"""
        self.file_path = file_path
        self.empty_label.pack_forget()

        # Clear previous file display
        for widget in self.file_frame.winfo_children():
            widget.destroy()

        # Show file info
        self.upload_frame.config(bg="#e8f5e9")
        is_multi = isinstance(file_path, (list, tuple))
        display_path = file_path[0] if (is_multi and len(file_path) > 0) else file_path
        file_name = os.path.basename(display_path) if display_path else ""

        info_frame = ttk.Frame(self.file_frame)
        info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)

        if is_multi:
            ttk.Label(info_frame, text=f"Selected {len(file_path)} files", font=("Arial", 9, "bold")).pack(anchor=tk.W)
            if file_name:
                ttk.Label(info_frame, text=f"First: {file_name}", font=("Arial", 8)).pack(anchor=tk.W)
        else:
            ttk.Label(info_frame, text="Selected: " + file_name, font=("Arial", 9, "bold")).pack(anchor=tk.W)

        try:
            if is_multi:
                total_size = sum(os.path.getsize(p) for p in file_path if os.path.isfile(p)) / 1024
                ttk.Label(info_frame, text=f"{total_size:.1f} KB total", font=("Arial", 8)).pack(anchor=tk.W)
            elif os.path.isfile(file_path):
                size = os.path.getsize(file_path) / 1024
                ttk.Label(info_frame, text=f"{size:.1f} KB", font=("Arial", 8)).pack(anchor=tk.W)
            else:
                ttk.Label(info_frame, text="Folder", font=("Arial", 8)).pack(anchor=tk.W)
        except Exception:
            pass

        # Clear button
        clear_btn = ttk.Button(self.file_frame, text="x", width=3, command=self.clear_file)
        clear_btn.pack(side=tk.RIGHT, padx=10)

        self.file_frame.pack(fill=tk.BOTH, expand=True)
    def clear_file(self):
        """Clear the selected file"""
        self.file_path = None
        self.file_frame.pack_forget()
        self.upload_frame.config(bg="#f0f0f0")
        self.empty_label.pack(expand=True)
    
    def get_file(self):
        """Get the selected file path"""
        return self.file_path


class StatusBar(ttk.Frame):
    """Status bar with progress indicator"""
    def __init__(self, parent):
        super().__init__(parent, relief=tk.RIDGE, borderwidth=2)
        self.status_type = 'idle'
        
        # Status text with icon
        self.status_frame = ttk.Frame(self)
        self.status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.icon_label = ttk.Label(self.status_frame, text="ℹ️", font=("Arial", 10))
        self.icon_label.pack(side=tk.LEFT, padx=(0, 10))
        
        self.status_label = ttk.Label(self.status_frame, text="Welcome to the Vampire Analysis", font=("Arial", 9))
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.progress_pct = ttk.Label(self.status_frame, text="", font=("Arial", 9, "bold"))
        self.progress_pct.pack(side=tk.RIGHT)
        
        # Progress bar
        self.progress = ttk.Progressbar(self, orient=tk.HORIZONTAL, mode='determinate', length=100)
        self.progress.pack(fill=tk.X, padx=10, pady=(0, 5))
        
    def set_status(self, message, status_type='processing', progress=0):
        """Update status message and progress"""
        self.status_type = status_type
        self.status_label.config(text=message)
        self.progress['value'] = progress
        
        # Update icon and colors based on status type
        icons = {
            'idle': 'ℹ️',
            'processing': '⚙️',
            'success': '✓',
            'error': '✕'
        }
        self.icon_label.config(text=icons.get(status_type, 'ℹ️'))
        
        if 0 < progress < 100:
            self.progress_pct.config(text=f"{progress}%")
        else:
            self.progress_pct.config(text="")


class ModelPreviewDialog(tk.Toplevel):
    """Modal dialog for model preview with save/discard options"""
    def __init__(self, parent, model_data, on_save, on_discard):
        super().__init__(parent)
        self.title("Model Preview")
        self.geometry("600x500")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        
        self.result = None
        
        # Header
        header = tk.Frame(self, bg="#4CAF50", height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text="✓ Model Built Successfully!", 
                bg="#4CAF50", fg="white", font=("Arial", 14, "bold")).pack(pady=15)
        
        # Content
        content = ttk.Frame(self, padding=20)
        content.pack(fill=tk.BOTH, expand=True)
        
        # Model details
        details_frame = tk.Frame(content, bg="#f5f5f5", relief=tk.RIDGE, bd=2)
        details_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(details_frame, text="Model Details", bg="#f5f5f5", 
                font=("Arial", 11, "bold")).pack(anchor=tk.W, padx=10, pady=10)
        
        detail_grid = ttk.Frame(details_frame)
        detail_grid.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Label(detail_grid, text="Model Name:", font=("Arial", 9, "bold")).grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Label(detail_grid, text=model_data['name']).grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        
        ttk.Label(detail_grid, text="Shape Modes:", font=("Arial", 9, "bold")).grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Label(detail_grid, text=str(model_data['shape_modes'])).grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        
        ttk.Label(detail_grid, text="Created:", font=("Arial", 9, "bold")).grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Label(detail_grid, text=model_data['timestamp']).grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
        
        # Visualization placeholder
        viz_frame = tk.Frame(content, bg="#f0f0f0", relief=tk.RIDGE, bd=2, height=150)
        viz_frame.pack(fill=tk.X, pady=(0, 15))
        viz_frame.pack_propagate(False)
        
        tk.Label(viz_frame, text="Model Visualization\nShape mode analysis preview", 
                bg="#f0f0f0", fg="#666666", font=("Arial", 10)).pack(expand=True)
        
        # Info message
        info_frame = tk.Frame(content, bg="#fff9c4", relief=tk.RIDGE, bd=2)
        info_frame.pack(fill=tk.X)
        
        tk.Label(info_frame, text="⚠ Next Steps: Save this model to apply it to new image sets\nin the Apply Model section, or discard to rebuild with different parameters.",
                bg="#fff9c4", fg="#333333", font=("Arial", 9), justify=tk.LEFT).pack(padx=10, pady=10)
        
        # Buttons
        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, padx=20, pady=15)
        
        ttk.Button(button_frame, text="✕ Discard Model", 
                  command=lambda: self.close(on_discard)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(button_frame, text="💾 Save Model", 
                  command=lambda: self.close(on_save)).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))
    
    def close(self, callback):
        """Close dialog and execute callback"""
        self.destroy()
        if callback:
            callback()


class SegmentationPanel(ttk.LabelFrame):
    """Panel for CellProfiler-based image segmentation"""
    def __init__(self, parent, status_callback):
        super().__init__(parent, text="SEGMENTATION - CellProfiler pipeline for raw image processing", padding=15)
        self.status_callback = status_callback
        self.valid_image_ext = {".tiff", ".tif", ".jpeg", ".jpg", ".png", ".bmp", ".gif"}
        self.valid_pipeline_ext = {".cppipe"}
        base_dir = os.path.dirname(os.path.abspath(__file__))

        # Presets are resolved dynamically from common repo-relative locations.
        self.pipeline_presets = {
            "Blue Stained DAPI": "Blue_Nuclei_Segmentation_Pipeline.cppipe",
            "Normal Staining": "Nuclei_Segmentation_Pipeline.cppipe",
        }
        self.launch_option = "Launch CellProfiler (Interactive)"
        self.segmentation_run_mode = tk.StringVar(value="Run Headless")
        self.segmentation_export_mode = tk.StringVar(value="Both")

        input_frame = ttk.Frame(self)
        input_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        left_frame = ttk.Frame(input_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        self.segmentation_input_upload = DragDropUploadField(
            left_frame,
            "Images",
            "Image files",
            "image/*",
            "Choose one or more image files. CellProfiler will use their source folder as the input directory.",
            icon='folder',
            allow_multiple=True
        )
        self.segmentation_input_upload.pack(fill=tk.BOTH, expand=True)

        run_mode_frame = ttk.Frame(self)
        run_mode_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(run_mode_frame, text="Run Mode", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        run_mode_help = ttk.Label(run_mode_frame, text=" i", cursor="hand2")
        run_mode_help.pack(side=tk.LEFT)
        ToolTip(
            run_mode_help,
            "Run Headless executes the selected CellProfiler pipeline automatically. "
            "Open CellProfiler launches CellProfiler so you can inspect or run the pipeline yourself."
        )
        self.segmentation_run_mode_combo = ttk.Combobox(
            run_mode_frame,
            textvariable=self.segmentation_run_mode,
            state="readonly",
            values=["Run Headless", "Open CellProfiler"],
            width=24
        )
        self.segmentation_run_mode_combo.pack(side=tk.RIGHT)

        export_mode_frame = ttk.Frame(self)
        export_mode_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(export_mode_frame, text="Export Mode", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        export_mode_help = ttk.Label(export_mode_frame, text=" i", cursor="hand2")
        export_mode_help.pack(side=tk.LEFT)
        ToolTip(
            export_mode_help,
            "Both saves segmented images and spreadsheet outputs. "
            "Images Only saves only image exports. Spreadsheet Only saves only measurement tables."
        )
        self.segmentation_export_mode_combo = ttk.Combobox(
            export_mode_frame,
            textvariable=self.segmentation_export_mode,
            state="readonly",
            values=["Both", "Images Only", "Spreadsheet Only"],
            width=24
        )
        self.segmentation_export_mode_combo.pack(side=tk.RIGHT)

        # Pipeline selection
        pipeline_frame = ttk.Frame(self)
        pipeline_frame.pack(fill=tk.X, pady=(0, 10))

        label_frame = ttk.Frame(pipeline_frame)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(label_frame, text="Segmentation Pipeline", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" i", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(
            help_btn,
            "Select a pipeline to open in CellProfiler, or upload your own. CellProfiler runs interactively."
        )

        self.pipeline_choice = tk.StringVar(value="Blue Stained DAPI")
        self.pipeline_combo = ttk.Combobox(
            pipeline_frame,
            textvariable=self.pipeline_choice,
            state="readonly",
            values=list(self.pipeline_presets.keys()) + [self.launch_option]
        )
        self.pipeline_combo.pack(fill=tk.X)
        # No custom pipeline upload option.


        # CellProfiler executable path
        cp_frame = ttk.Frame(self)
        cp_frame.pack(fill=tk.X, pady=(0, 10))

        label_frame = ttk.Frame(cp_frame)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(label_frame, text="CellProfiler Executable", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" i", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(
            help_btn,
            "Path to CellProfiler executable (e.g., /Applications/CellProfiler.app/Contents/MacOS/cp or 'cellprofiler')."
        )

        cp_input_frame = ttk.Frame(cp_frame)
        cp_input_frame.pack(fill=tk.X)
        self.cp_executable = ttk.Entry(cp_input_frame)
        self.cp_executable.insert(0, self.get_default_cp_executable())
        self.cp_executable.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(cp_input_frame, text="...", width=3, command=self.browse_cp_executable).pack(side=tk.RIGHT)

        output_frame = ttk.Frame(self)
        output_frame.pack(fill=tk.X, pady=(0, 10))

        output_label_frame = ttk.Frame(output_frame)
        output_label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(output_label_frame, text="Segmented Output Folder", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        output_help_btn = ttk.Label(output_label_frame, text=" i", cursor="hand2")
        output_help_btn.pack(side=tk.LEFT)
        ToolTip(output_help_btn, "Choose where CellProfiler should write segmented images and exported results.")

        output_input_frame = ttk.Frame(output_frame)
        output_input_frame.pack(fill=tk.X)
        self.segmentation_output_path = ttk.Entry(output_input_frame)
        self.segmentation_output_path.insert(0, "./results/segmentation")
        self.segmentation_output_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(output_input_frame, text="Browse", width=10,
                  command=self.browse_segmentation_output).pack(side=tk.RIGHT)

        # Segmentation button
        segment_btn = ttk.Button(self, text="Start Segmentation", command=self.start_segmentation)
        segment_btn.pack(fill=tk.X)
        ToolTip(segment_btn, "Run the selected CellProfiler pipeline headlessly or open CellProfiler interactively")

        # No custom pipeline upload option.
    def browse_cp_executable(self):
        """Browse for CellProfiler executable"""
        exe = filedialog.askopenfilename()
        if exe:
            self.cp_executable.delete(0, tk.END)
            self.cp_executable.insert(0, exe)

    def browse_segmentation_output(self):
        """Browse for segmentation output folder"""
        folder = filedialog.askdirectory()
        if folder:
            self.segmentation_output_path.delete(0, tk.END)
            self.segmentation_output_path.insert(0, folder)

    def get_default_cp_executable(self):
        """Best-effort default CellProfiler executable path."""
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

    def resolve_cp_executable(self, cp_exec):
        """Resolve OS-specific CellProfiler launch targets when possible."""
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
            text=True
        )
        target = (result.stdout or "").strip()
        if result.returncode == 0 and target:
            return target
        return cp_exec

    def cp_executable_exists(self, cp_exec):
        """Check whether the chosen CellProfiler executable is callable."""
        if not cp_exec:
            return False
        if sys.platform == "darwin":
            if cp_exec.lower().endswith(".app"):
                return os.path.isdir(cp_exec)
            if cp_exec in {"cellprofiler", "CellProfiler"} and shutil.which("open") is not None:
                return True
        return os.path.isfile(cp_exec) or shutil.which(cp_exec) is not None

    def build_cp_command(self, cp_exec, pipeline_path=None, *, run_headless=False, input_dir=None, output_dir=None):
        """Build a platform-appropriate CellProfiler command."""
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
        """Resolve preset pipeline filename from common repo-relative paths."""
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
        """Resolve selected pipeline path based on dropdown selection."""
        choice = self.pipeline_choice.get()
        if choice == self.launch_option:
            return None
        preset_filename = self.pipeline_presets.get(choice)
        return self.resolve_preset_pipeline(preset_filename) if preset_filename else None

    def start_segmentation(self):
        """Start CellProfiler segmentation process."""
        cp_exec = self.cp_executable.get().strip()
        cp_exec = self.resolve_cp_executable(cp_exec)
        pipeline_choice = self.pipeline_choice.get()
        pipeline_path = self.resolve_pipeline_path()
        run_mode = self.segmentation_run_mode.get()
        run_headless = run_mode == "Run Headless"
        image_input = self.segmentation_input_upload.get_file()
        output_dir = self.segmentation_output_path.get().strip()
        export_mode = self.segmentation_export_mode.get()

        if not self.cp_executable_exists(cp_exec):
            self.status_callback("Error: CellProfiler executable not found", "error", 0)
            messagebox.showerror(
                "CellProfiler Not Found",
                "The selected CellProfiler executable could not be found.\n\n"
                f"Current value:\n{cp_exec or '(empty)'}\n\n"
                "Use the browse button to select the CellProfiler executable, or enter a command "
                "that is available on your PATH."
            )
            return

        if pipeline_choice != self.launch_option:
            if not pipeline_path:
                self.status_callback("Error: Please select a valid .cppipe pipeline", "error", 0)
                messagebox.showerror(
                    "Error",
                    "Pipeline not found. Keep pipeline files in project root or ./pipelines."
                )
                return
            if not os.path.isfile(pipeline_path):
                self.status_callback("Error: Pipeline file not found", "error", 0)
                messagebox.showerror("Error", f"Pipeline file not found:\n{pipeline_path}")
                return
            if Path(pipeline_path).suffix.lower() not in self.valid_pipeline_ext:
                self.status_callback("Error: Pipeline must be .cppipe", "error", 0)
                messagebox.showerror("Error", "Pipeline must be a .cppipe file")
                return

        if not image_input:
            self.status_callback("Error: Please select images", "error", 0)
            messagebox.showerror("Error", "Please select images for segmentation.")
            return

        image_paths = collect_image_paths(image_input)
        if not image_paths:
            self.status_callback("Error: No supported images found", "error", 0)
            messagebox.showerror(
                "No Images Found",
                "No supported image files were found in the selected input.\n\n"
                "Supported types: .tif, .tiff, .jpg, .jpeg, .png, .bmp, .gif"
            )
            return

        if not output_dir:
            self.status_callback("Error: Please select an output folder", "error", 0)
            messagebox.showerror("Error", "Please select an output folder for segmentation.")
            return

        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            self.status_callback("Error: Could not create output folder", "error", 0)
            messagebox.showerror("Error", f"Could not create output folder:\n{output_dir}\n\n{exc}")
            return

        try:
            input_dir = prepare_cellprofiler_input_dir(image_input, image_paths, output_dir)
        except Exception as exc:
            self.status_callback("Error: Could not prepare selected images", "error", 0)
            messagebox.showerror(
                "Input Preparation Failed",
                f"Could not prepare the selected images for CellProfiler.\n\n{exc}"
            )
            return

        if run_headless and pipeline_choice == self.launch_option:
            self.status_callback("Error: Headless mode requires a pipeline", "error", 0)
            messagebox.showerror(
                "Pipeline Required",
                "Choose a segmentation pipeline before running CellProfiler headlessly."
            )
            return

        configured_pipeline_path = pipeline_path
        if pipeline_path:
            try:
                configured_pipeline_path = configure_cellprofiler_pipeline(
                    pipeline_path,
                    output_dir,
                    export_mode
                )
            except Exception as exc:
                self.status_callback("Error: Could not configure pipeline outputs", "error", 0)
                messagebox.showerror(
                    "Pipeline Configuration Failed",
                    f"Could not prepare the CellProfiler pipeline for this run.\n\n{exc}"
                )
                return

        def process():
            self.after(0, lambda: self.status_callback("Initializing CellProfiler...", "processing", 10))
            env = os.environ.copy()
            env["MPLBACKEND"] = "Agg"
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)

            cmd = self.build_cp_command(
                cp_exec,
                configured_pipeline_path,
                run_headless=run_headless,
                input_dir=input_dir,
                output_dir=output_dir
            )
            run_msg = "Running CellProfiler headlessly..." if run_headless else "Launching CellProfiler interactively..."
            self.after(0, lambda: self.status_callback(run_msg, "processing", 40))
            try:
                if run_headless:
                    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
                else:
                    subprocess.Popen(cmd, env=env)
                    result = None
            except Exception as exc:
                self.after(0, lambda: self.status_callback("CellProfiler failed", "error", 0))
                self.after(0, lambda: messagebox.showerror(
                    "Segmentation Failed",
                    f"Could not start CellProfiler.\n\nCommand:\n{' '.join(cmd)}\n\nError:\n{exc}"
                ))
                if run_headless:
                    cleanup_cellprofiler_temp_artifacts(
                        image_input,
                        input_dir,
                        pipeline_path,
                        configured_pipeline_path
                    )
                return

            if run_headless and result and result.returncode != 0:
                stderr_tail = (result.stderr or "").strip()
                if len(stderr_tail) > 1200:
                    stderr_tail = stderr_tail[-1200:]
                self.after(0, lambda: self.status_callback("CellProfiler failed", "error", 0))
                self.after(0, lambda: messagebox.showerror(
                    "Segmentation Failed",
                    f"Pipeline: {pipeline_choice}\n"
                    f"Return code: {result.returncode}\n\n"
                    f"stderr:\n{stderr_tail or '(empty)'}"
                ))
                cleanup_cellprofiler_temp_artifacts(
                    image_input,
                    input_dir,
                    pipeline_path,
                    configured_pipeline_path
                )
                return

            if run_headless:
                cleanup_cellprofiler_temp_artifacts(
                    image_input,
                    input_dir,
                    pipeline_path,
                    configured_pipeline_path
                )
                self.after(0, lambda: self.status_callback("CellProfiler segmentation completed", "success", 100))
                self.after(0, lambda: messagebox.showinfo(
                    "Segmentation Complete",
                    f"CellProfiler finished headless segmentation.\n\n"
                    f"Output folder:\n{output_dir}\n\n"
                    f"Pipeline preset:\n{pipeline_path}\n\n"
                    f"Export mode:\n{export_mode}"
                ))
            else:
                self.after(0, lambda: self.status_callback("CellProfiler launched", "success", 100))
                self.after(0, lambda: messagebox.showinfo(
                    "CellProfiler Launched",
                    f"CellProfiler: {cp_exec}\n"
                    f"Selected pipeline: {configured_pipeline_path if configured_pipeline_path else 'Choose in CellProfiler'}\n"
                    f"Export mode: {export_mode}\n"
                    f"Images folder:\n{input_dir}\n\n"
                    f"Output folder:\n{output_dir}"
                ))

        threading.Thread(target=process, daemon=True).start()
class MaskingPanel(ttk.LabelFrame):
    """Panel for SHG-based masking with damage region analysis"""
    def __init__(self, parent, status_callback):
        super().__init__(parent, text="MASKING - SHG damage region mask creation and application", padding=15)
        self.status_callback = status_callback
        self.roi_mode = tk.StringVar(value="auto")
        self.rotation_mode_map = {
            "None": "none",
            "Vertical +90 Counterclockwise": "vertical",
            "Horizontal -90 Clockwise": "horizontal",
            "User Angle": "user",
        }
        self.rotation_mode = tk.StringVar(value="None")
        self.enhance_var = tk.BooleanVar(value=False)
        self.create_mask_var = tk.BooleanVar(value=True)
        self.save_figures_var = tk.BooleanVar(value=True)
        self.save_stats_var = tk.BooleanVar(value=True)
        self.save_roi_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=True)
        self.mask_output_type = tk.StringVar(value="all")

        # SHG input selection
        upload_frame = ttk.Frame(self)
        upload_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.shg_upload = DragDropUploadField(
            upload_frame,
            "SHG Images",
            "SHG image files",
            "image/*",
            "Select one or more SHG image files.",
            icon='folder',
            allow_multiple=True
        )
        self.shg_upload.pack(fill=tk.BOTH, expand=True)

        params_frame = tk.Frame(self, bg="#f0f0f0", relief=tk.RIDGE, bd=2)
        params_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(params_frame, text="MATLAB Masking Parameters",
                bg="#f0f0f0", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=10, pady=5)

        params_content = ttk.Frame(params_frame)
        params_content.pack(fill=tk.X, padx=10, pady=(0, 10))

        bundle_row = ttk.Frame(params_content)
        bundle_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(bundle_row, text="Bundle Width", width=18).pack(side=tk.LEFT)
        bundle_help = ttk.Label(bundle_row, text=" i", cursor="hand2")
        bundle_help.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(bundle_help, "Tile size in pixels used for FFT orientation analysis. Larger values smooth more but reduce local detail.")
        self.bundle_width = ttk.Entry(bundle_row, width=10)
        self.bundle_width.insert(0, "15")
        self.bundle_width.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(bundle_row, text="Bundle Height", width=18).pack(side=tk.LEFT)
        self.bundle_height = ttk.Entry(bundle_row, width=10)
        self.bundle_height.insert(0, "15")
        self.bundle_height.pack(side=tk.LEFT)

        percentile_row = ttk.Frame(params_content)
        percentile_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(percentile_row, text="Low SHG Percentile", width=18).pack(side=tk.LEFT)
        percentile_help = ttk.Label(percentile_row, text=" i", cursor="hand2")
        percentile_help.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(percentile_help, "Threshold percentile derived from normalized control-image SHG intensity. Lower values make the low-SHG mask more selective.")
        self.low_shg_percentile = ttk.Entry(percentile_row, width=10)
        self.low_shg_percentile.insert(0, "10")
        self.low_shg_percentile.pack(side=tk.LEFT)

        mask_type_row = ttk.Frame(params_content)
        mask_type_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(mask_type_row, text="Mask Output Type", width=18).pack(side=tk.LEFT)
        mask_type_help = ttk.Label(mask_type_row, text=" i", cursor="hand2")
        mask_type_help.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(mask_type_help, "Choose which mask family to save. 'all' writes every supported mask output from the MATLAB run.")
        self.mask_output_combo = ttk.Combobox(
            mask_type_row,
            textvariable=self.mask_output_type,
            state="readonly",
            values=["all", "damaged", "undamaged", "low_shg", "high_shg"],
            width=18
        )
        self.mask_output_combo.pack(side=tk.LEFT)

        roi_row = ttk.Frame(params_content)
        roi_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(roi_row, text="ROI Mode", width=18).pack(side=tk.LEFT)
        roi_help = ttk.Label(roi_row, text=" i", cursor="hand2")
        roi_help.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(roi_help, "auto uses MATLAB ROI autodetection, draw opens a MATLAB polygon tool, and none analyzes the full image.")
        self.roi_mode_combo = ttk.Combobox(
            roi_row,
            textvariable=self.roi_mode,
            state="readonly",
            values=["auto", "draw", "none"],
            width=18
        )
        self.roi_mode_combo.pack(side=tk.LEFT)

        rotation_row = ttk.Frame(params_content)
        rotation_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(rotation_row, text="Rotation Mode", width=18).pack(side=tk.LEFT)
        rotation_help = ttk.Label(rotation_row, text=" i", cursor="hand2")
        rotation_help.pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(rotation_help, "Rotate the SHG image before analysis. Use User Angle for custom rotation in degrees.")
        self.rotation_mode_combo = ttk.Combobox(
            rotation_row,
            textvariable=self.rotation_mode,
            state="readonly",
            values=list(self.rotation_mode_map.keys()),
            width=30
        )
        self.rotation_mode_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.rotation_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self.toggle_user_angle())
        ttk.Label(rotation_row, text="User Angle", width=12).pack(side=tk.LEFT)
        self.user_angle = ttk.Entry(rotation_row, width=10)
        self.user_angle.insert(0, "0")
        self.user_angle.pack(side=tk.LEFT)

        checks_row_one = ttk.Frame(params_content)
        checks_row_one.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(checks_row_one, text="Enhance Images", variable=self.enhance_var).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(checks_row_one, text="Create Masks", variable=self.create_mask_var).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(checks_row_one, text="Save Figures", variable=self.save_figures_var).pack(side=tk.LEFT)
        save_help_one = ttk.Label(checks_row_one, text=" i", cursor="hand2")
        save_help_one.pack(side=tk.LEFT, padx=(8, 0))
        ToolTip(save_help_one, "Create Masks saves the selected mask outputs. Save Figures writes MATLAB QC plots such as quiver and histogram figures.")

        checks_row_two = ttk.Frame(params_content)
        checks_row_two.pack(fill=tk.X)
        ttk.Checkbutton(checks_row_two, text="Save Stats TXT", variable=self.save_stats_var).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(checks_row_two, text="Save ROI TIF", variable=self.save_roi_var).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(checks_row_two, text="Overwrite Existing Files", variable=self.overwrite_var).pack(side=tk.LEFT)
        save_help_two = ttk.Label(checks_row_two, text=" i", cursor="hand2")
        save_help_two.pack(side=tk.LEFT, padx=(8, 0))
        ToolTip(save_help_two, "Save Stats TXT writes summary text outputs. Save ROI TIF stores the ROI mask image. Overwrite controls whether existing files are replaced.")
        self.toggle_user_angle()
        
        # Output directory
        output_frame = ttk.Frame(self)
        output_frame.pack(fill=tk.X, pady=(0, 10))
        
        label_frame = ttk.Frame(output_frame)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(label_frame, text="Mask Output Folder", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" ℹ️", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(help_btn, "Choose where MATLAB should save masks, figures, and stats output.")
        
        path_input_frame = ttk.Frame(output_frame)
        path_input_frame.pack(fill=tk.X)
        
        self.output_path = ttk.Entry(path_input_frame)
        self.output_path.insert(0, "./results/masks")
        self.output_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(path_input_frame, text="📁", width=3,
                  command=lambda: self.browse_output()).pack(side=tk.RIGHT)
        
        # Create masks button
        create_btn = ttk.Button(self, text="▶ Create Masks", command=self.create_masks)
        create_btn.pack(fill=tk.X)
        ToolTip(create_btn, "Process SHG images with the MATLAB masking runner")
    
    def browse_output(self):
        """Browse for output folder"""
        folder = filedialog.askdirectory()
        if folder:
            self.output_path.delete(0, tk.END)
            self.output_path.insert(0, folder)

    def toggle_user_angle(self):
        """Enable user angle only when custom rotation is selected."""
        if self.rotation_mode_map.get(self.rotation_mode.get(), "none") == "user":
            self.user_angle.configure(state="normal")
        else:
            self.user_angle.configure(state="normal")
            self.user_angle.delete(0, tk.END)
            self.user_angle.insert(0, "0")
            self.user_angle.configure(state="disabled")
    
    def create_masks(self):
        """Create SHG-based masks by calling the MATLAB runner."""
        if not self.shg_upload.get_file():
            self.status_callback("Error: Please select SHG images", 'error', 0)
            messagebox.showerror("Error", "Please select SHG images")
            return

        out_dir = self.output_path.get().strip()
        if not out_dir:
            self.status_callback("Error: Please select a mask output folder", 'error', 0)
            messagebox.showerror("Error", "Please select a mask output folder")
            return

        try:
            bundle_width = float(self.bundle_width.get().strip() or "15")
            bundle_height = float(self.bundle_height.get().strip() or "15")
            low_shg_percentile = float(self.low_shg_percentile.get().strip() or "10")
            user_angle = float(self.user_angle.get().strip() or "0")
        except ValueError:
            self.status_callback("Error: Numeric masking parameters are invalid", 'error', 0)
            messagebox.showerror("Error", "Bundle size, percentile, and angle must be valid numbers.")
            return

        shg_input = self.shg_upload.get_file()
        roi_mode = self.roi_mode.get()
        rot_mode = self.rotation_mode_map.get(self.rotation_mode.get(), "none")
        do_enhance = self.enhance_var.get()
        do_mask = self.create_mask_var.get()
        save_figures = self.save_figures_var.get()
        save_stats = self.save_stats_var.get()
        save_roi = self.save_roi_var.get()
        overwrite_flag = self.overwrite_var.get()
        mask_output_type = self.mask_output_type.get()

        def process():
            try:
                if roi_mode == "draw":
                    self.after(0, lambda: self.status_callback(
                        "MATLAB will open an ROI window for polygon drawing...",
                        "processing",
                        50
                    ))
                run_matlab_mask_job(
                    shg_input,
                    out_dir,
                    bundle_width=bundle_width,
                    bundle_height=bundle_height,
                    do_enhance=do_enhance,
                    do_mask=do_mask,
                    save_figure=save_figures,
                    save_stats=save_stats,
                    save_roi=save_roi,
                    roi_mode=roi_mode,
                    mask_verts=None,
                    low_shg_percentile=low_shg_percentile,
                    rot_mode=rot_mode,
                    user_angle=user_angle,
                    mask_types=mask_output_type,
                    overwrite_flag=overwrite_flag,
                    status_callback=lambda msg, kind, prog: self.after(
                        0, lambda m=msg, k=kind, p=prog: self.status_callback(m, k, p)
                    ),
                )
                self.after(0, lambda: messagebox.showinfo(
                    "Masking Complete",
                    f"MATLAB masking finished.\nOutput saved to:\n{out_dir}"
                ))
            except Exception as exc:
                err_msg = f"Error during MATLAB masking: {exc}"
                self.after(0, lambda: self.status_callback(err_msg, "error", 0))
                self.after(0, lambda: messagebox.showerror("Masking Failed", err_msg))
        
        threading.Thread(target=process, daemon=True).start()


class BuildModelPanel(ttk.LabelFrame):
    """Panel for building shape analysis models"""
    def __init__(self, parent, status_callback, on_model_built):
        super().__init__(parent, text="BUILD MODEL - Create a new shape analysis model", padding=15)
        self.status_callback = status_callback
        self.on_model_built = on_model_built
        
        # Upload fields - side by side
        upload_frame = ttk.Frame(self)
        upload_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        left_frame = ttk.Frame(upload_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.csv_upload = DragDropUploadField(
            left_frame,
            "CSV File Input",
            "CSV file input",
            ".csv",
            "Upload a CSV file with headers: set ID, condition, set location, tag, note."
        )
        self.csv_upload.pack(fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(upload_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        self.raw_upload = DragDropUploadField(
            right_frame,
            "Image Folder",
            "Image folder",
            "image/*",
            "Optional direct folder input. If no CSV is provided, the GUI will auto-generate a build-model CSV from this folder."
        )
        self.raw_upload.pack(fill=tk.BOTH, expand=True)
        
        # Number of coordinates
        coord_frame = ttk.Frame(self)
        coord_frame.pack(fill=tk.X, pady=(0, 10))
        
        label_frame = ttk.Frame(coord_frame)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(label_frame, text="Number of Coordinates", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" ℹ️", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(help_btn, "Number of coordinate points used to define the shape boundary")
        
        self.num_coords = ttk.Entry(coord_frame)
        self.num_coords.insert(0, "50")
        self.num_coords.pack(fill=tk.X)
        
        # Number of shape modes with increment/decrement buttons only
        modes_frame = ttk.Frame(self)
        modes_frame.pack(fill=tk.X, pady=(0, 10))
        
        label_frame = ttk.Frame(modes_frame)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(label_frame, text="Number of Shape Modes", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" ℹ️", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(help_btn, "Number of principal shape variations to capture. Range: 1-10")
        
        controls_frame = ttk.Frame(modes_frame)
        controls_frame.pack(fill=tk.X)
        
        # Decrement button
        ttk.Button(controls_frame, text="▼ Decrease", width=15, 
                  command=self.decrease_modes).pack(side=tk.LEFT, padx=(0, 10))
        
        # Display value
        self.shape_modes_var = tk.IntVar(value=5)
        self.modes_display = tk.Label(controls_frame, text="5", bg="#ffcdd2", fg="#c62828",
                                     font=("Arial", 12, "bold"), width=8, relief=tk.RIDGE, bd=2)
        self.modes_display.pack(side=tk.LEFT, padx=10)
        
        # Increment button
        ttk.Button(controls_frame, text="▲ Increase", width=15,
                  command=self.increase_modes).pack(side=tk.LEFT, padx=(10, 0))
        
        # Output folder
        folder_frame = ttk.Frame(self)
        folder_frame.pack(fill=tk.X, pady=(0, 10))
        
        label_frame = ttk.Frame(folder_frame)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(label_frame, text="Model Output Folder", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" ℹ️", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(help_btn, "Directory where the model will be saved. Default: ./models/output")
        
        path_input_frame = ttk.Frame(folder_frame)
        path_input_frame.pack(fill=tk.X)
        
        self.output_folder = ttk.Entry(path_input_frame)
        self.output_folder.insert(0, "./models/output")
        self.output_folder.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(path_input_frame, text="📁", width=3,
                  command=lambda: self.browse_output()).pack(side=tk.RIGHT)
        
        # Model name
        name_frame = ttk.Frame(self)
        name_frame.pack(fill=tk.X, pady=(0, 10))
        
        label_frame = ttk.Frame(name_frame)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(label_frame, text="Model Name", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" ℹ️", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(help_btn, "Give your model a descriptive name for easy identification")
        
        self.model_name = ttk.Entry(name_frame)
        self.model_name.insert(0, "collagen_fiber_model_v1")
        self.model_name.pack(fill=tk.X)
        
        # Build button
        build_btn = ttk.Button(self, text="▶ Build Model", command=self.build_model)
        build_btn.pack(fill=tk.X)
        ToolTip(build_btn, "Build a new shape analysis model")
    
    def browse_output(self):
        """Browse for output folder"""
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder.delete(0, tk.END)
            self.output_folder.insert(0, folder)

    
    def increase_modes(self):
        current = self.shape_modes_var.get()
        if current < 10:
            self.shape_modes_var.set(current + 1)
            self.modes_display.config(text=str(current + 1))
    
    def decrease_modes(self):
        current = self.shape_modes_var.get()
        if current > 1:
            self.shape_modes_var.set(current - 1)
            self.modes_display.config(text=str(current - 1))
    
    def build_model(self):
        """Build model by running getboundary + mainbody pipeline."""
        csv_path = self.csv_upload.get_file()
        image_folder = self.raw_upload.get_file()
        if not csv_path and not image_folder:
            self.status_callback("Error: Please select a model-build CSV file or image folder", 'error', 0)
            messagebox.showerror("Error", "Please select a model-build CSV file or image folder")
            return

        if not self.model_name.get().strip():
            self.status_callback("Error: Please provide a model name", 'error', 0)
            messagebox.showerror("Error", "Please provide a model name")
            return

        if not self.output_folder.get().strip():
            self.status_callback("Error: Please provide a model output folder", 'error', 0)
            messagebox.showerror("Error", "Please provide a model output folder")
            return

        # Snapshot tkinter values on the main thread before starting worker thread.
        num_coords = self.num_coords.get().strip() or "50"
        clnum = str(self.shape_modes_var.get())
        outpth = self.output_folder.get().strip()
        model_name = self.model_name.get().strip()
        if not csv_path and image_folder:
            csv_path = self.create_build_dataset_csv(image_folder, outpth)

        def process():
            status_state = {"message": "Initializing model build..."}

            def set_status_from_legacy(text):
                status_state["message"] = text
                status_type = "error" if str(text).lower().startswith("error") else "processing"
                if threading.current_thread() is threading.main_thread():
                    self.status_callback(text, status_type, 0)
                else:
                    self.after(0, lambda: self.status_callback(text, status_type, 0))

            entries = {
                "Image sets to build": LegacyTextAdapter(getter=lambda: csv_path),
                "Number of coordinates": LegacyTextAdapter(getter=lambda: num_coords),
                "Number of shape modes": LegacyTextAdapter(getter=lambda: clnum),
                "Model output folder": LegacyTextAdapter(getter=lambda: outpth),
                "Model name": LegacyTextAdapter(getter=lambda: model_name),
                "Status": LegacyTextAdapter(getter=lambda: status_state["message"], setter=set_status_from_legacy),
                "Model to apply": LegacyTextAdapter(getter=lambda: ""),
            }
            progress_adapter = LegacyProgressAdapter(self, self.status_callback, lambda: status_state["message"])

            try:
                self.status_callback("Extracting boundaries...", "processing", 5)
                getboundary(csv_path, progress_adapter, entries)

                self.status_callback("Building model...", "processing", 60)
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
                self.save_model(model_data)
                self.status_callback("Model built and saved successfully!", "success", 100)
                messagebox.showinfo(
                    "Build Complete",
                    f"Model built successfully.\n"
                    f"Model name: {model_name}\n"
                    f"Model path: {model_path if model_path else 'Created (path not resolved)'}"
                )
            except Exception as exc:
                err_msg = f"Error during model build: {exc}"
                self.status_callback(err_msg, "error", 0)
                messagebox.showerror("Model Build Failed", err_msg)

        # Run on main thread: legacy pipeline uses Tk/Matplotlib TkAgg internally.
        process()

    def create_build_dataset_csv(self, image_folder, output_folder):
        """Create a temporary dataset CSV so build-model can run from a folder."""
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
    
    def save_model(self, model_data):
        """Save the built model"""
        self.on_model_built(model_data)
        self.status_callback(f'Model "{model_data["name"]}" saved successfully!', 'success', 0)
    
    def discard_model(self):
        """Discard the built model"""
        self.status_callback('Model discarded', 'idle', 0)


class ApplyModelPanel(ttk.LabelFrame):
    """Panel for applying models to new datasets"""
    def __init__(self, parent, status_callback, built_model_getter):
        super().__init__(parent, text="APPLY MODEL - Apply trained model to new image sets", padding=15)
        self.status_callback = status_callback
        self.built_model_getter = built_model_getter
        self.use_built_model_var = tk.BooleanVar(value=False)
        self.valid_pipeline_ext = {".cpproj", ".cppipe"}
        
        # Built model notice (will be shown when model is available)
        self.model_notice_frame = tk.Frame(self, bg="#e8f5e9", relief=tk.RIDGE, bd=2)
        self.model_notice_frame.pack(fill=tk.X, pady=(0, 10))
        self.model_notice_frame.pack_forget()  # Hidden initially
        
        notice_content = ttk.Frame(self.model_notice_frame)
        notice_content.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(notice_content, text="⚡", bg="#e8f5e9", font=("Arial", 12)).pack(side=tk.LEFT, padx=(0, 10))
        
        self.model_info_label = tk.Label(notice_content, text="", bg="#e8f5e9",
                                         font=("Arial", 9), justify=tk.LEFT)
        self.model_info_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Checkbutton(notice_content, text="Use this model", variable=self.use_built_model_var,
                       command=self.toggle_model_file).pack(side=tk.RIGHT)
        
        cp_launch_frame = tk.Frame(self, bg="#f0f0f0", relief=tk.RIDGE, bd=2)
        cp_launch_frame.pack(fill=tk.X, pady=(0, 10))

        cp_launch_label = ttk.Frame(cp_launch_frame)
        cp_launch_label.pack(fill=tk.X, padx=10, pady=(8, 4))
        ttk.Label(cp_launch_label, text="CellProfiler Masking Pipeline", font=("Arial", 10, "bold")).pack(side=tk.LEFT)
        cp_help = ttk.Label(cp_launch_label, text=" i", cursor="hand2")
        cp_help.pack(side=tk.LEFT)
        ToolTip(
            cp_help,
            "Open a CellProfiler masking pipeline, such as Masking_pipeline.cpproj, to apply SHG masks onto staining images."
        )

        cp_body = ttk.Frame(cp_launch_frame)
        cp_body.pack(fill=tk.X, padx=10, pady=(0, 10))

        cp_exec_label = ttk.Frame(cp_body)
        cp_exec_label.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(cp_exec_label, text="CellProfiler Executable", font=("Arial", 9, "bold")).pack(side=tk.LEFT)

        cp_exec_input = ttk.Frame(cp_body)
        cp_exec_input.pack(fill=tk.X, pady=(0, 10))
        self.mask_cp_executable = ttk.Entry(cp_exec_input)
        self.mask_cp_executable.insert(0, self.get_default_cp_executable())
        self.mask_cp_executable.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(cp_exec_input, text="...", width=3, command=self.browse_mask_cp_executable).pack(side=tk.RIGHT)

        pipeline_label = ttk.Frame(cp_body)
        pipeline_label.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(pipeline_label, text="Masking Pipeline Option", font=("Arial", 9, "bold")).pack(side=tk.LEFT)

        preset_pipeline = self.resolve_masking_pipeline_preset()
        self.mask_pipeline_choice = tk.StringVar(
            value="Masking Pipeline" if preset_pipeline else "Custom Pipeline"
        )
        self.mask_pipeline_combo = ttk.Combobox(
            cp_body,
            textvariable=self.mask_pipeline_choice,
            state="readonly",
            values=["Masking Pipeline", "Open CellProfiler"]
        )
        self.mask_pipeline_combo.pack(fill=tk.X, pady=(0, 10))
        self.mask_pipeline_combo.bind("<<ComboboxSelected>>", lambda _event: self.toggle_mask_pipeline_upload())
        self.toggle_mask_pipeline_upload()

        cp_launch_btn = ttk.Button(cp_body, text="Open Masking Pipeline", command=self.start_masking_pipeline)
        cp_launch_btn.pack(fill=tk.X)
        ToolTip(
            cp_launch_btn,
            "Launch CellProfiler with the selected masking pipeline. Choose image, mask, and output folders inside CellProfiler."
        )

        self.input_mode_frame = ttk.Frame(self)
        self.input_mode_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(self.input_mode_frame, text="Segmented Image Input Type", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(0, 5))
        self.apply_input_mode = tk.StringVar(value="CSV")
        self.apply_input_mode_combo = ttk.Combobox(
            self.input_mode_frame,
            textvariable=self.apply_input_mode,
            state="readonly",
            values=["CSV", "Folder"]
        )
        self.apply_input_mode_combo.pack(fill=tk.X)
        self.apply_input_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self.toggle_apply_input_mode())

        self.apply_csv_upload = DragDropUploadField(
            self,
            "Image Set (CSV)",
            "CSV file with image paths",
            ".csv",
            "Upload a CSV file containing set ID, condition, set location, tag, and note columns."
        )
        self.apply_csv_upload.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.image_folder_upload = DragDropUploadField(
            self,
            "Images Folder",
            "Folder with images to analyze",
            "image/*",
            "Select the folder containing the images you want to analyze with the model."
        )
        self.image_folder_upload.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.toggle_apply_input_mode()

        self.model_upload_container = ttk.Frame(self)
        self.model_upload_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.model_upload = DragDropUploadField(
            self.model_upload_container,
            "Model to Apply",
            "Drag and drop or click to select model (.pkl/.pickle)",
            ".pkl,.pickle",
            "Upload a previously saved model file to apply to the images"
        )
        self.model_upload.pack(fill=tk.BOTH, expand=True)
        self.input_mode_frame.pack_forget()
        self.input_mode_frame.pack(fill=tk.X, pady=(0, 10), after=self.model_upload_container)
        self.apply_csv_upload.pack_forget()
        self.image_folder_upload.pack_forget()
        self.toggle_apply_input_mode()

        # Output folder
        folder_frame = ttk.Frame(self)
        folder_frame.pack(fill=tk.X, pady=(0, 10))
        
        label_frame = ttk.Frame(folder_frame)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(label_frame, text="Result Output Folder", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" ℹ️", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(help_btn, "Directory where analysis results will be saved. Default: ./results/model_output")
        
        path_input_frame = ttk.Frame(folder_frame)
        path_input_frame.pack(fill=tk.X)
        
        self.output_folder = ttk.Entry(path_input_frame)
        self.output_folder.insert(0, "./results/model_output")
        self.output_folder.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(path_input_frame, text="📁", width=3,
                  command=lambda: self.browse_output()).pack(side=tk.RIGHT)
        # Apply button
        apply_btn = ttk.Button(self, text="▶ Apply Model", command=self.apply_model)
        apply_btn.pack(fill=tk.X, pady=(0, 10))
        ToolTip(apply_btn, "Apply the selected model to images")
    
    def browse_output(self):
        """Browse for output folder"""
        folder = filedialog.askdirectory()
        if folder:
            self.output_folder.delete(0, tk.END)
            self.output_folder.insert(0, folder)

    def browse_mask_cp_executable(self):
        """Browse for CellProfiler executable used by the masking pipeline."""
        exe = filedialog.askopenfilename()
        if exe:
            self.mask_cp_executable.delete(0, tk.END)
            self.mask_cp_executable.insert(0, exe)

    def toggle_apply_input_mode(self):
        """Show either CSV input or folder input for apply-model workflow."""
        if self.apply_input_mode.get() == "CSV":
            self.image_folder_upload.pack_forget()
            self.apply_csv_upload.pack(fill=tk.BOTH, expand=True, pady=(0, 10), after=self.input_mode_frame)
        else:
            self.apply_csv_upload.pack_forget()
            self.image_folder_upload.pack(fill=tk.BOTH, expand=True, pady=(0, 10), after=self.input_mode_frame)

    def toggle_mask_pipeline_upload(self):
        """No-op placeholder now that custom mode simply opens CellProfiler."""
        return

    def get_default_cp_executable(self):
        """Best-effort default CellProfiler executable path."""
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

    def resolve_cp_executable(self, cp_exec):
        """Resolve OS-specific CellProfiler launch targets when possible."""
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
            text=True
        )
        target = (result.stdout or "").strip()
        if result.returncode == 0 and target:
            return target
        return cp_exec

    def cp_executable_exists(self, cp_exec):
        """Check whether the chosen CellProfiler executable is callable."""
        if not cp_exec:
            return False
        if sys.platform == "darwin":
            if cp_exec.lower().endswith(".app"):
                return os.path.isdir(cp_exec)
            if cp_exec in {"cellprofiler", "CellProfiler"} and shutil.which("open") is not None:
                return True
        return os.path.isfile(cp_exec) or shutil.which(cp_exec) is not None

    def build_cp_command(self, cp_exec, pipeline_path=None):
        """Build a platform-appropriate CellProfiler command."""
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

    def resolve_masking_pipeline_preset(self):
        """Resolve repo-local masking pipeline when present."""
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

    def resolve_selected_masking_pipeline(self):
        """Resolve the pipeline path from the preset/custom dropdown."""
        if self.mask_pipeline_choice.get() == "Open CellProfiler":
            return None
        return self.resolve_masking_pipeline_preset()

    def start_masking_pipeline(self):
        """Launch CellProfiler with the masking pipeline."""
        cp_exec = self.resolve_cp_executable(self.mask_cp_executable.get().strip())
        pipeline_path = self.resolve_selected_masking_pipeline()

        if not self.cp_executable_exists(cp_exec):
            self.status_callback("Error: CellProfiler executable not found", "error", 0)
            messagebox.showerror(
                "CellProfiler Not Found",
                "The selected CellProfiler executable could not be found.\n\n"
                f"Current value:\n{cp_exec or '(empty)'}\n\n"
                "Use the browse button to select the CellProfiler executable, or enter a command on your PATH."
            )
            return

        if self.mask_pipeline_choice.get() != "Open CellProfiler" and not pipeline_path:
            self.status_callback("Error: Please select a masking pipeline", "error", 0)
            messagebox.showerror("Error", "Please upload Masking_pipeline.cpproj or Masking_pipeline.cppipe.")
            return

        if pipeline_path and Path(pipeline_path).suffix.lower() not in self.valid_pipeline_ext:
            self.status_callback("Error: Masking pipeline must be .cpproj or .cppipe", "error", 0)
            messagebox.showerror("Error", "Masking pipeline must be a .cpproj or .cppipe file.")
            return

        def process():
            self.after(0, lambda: self.status_callback("Launching CellProfiler masking pipeline...", "processing", 20))
            cmd = self.build_cp_command(cp_exec, pipeline_path)
            try:
                subprocess.Popen(cmd)
            except Exception as exc:
                self.after(0, lambda: self.status_callback("CellProfiler failed", "error", 0))
                self.after(0, lambda: messagebox.showerror(
                    "CellProfiler Launch Failed",
                    f"Could not start CellProfiler.\n\nCommand:\n{' '.join(cmd)}\n\nError:\n{exc}"
                ))
                return

            self.after(0, lambda: self.status_callback("CellProfiler masking pipeline launched", "success", 100))
            self.after(0, lambda: messagebox.showinfo(
                "CellProfiler Launched",
                f"CellProfiler: {cp_exec}\n"
                + (f"Masking pipeline: {pipeline_path}\n" if pipeline_path else "Mode: Open CellProfiler only\n")
                + "Choose the staining-image input folder, mask folder, and output folder inside CellProfiler."
            ))

        threading.Thread(target=process, daemon=True).start()

    def create_apply_dataset_csv(self, image_folder, output_folder):
        """Create a temporary dataset CSV so the legacy pipeline can run from a folder."""
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

    def update_model_notice(self, model_data):
        """Update the built model notice"""
        if model_data:
            info_text = f"Model \"{model_data['name']}\" is ready to use!\nCreated: {model_data['timestamp']} • {model_data['shape_modes']} shape modes"
            self.model_info_label.config(text=info_text)
            self.model_notice_frame.pack(fill=tk.X, pady=(0, 10))
        else:
            self.model_notice_frame.pack_forget()
    
    def toggle_model_file(self):
        """Toggle model file upload visibility"""
        if self.use_built_model_var.get():
            self.model_upload_container.pack_forget()
        else:
            self.model_upload_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    
    def apply_model(self):
        """Apply model by running getboundary + mainbody pipeline."""
        csv_path = None
        if self.apply_input_mode.get() == "CSV":
            csv_path = self.apply_csv_upload.get_file()
            if not csv_path:
                self.status_callback("Error: Please select an image set CSV file", 'error', 0)
                messagebox.showerror("Error", "Please select an image set CSV file")
                return
        else:
            image_folder = self.image_folder_upload.get_file()
            if not image_folder:
                self.status_callback("Error: Please select an images folder", 'error', 0)
                messagebox.showerror("Error", "Please select an images folder")
                return

        built_model = self.built_model_getter()
        if self.use_built_model_var.get():
            model_path = built_model.get("path") if built_model else None
            if not model_path:
                self.status_callback("Error: Built model path is unavailable. Select a model pickle file.", 'error', 0)
                messagebox.showerror("Error", "Built model path is unavailable. Select a model pickle file.")
                return
        else:
            model_path = self.model_upload.get_file()
            if not model_path:
                self.status_callback("Error: Please select a model pickle file or use the built model", 'error', 0)
                messagebox.showerror("Error", "Please select a model pickle file or use the built model")
                return

        if not self.output_folder.get().strip():
            self.status_callback("Error: Please provide a result output folder", 'error', 0)
            messagebox.showerror("Error", "Please provide a result output folder")
            return

        # Snapshot tkinter values on the main thread before starting worker thread.
        outpth = self.output_folder.get().strip()
        if self.apply_input_mode.get() != "CSV":
            csv_path = self.create_apply_dataset_csv(image_folder, outpth)

        def process():
            status_state = {"message": "Initializing model application..."}

            def set_status_from_legacy(text):
                status_state["message"] = text
                status_type = "error" if str(text).lower().startswith("error") else "processing"
                if threading.current_thread() is threading.main_thread():
                    self.status_callback(text, status_type, 0)
                else:
                    self.after(0, lambda: self.status_callback(text, status_type, 0))

            entries = {
                "Image sets to apply": LegacyTextAdapter(getter=lambda: csv_path),
                "Result output folder": LegacyTextAdapter(getter=lambda: outpth),
                "Model to apply": LegacyTextAdapter(getter=lambda: model_path),
                "Number of coordinates": LegacyTextAdapter(getter=lambda: "50"),
                "Status": LegacyTextAdapter(getter=lambda: status_state["message"], setter=set_status_from_legacy),
            }
            progress_adapter = LegacyProgressAdapter(self, self.status_callback, lambda: status_state["message"])

            try:
                self.status_callback("Extracting boundaries...", "processing", 5)
                getboundary(csv_path, progress_adapter, entries)

                self.status_callback("Applying model to image set...", "processing", 60)
                mainbody(False, csv_path, entries, outpth, None, progress_adapter)

                self.status_callback("Model applied successfully!", "success", 100)

                # TODO(stats): call your statistical analysis module here using model outputs.
                messagebox.showinfo(
                    "Apply Complete",
                    f"Model application finished.\nResults saved to:\n{outpth}"
                )
            except Exception as exc:
                err_msg = f"Error during model application: {exc}"
                self.status_callback(err_msg, "error", 0)
                messagebox.showerror("Model Apply Failed", err_msg)

        # Run on main thread: avoids Tk/Tcl async deletion errors from TkAgg in worker threads.
        process()


class VampireAnalysisApp:
    """Main application window"""
    def __init__(self, root):
        self.root = root
        self.root.title("Vampire Analysis - Shape Mode Analysis Tool v2")
        self.root.geometry("550x600")
        
        # Built model storage
        self.built_model = None
        
        # Configure styles
        self.setup_styles()
        
        # Header
        header = tk.Frame(root, bg="#c62828", height=80)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text="VAMPIRE Analysis", bg="#c62828", fg="white",
                font=("Arial", 20, "bold")).pack(pady=(15, 5))
        tk.Label(header, text="Advanced shape mode analysis and model application tool", 
                bg="#c62828", fg="#ffcdd2", font=("Arial", 10)).pack()
        
        # Main content with scrollbar
        main_container = ttk.Frame(root)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(main_container, bg="#f5f5f5")
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Enable mousewheel scrolling
        def on_mousewheel(event):
            if sys.platform == "darwin":
                step = -1 if event.delta > 0 else 1
            else:
                step = int(-1 * (event.delta / 120))
            if step != 0:
                canvas.yview_scroll(step, "units")

        def on_linux_scroll(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)
        canvas.bind_all("<Button-4>", on_linux_scroll)
        canvas.bind_all("<Button-5>", on_linux_scroll)

        # Keep the scrollable frame width synced with the canvas width so panels expand on resize.
        def on_canvas_configure(event):
            canvas.itemconfigure(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)
        
        content = ttk.Frame(scrollable_frame, padding=20)
        content.pack(fill=tk.BOTH, expand=True)
        
        # Panels in new order
        self.segmentation_panel = SegmentationPanel(content, self.update_status)
        self.segmentation_panel.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        self.masking_panel = MaskingPanel(content, self.update_status)
        self.masking_panel.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        self.build_panel = BuildModelPanel(content, self.update_status, self.on_model_built)
        self.build_panel.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        self.apply_panel = ApplyModelPanel(content, self.update_status, self.get_built_model)
        self.apply_panel.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Add some bottom padding
        ttk.Frame(content, height=100).pack()
        
        # Status bar
        self.status_bar = StatusBar(root)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def setup_styles(self):
        """Configure ttk styles"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure colors for different states
        style.configure('TFrame', background='#f5f5f5')
        style.configure('TLabel', background='#f5f5f5')
        style.configure('TLabelframe', background='#ffffff', borderwidth=2, relief=tk.RIDGE)
        style.configure('TLabelframe.Label', font=('Arial', 11, 'bold'))
    
    def update_status(self, message, status_type='processing', progress=0):
        """Update status bar"""
        self.status_bar.set_status(message, status_type, progress)
    
    def on_model_built(self, model_data):
        """Callback when model is built and saved"""
        self.built_model = model_data
        self.apply_panel.update_model_notice(model_data)
    
    def get_built_model(self):
        """Get the currently built model"""
        return self.built_model


def main():
    """Main entry point"""
    root = tk.Tk()
    app = VampireAnalysisApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()


