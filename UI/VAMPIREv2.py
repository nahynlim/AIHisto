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
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
from mainbody import mainbody
from getboundary import getboundary


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
        super().__init__(parent, text="Segmentation - CellProfiler pipeline for raw image processing", padding=15)
        self.status_callback = status_callback
        self.valid_image_ext = {".tiff", ".tif", ".jpeg", ".jpg", ".png", ".bmp", ".gif"}
        self.valid_pipeline_ext = {".cpproj", ".cppipe"}
        base_dir = os.path.dirname(os.path.abspath(__file__))

        # Presets are resolved dynamically from common repo-relative locations.
        self.pipeline_presets = {
            "Blue Stained DAPI": "Blue_Nuclei_Segmentation_Pipeline.cppipe",
            "Normal Staining": "Nuclei_Segmentation_Pipeline.cppipe",
        }
        self.launch_option = "Launch CellProfiler (Interactive)"

        # Raw images folder upload
        # Raw images are now selected inside CellProfiler (interactive mode).

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

        # Open CellProfiler button
        segment_btn = ttk.Button(self, text="Open CellProfiler", command=self.start_segmentation)
        segment_btn.pack(fill=tk.X)
        ToolTip(segment_btn, "Open CellProfiler with the selected pipeline")

        # No custom pipeline upload option.
    def browse_cp_executable(self):
        """Browse for CellProfiler executable"""
        exe = filedialog.askopenfilename()
        if exe:
            self.cp_executable.delete(0, tk.END)
            self.cp_executable.insert(0, exe)

    def get_default_cp_executable(self):
        """Best-effort default CellProfiler executable path."""
        windows_lnk = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\CellProfiler.lnk"
        if os.path.isfile(windows_lnk):
            return windows_lnk
        mac_cp = "/Applications/CellProfiler.app/Contents/MacOS/cp"
        if os.path.isfile(mac_cp):
            return mac_cp
        return "cellprofiler"

    def resolve_cp_executable(self, cp_exec):
        """Resolve a Windows .lnk shortcut to its target executable when possible."""
        if not cp_exec:
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
        return os.path.isfile(cp_exec) or shutil.which(cp_exec) is not None

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
                self.status_callback("Error: Please select a valid .cpproj/.cppipe pipeline", 'error', 0)
                messagebox.showerror(
                    "Error",
                    "Pipeline not found. Keep pipeline files in project root or ./pipelines, "
                    "or choose 'Upload Your Own'."
                )
                return
            if not os.path.isfile(pipeline_path):
                self.status_callback("Error: Pipeline file not found", 'error', 0)
                messagebox.showerror("Error", f"Pipeline file not found:\n{pipeline_path}")
                return
            if Path(pipeline_path).suffix.lower() not in self.valid_pipeline_ext:
                self.status_callback("Error: Pipeline must be .cpproj or .cppipe", 'error', 0)
                messagebox.showerror("Error", "Pipeline must be a .cpproj or .cppipe file")
                return

        def process():
            self.after(0, lambda: self.status_callback("Initializing CellProfiler...", "processing", 10))
            env = os.environ.copy()
            env["MPLBACKEND"] = "Agg"
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)

            if pipeline_path:
                cmd = [cp_exec, "-p", pipeline_path]
                run_msg = "Launching CellProfiler with selected pipeline..."
            else:
                cmd = [cp_exec]
                run_msg = "Launching CellProfiler interactive app..."
            self.after(0, lambda: self.status_callback(run_msg, "processing", 40))
            try:
                result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            except Exception as exc:
                self.after(0, lambda: self.status_callback("CellProfiler failed", "error", 0))
                self.after(0, lambda: messagebox.showerror(
                    "Segmentation Failed",
                    f"Could not start CellProfiler.\n\nCommand:\n{' '.join(cmd)}\n\nError:\n{exc}"
                ))
                return

            if result.returncode != 0:
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
                return

            self.after(0, lambda: self.status_callback("CellProfiler launched", "success", 100))
            self.after(0, lambda: messagebox.showinfo(
                "CellProfiler Launched",
                f"CellProfiler: {cp_exec}\n"
                f"Selected pipeline: {pipeline_path if pipeline_path else 'Choose in CellProfiler'}\n"
                "Input/output: choose in CellProfiler"
            ))

        threading.Thread(target=process, daemon=True).start()
