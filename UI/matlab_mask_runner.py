"""MATLAB-backed masking runner for the GUI."""

from __future__ import annotations

import glob
import os
from typing import Callable, Optional


def _emit(status_callback: Optional[Callable[[str, str, int], None]], message: str, status_type: str, progress: int) -> None:
    if status_callback is not None:
        status_callback(message, status_type, progress)


def _resolve_matlab_dir(base_dir: str) -> str:
    candidates = [
        os.path.join(base_dir, "matlab"),
        os.path.join(base_dir, "MATLAB"),
    ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    raise FileNotFoundError("Could not find a MATLAB script folder. Expected ./matlab or ./MATLAB.")


def _collect_shg_files(img_input) -> list[str]:
    if not img_input:
        raise ValueError("SHG input path is required.")

    if isinstance(img_input, (list, tuple)):
        parts = [str(p).strip() for p in img_input if str(p).strip()]
    else:
        parts = [p.strip() for p in str(img_input).split(",") if p.strip()]
    img_files: list[str] = []
    for path in parts:
        if os.path.isdir(path):
            img_files.extend(sorted(glob.glob(os.path.join(path, "*.tif"))))
            img_files.extend(sorted(glob.glob(os.path.join(path, "*.tiff"))))
        else:
            img_files.append(path)

    shg_files = sorted(
        str(path)
        for path in img_files
        if os.path.isfile(path) and path.lower().endswith("_0000.tif")
    )
    if not shg_files:
        raise FileNotFoundError("No SHG files ending in '_0000.tif' were found in the selected input.")
    return shg_files


def run_matlab_mask_job(
    img_input,
    out_dir: str,
    *,
    bundle_width: float = 15.0,
    bundle_height: float = 15.0,
    do_enhance: bool = False,
    do_mask: bool = True,
    save_figure: bool = True,
    roi_mode: str = "auto",
    mask_verts: Optional[list[list[float]]] = None,
    low_shg_percentile: float = 10.0,
    rot_mode: str = "none",
    user_angle: float = 0.0,
    mask_types: str = "all",
    overwrite_flag: bool = True,
    matlab_function_name: str = "run_FFT_align_msk_v3_autoROI_from_python",
    status_callback: Optional[Callable[[str, str, int], None]] = None,
) -> None:
    """Run the MATLAB masking workflow from GUI-supplied inputs."""
    _emit(status_callback, "Preparing MATLAB masking job...", "processing", 10)

    if not out_dir:
        raise ValueError("Output directory is required.")
    if not 0 <= float(low_shg_percentile) <= 100:
        raise ValueError("Low SHG percentile must be between 0 and 100.")
    if roi_mode not in {"auto", "draw", "none"}:
        raise ValueError("ROI mode must be one of: auto, draw, none.")
    if rot_mode not in {"none", "vertical", "horizontal", "user"}:
        raise ValueError("Rotation mode must be one of: none, vertical, horizontal, user.")
    if mask_types not in {"all", "damaged", "undamaged", "low_shg", "high_shg"}:
        raise ValueError("Mask output type must be one of: all, damaged, undamaged, low_shg, high_shg.")
    if roi_mode == "draw" and not mask_verts:
        raise ValueError("ROI draw mode requires polygon vertices from the GUI.")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    script_dir = _resolve_matlab_dir(base_dir)
    os.makedirs(out_dir, exist_ok=True)
    img_files = _collect_shg_files(img_input)

    _emit(status_callback, "Starting MATLAB engine...", "processing", 25)
    try:
        import matlab.engine  # type: ignore
        import matlab  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "MATLAB Engine for Python is not installed in this environment."
        ) from exc

    eng = None
    try:
        eng = matlab.engine.start_matlab()
        eng.addpath(script_dir, nargout=0)

        _emit(status_callback, "Checking MATLAB masking function...", "processing", 40)
        function_path = eng.which(matlab_function_name)
        if not function_path:
            raise RuntimeError(
                f"MATLAB function '{matlab_function_name}' was not found in {script_dir}. "
                "Add that wrapper .m file before running the GUI masking workflow."
            )

        matlab_mask_verts = matlab.double(mask_verts) if mask_verts else matlab.double([])

        args = [
            [str(path) for path in img_files],
            str(out_dir),
            bool(do_enhance),
            float(bundle_width),
            float(bundle_height),
            "interactive", False,
            "mask_mode", str(roi_mode),
        ]

        if roi_mode == "draw" and mask_verts:
            args.extend(["maskVerts", matlab_mask_verts])

        args.extend([
            "low_shg_percentile", float(low_shg_percentile),
            "rot_mode", str(rot_mode),
            "user_angle", float(user_angle),
            "mask_types", str(mask_types),
            "save_masks", bool(do_mask),
            "save_stats", True,
            "save_roi", True,
            "save_figures", bool(save_figure),
            "overwrite", bool(overwrite_flag),
        ])

        _emit(status_callback, "Running MATLAB mask creation...", "processing", 60)
        getattr(eng, matlab_function_name)(*args, nargout=0)
        _emit(status_callback, "MATLAB mask creation completed!", "success", 100)
    finally:
        if eng is not None:
            try:
                eng.quit()
            except Exception:
                pass