class MaskingPanel(ttk.LabelFrame):
    """Panel for SHG-based masking with damage region analysis"""
    def __init__(self, parent, status_callback):
        super().__init__(parent, text="🎭 Masking - SHG damage region mask creation and application", padding=15)
        self.status_callback = status_callback
        
        # Upload folders - side by side
        upload_frame = ttk.Frame(self)
        upload_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        left_frame = ttk.Frame(upload_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.shg_upload = DragDropUploadField(
            left_frame,
            "SHG Images Folder",
            "SHG images for mask creation",
            "image/*",
            "SHG images will be processed to create binary masks identifying damage regions",
            icon='folder'
        )
        self.shg_upload.pack(fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(upload_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        self.segmented_upload = DragDropUploadField(
            right_frame,
            "Segmented Images Folder",
            "Segmented images to apply mask",
            "image/*",
            "Segmented images to which the SHG-derived mask will be applied",
            icon='folder'
        )
        self.segmented_upload.pack(fill=tk.BOTH, expand=True)
        
        # Mask options
        mask_options_frame = tk.Frame(self, bg="#f0f0f0", relief=tk.RIDGE, bd=2)
        mask_options_frame.pack(fill=tk.X, pady=(0, 10))
        
        tk.Label(mask_options_frame, text="Mask Application Mode", 
                bg="#f0f0f0", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=10, pady=5)
        
        options_content = ttk.Frame(mask_options_frame)
        options_content.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        self.mask_mode = tk.StringVar(value="none")
        
        # Radio buttons for mask mode
        none_radio = ttk.Radiobutton(options_content, text="No Mask", 
                                     variable=self.mask_mode, value="none")
        none_radio.pack(anchor=tk.W, padx=20, pady=2)
        ToolTip(none_radio, "Output segmented images without any masking")
        
        damaged_radio = ttk.Radiobutton(options_content, text="Mask (Damaged Regions Only)", 
                                       variable=self.mask_mode, value="mask")
        damaged_radio.pack(anchor=tk.W, padx=20, pady=2)
        ToolTip(damaged_radio, "Apply mask to show only damaged regions identified by SHG")
        
        undamaged_radio = ttk.Radiobutton(options_content, text="Inverse Mask (Undamaged Regions Only)", 
                                         variable=self.mask_mode, value="inverse")
        undamaged_radio.pack(anchor=tk.W, padx=20, pady=2)
        ToolTip(undamaged_radio, "Apply inverse mask to show only undamaged regions")
        
        # Output directory
        output_frame = ttk.Frame(self)
        output_frame.pack(fill=tk.X, pady=(0, 10))
        
        label_frame = ttk.Frame(output_frame)
        label_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(label_frame, text="Masked Images Output Directory", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        help_btn = ttk.Label(label_frame, text=" ℹ️", cursor="hand2")
        help_btn.pack(side=tk.LEFT)
        ToolTip(help_btn, "Directory where masked/unmasked images will be saved")
        
        path_input_frame = ttk.Frame(output_frame)
        path_input_frame.pack(fill=tk.X)
        
        self.output_path = ttk.Entry(path_input_frame)
        self.output_path.insert(0, "./results/masked_images")
        self.output_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(path_input_frame, text="📁", width=3,
                  command=lambda: self.browse_output()).pack(side=tk.RIGHT)
        
        # Create masks button
        create_btn = ttk.Button(self, text="▶ Create Masks", command=self.create_masks)
        create_btn.pack(fill=tk.X)
        ToolTip(create_btn, "Process SHG images to create masks and apply to segmented images")
    
    def browse_output(self):
        """Browse for output folder"""
        folder = filedialog.askdirectory()
        if folder:
            self.output_path.delete(0, tk.END)
            self.output_path.insert(0, folder)
    
    def create_masks(self):
        """Create and apply SHG-based masks"""
        if not self.shg_upload.get_file():
            self.status_callback("Error: Please select SHG images folder", 'error', 0)
            messagebox.showerror("Error", "Please select SHG images folder")
            return
        
        if not self.segmented_upload.get_file():
            self.status_callback("Error: Please select segmented images folder", 'error', 0)
            messagebox.showerror("Error", "Please select segmented images folder")
            return
        
        def process():
            # TODO(masking): Replace this simulated flow with your external masking module call.
            # TODO(intersection): Compute segmentation-mask intersection here
            # (e.g., segmented * mask, or segmented * (1 - mask) for inverse mode)
            # before saving outputs to self.output_path.get().
            # TODO(masking-save): save mask and intersection outputs to self.output_path.get()
            mask_mode_text = {
                'none': 'no masking',
                'mask': 'damaged region masking',
                'inverse': 'undamaged region masking'
            }
            mode_desc = mask_mode_text.get(self.mask_mode.get(), 'masking')
            
            steps = [
                (20, 'Loading SHG images...'),
                (40, 'Creating binary masks from SHG data...'),
                (60, 'Loading segmented images...'),
                (80, f'Applying {mode_desc}...'),
                (100, 'Mask creation and application completed!')
            ]
            
            for progress, message in steps:
                time.sleep(0.7)
                self.status_callback(message, 'processing', progress)
            
            time.sleep(0.5)
            self.status_callback(f'Masking completed with {mode_desc}!', 'success', 100)
            self.after(0, lambda: messagebox.showinfo(
                "Masking Complete",
                f"Masking mode: {mode_desc}\nOutput saved to:\n{self.output_path.get()}"
            ))
        
        threading.Thread(target=process, daemon=True).start()


class BuildModelPanel(ttk.LabelFrame):
    """Panel for building shape analysis models"""
    def __init__(self, parent, status_callback, on_model_built):
        super().__init__(parent, text="⚙️ Build Model - Create a new shape analysis model", padding=15)
        self.status_callback = status_callback
        self.on_model_built = on_model_built
        
        # Upload fields - side by side
        upload_frame = ttk.Frame(self)
        upload_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        left_frame = ttk.Frame(upload_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        self.csv_upload = DragDropUploadField(
            left_frame,
            "Image Set (CSV)",
            "CSV file with image paths",
            ".csv",
            "Upload a CSV file containing paths to images for model building"
        )
        self.csv_upload.pack(fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(upload_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        self.raw_upload = DragDropUploadField(
            right_frame,
            "Raw Images (Optional)",
            "Direct image upload",
            "image/*",
            "Alternatively, upload raw images directly instead of using a CSV file",
            allow_multiple=True
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
        image_folder = self.image_folder_upload.get_file()
        if not image_folder:
            self.status_callback("Error: Please select an images folder", 'error', 0)
            messagebox.showerror("Error", "Please select an images folder")
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
        super().__init__(parent, text="💻 Apply Model - Apply trained model to new image sets", padding=15)
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

        self.image_folder_upload = DragDropUploadField(
            self,
            "Images Folder",
            "Folder with images to analyze",
            "image/*",
            "Select the folder containing the images you want to analyze with the model."
        )
        self.image_folder_upload.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

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

    def toggle_mask_pipeline_upload(self):
        """No-op placeholder now that custom mode simply opens CellProfiler."""
        return

    def get_default_cp_executable(self):
        """Best-effort default CellProfiler executable path."""
        windows_lnk = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\CellProfiler.lnk"
        if os.path.isfile(windows_lnk):
            return windows_lnk
        mac_cp = "/Applications/CellProfiler.app/Contents/MacOS/cp"
        if os.path.isfile(mac_cp):
            return mac_cp
        return "cellprofiler"

    def resolve_cp_executable(self, cp_exec):
        """Resolve a Windows .lnk shortcut to its target executable when possible."""
        if not cp_exec:
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
        return os.path.isfile(cp_exec) or shutil.which(cp_exec) is not None

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
            cmd = [cp_exec] if pipeline_path is None else [cp_exec, "-p", pipeline_path]
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
        df = pd.DataFrame([
            {
                "set ID": 1,
                "condition": folder_name,
                "set location": image_folder,
                "tag": "",
                "note": "Auto-generated from Apply Model folder selection",
            }
        ])
        df.to_csv(csv_path, index=False)
        return csv_path

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
        self.root.geometry("950x950")
        
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
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

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


