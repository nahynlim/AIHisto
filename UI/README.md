# AIHisto UI README

This repository contains a GUI-driven workflow for image segmentation, SHG masking, and VAMPIRE-based shape analysis. This README is a working protocol document that you can continue refining as the project evolves.

## Overview

The current workflow has up to four major stages:

1. Segment raw microscopy images with CellProfiler.
2. Create SHG-based masks with MATLAB.
3. Build a VAMPIRE shape model from segmented image sets.
4. Apply a saved VAMPIRE model to new segmented image sets.

The main GUI entry point is:

```cmd
python VAMPIREv3_pyqt6.py
```

## External Software Installation

This project depends on external software in addition to Python packages.

### 1. CellProfiler installation

CellProfiler is used for segmentation and for the masking pipeline that opens in CellProfiler.

#### Windows

1. Go to the official CellProfiler download page.
2. Download the Windows installer.
3. Run the installer and finish setup.
4. After installation, confirm that CellProfiler opens normally.
5. In the GUI, if auto-detection does not work, browse to the CellProfiler executable manually.

Typical Windows locations may include:

- `C:\ProgramData\Microsoft\Windows\Start Menu\Programs\CellProfiler.lnk`
- A desktop shortcut
- The installed application folder if a direct executable is available

#### macOS

1. Go to the official CellProfiler download page.
2. Download the macOS `.app` package.
3. Drag `CellProfiler.app` into the `Applications` folder.
4. Open it once manually so macOS security permissions can be accepted if needed.
5. In this GUI, the expected application path may be:

```bash
/Applications/CellProfiler.app
```

or the internal executable:

```bash
/Applications/CellProfiler.app/Contents/MacOS/cp
```

#### Notes

- If the GUI says CellProfiler cannot be found, use the browse button and select the application or executable manually.
- CellProfiler is used in two places in this repo:
  - segmentation of raw input images
  - launching the masking pipeline that combines staining images and masks

### 2. MATLAB installation

MATLAB is used for the SHG masking workflow.

#### Windows

1. Download MATLAB through your institutional or MathWorks license.
2. Run the installer and complete the standard setup.
3. Open MATLAB once to confirm it launches correctly.
4. Make sure the installation includes any toolboxes required by your masking scripts.

#### macOS

1. Download MATLAB through your institutional or MathWorks license.
2. Install the MATLAB application in `Applications`.
3. Open MATLAB once to allow permissions and complete activation.
4. Confirm you can run `.m` scripts normally.

#### Important note for both Windows and macOS

The GUI requires MATLAB itself and also MATLAB Engine for Python in the same Python environment used to launch `VAMPIREv3_pyqt6.py`.

Python-version compatibility matters:

- `MATLAB R2023a` is the last release that supports Python `3.8.x`
- `MATLAB R2023b` and newer should use a Python `3.9.x` environment

If this step is missing, the GUI masking workflow will fail with a MATLAB Engine import error.

After activating the correct Python environment, first try:

```cmd
python -m pip install matlab.engine
```

If needed, install from the MATLAB engine folder.

#### Windows Command Prompt

```cmd
cd "C:\Program Files\MATLAB\R20XXx\extern\engines\python"
python -m pip install .
```

#### macOS Terminal

```bash
cd /Applications/MATLAB_R20XXx.app/extern/engines/python
python3 -m pip install .
```

## Required Python Version

Users should install a specific Python version before creating the project environment.

### Recommended version

Choose the Python version based on your MATLAB version:

- If you are using `MATLAB R2023a`, the last supported Python series is `Python 3.8.x`
- If you are using `MATLAB R2023b` or newer, use a `Python 3.9.x` environment

For this project, the default recommendation is:

- `Python 3.9.x`

### Install Python before creating the environment

#### Windows Command Prompt

1. Open your browser and go to the official Python downloads page: `https://www.python.org/downloads/`
2. Download the Windows installer for the Python version you need:
   - `Python 3.8.x` if using `MATLAB R2023a`
   - `Python 3.9.x` if using `MATLAB R2023b` or newer
3. Run the installer.
4. Make sure to check `Add Python to PATH` during installation.
5. Finish installation.
6. Open `Command Prompt`.
7. Confirm installation:

If you are using `MATLAB R2023a`:

```cmd
py -3.8 --version
```

If you are using `MATLAB R2023b` or newer:

```cmd
py -3.9 --version
```

#### macOS Terminal

1. Open your browser and go to the official Python downloads page: `https://www.python.org/downloads/`
2. Download the macOS installer for the Python version you need:
   - `Python 3.8.x` if using `MATLAB R2023a`
   - `Python 3.9.x` if using `MATLAB R2023b` or newer
3. Run the installer and complete setup.
4. Open `Terminal`.
5. Confirm installation:

If you are using `MATLAB R2023a`:

```bash
python3.8 --version
```

If you are using `MATLAB R2023b` or newer:

```bash
python3.9 --version
```

If the command for your chosen version is not found, install that Python version first before continuing.

## Python Environment Setup

The project should be run from a dedicated Python environment.

### Setup protocol

Follow this order:

1. Download and install the correct Python version from `python.org`.
2. Open the correct terminal for your operating system.
3. Go to the `UI/` project folder.
4. Create the virtual environment manually.
5. Activate the virtual environment.
6. Install the Python packages.
7. Install `matlab.engine`.
8. Launch `VAMPIREv3_pyqt6.py`.

### Windows setup using Command Prompt

#### Step 1. Open Command Prompt

Use `Command Prompt`, not PowerShell.

#### Step 2. Go to the project folder

```cmd
cd C:\path\to\AIHisto\UI
```

#### Step 3. Create the environment manually

If you are using `MATLAB R2023a`:

```cmd
py -3.8 -m venv .venv
```

If you are using `MATLAB R2023b` or newer:

```cmd
py -3.9 -m venv .venv
```

#### Step 4. Activate the environment

```cmd
.venv\Scripts\activate
```

#### Step 5. Confirm the Python version

```cmd
python --version
```

#### Step 6. Install the Python packages

```cmd
python -m pip install numpy pandas pillow scipy opencv-python scikit-image joblib scikit-learn matplotlib
```

#### Step 7. Install MATLAB Engine for Python

```cmd
python -m pip install matlabengine
```

If `matlabengine` does not install directly, install it from the MATLAB `extern/engines/python` folder:

Option 1. Open `Command Prompt` as Administrator and run:

```cmd
cd "C:\Program Files\MATLAB\R20XXx\extern\engines\python"
python -m pip install .
```

Option 2. If you do not want to install from `Program Files`, copy the MATLAB engine folder to a writable location and install from there.

#### Step 8. Launch the GUI

```cmd
cd C:\path\to\AIHisto\UI
python VAMPIREv3_pyqt6.py
```

### macOS setup using Terminal

#### Step 1. Open Terminal

Use `Terminal`.

#### Step 2. Go to the project folder

```bash
cd /path/to/AIHisto/UI
```

#### Step 3. Create the environment manually

If you are using `MATLAB R2023a`:

```bash
python3.8 -m venv .venv
```

If you are using `MATLAB R2023b` or newer:

```bash
python3.9 -m venv .venv
```

#### Step 4. Activate the environment

```bash
source .venv/bin/activate
```

#### Step 5. Confirm the Python version

```bash
python3 --version
```

#### Step 6. Install the Python packages

```bash
python3 -m pip install numpy pandas pillow scipy opencv-python scikit-image joblib scikit-learn matplotlib
```

#### Step 7. Install MATLAB Engine for Python

```bash
python3 -m pip install matlabengine
```

If `matlab.engine` does not install directly, install it from the MATLAB `extern/engines/python` folder:

```bash
cd /Applications/MATLAB_R20XXx.app/extern/engines/python
python3 -m pip install .
```

#### Step 8. Launch the GUI

```bash
cd /path/to/AIHisto/UI
python3 VAMPIREv3_pyqt6.py
```

### If you created the environment with the wrong Python version

Delete the old environment folder and recreate it with the correct Python version for your MATLAB release.

#### Windows Command Prompt

If you are using `MATLAB R2023a`:

```cmd
rmdir /s /q .venv
py -3.8 -m venv .venv
.venv\Scripts\activate
```

If you are using `MATLAB R2023b` or newer:

```cmd
rmdir /s /q .venv
py -3.9 -m venv .venv
.venv\Scripts\activate
```

#### macOS Terminal

If you are using `MATLAB R2023a`:

```bash
rm -rf .venv
python3.8 -m venv .venv
source .venv/bin/activate
```

If you are using `MATLAB R2023b` or newer:

```bash
rm -rf .venv
python3.9 -m venv .venv
source .venv/bin/activate
```

## Running the GUI

After activating the environment and installing dependencies:

```cmd
python VAMPIREv3_pyqt6.py
```

On macOS Terminal:

```bash
python3 VAMPIREv3_pyqt6.py
```

## How to Launch the GUI

The current recommended way to open the software is to run the Python GUI file directly.

### Windows Command Prompt

```cmd
cd C:\path\to\AIHisto\UI
.venv\Scripts\activate
python VAMPIREv3_pyqt6.py
```

### macOS Terminal

```bash
cd /path/to/AIHisto/UI
source .venv/bin/activate
python3 VAMPIREv3_pyqt6.py
```

### Can this become an executable?

Yes, in the future this project could be packaged as:

- a Windows `.exe`
- a macOS `.app`

However, the current project still depends on external software such as CellProfiler and MATLAB, so the most reliable method right now is to launch `VAMPIREv3_pyqt6.py` from an activated Python environment.

## Repository File Organization

This section explains where the main code and pipeline assets live.

## Repository Directory Paths

The project root is the `UI/` folder. A typical layout now looks like:

```text
UI/
├─ VAMPIREv3_pyqt6.py
├─ vampire/
│  ├─ __init__.py
│  ├─ mainbody.py
│  ├─ getboundary.py
│  ├─ clusterSM.py
│  └─ ...
├─ pipelines/
│  ├─ Blue_Nuclei_Segmentation_Pipeline.cppipe
│  ├─ Blue_Nuclei_Segmentation_Pipeline.cpproj
│  ├─ Nuclei_Segmentation_Pipeline.cppipe
│  ├─ Nuclei_Segmentation_Pipeline.cpproj
│  └─ Masking_pipeline.cpproj
├─ matlab/
├─ results/
├─ Supplementary Data/
└─ README.md
```

### Important paths users may need

- GUI launcher:
  - `UI/VAMPIREv3_pyqt6.py`
- Core VAMPIRE analysis code:
  - `UI/vampire/`
- CellProfiler pipelines:
  - `UI/pipelines/`
- MATLAB scripts:
  - `UI/matlab/`
- Example inputs and outputs:
  - `UI/Supplementary Data/`
- Generated run outputs:
  - `UI/results/`

### Full path example

On Windows, a full path may look like:

```text
C:\path\to\AIHisto\UI\VAMPIREv3_pyqt6.py
```

On macOS, a full path may look like:

```text
/path/to/AIHisto/UI/VAMPIREv3_pyqt6.py
```

### Main Python files

- `VAMPIREv3_pyqt6.py`
  - Main GUI used for segmentation, masking, model building, and model application.
- `vampire.py`
  - Older legacy GUI.
- `generate_vampire_input_csv.py`
  - Utility for creating dataset CSV files used by build/apply workflows.
- `matlab_mask_runner.py`
  - Python bridge that launches the MATLAB masking function.

### Core analysis modules

- `vampire/mainbody.py`
- `vampire/getboundary.py`
- `vampire/clusterSM.py`
- `vampire/bdreg.py`
- `vampire/bd_resample.py`
- `vampire/pca_bdreg.py`
- `vampire/PCA_custom.py`
- `vampire/reg_bd3.py`
- `vampire/reg_bd_svd.py`
- `vampire/update_csv.py`
- `vampire/collect_selected_bstack.py`

These files support boundary registration, PCA, clustering, and CSV/result updates for the VAMPIRE workflow.

### CellProfiler pipeline files

- `pipelines/Blue_Nuclei_Segmentation_Pipeline.cppipe`
- `pipelines/Blue_Nuclei_Segmentation_Pipeline.cpproj`
- `pipelines/Nuclei_Segmentation_Pipeline.cppipe`
- `pipelines/Nuclei_Segmentation_Pipeline.cpproj`
- `pipelines/Masking_pipeline.cpproj`
- `Supplementary Data/CellProfiler segmentation pipeline.cppipe`

### MATLAB scripts

All MATLAB-related code is stored in:

- `matlab/`

Important scripts include:

- `matlab/run_FFT_align_msk_v3_autoROI_from_python.m`
- `matlab/FFT_align_msk_update_03_24_2026.m`
- `matlab/FFT_align_msk_SHG_controlRef_singleOrBatch.m`

### Example and supplementary data

- `Supplementary Data/Example images/`
- `Supplementary Data/Example segmented images/`
- `Supplementary Data/Example output/`

### Output folders

- `results/`
- `results/model_output/`

## Expected Data Organization

The current build/apply pipeline expects a dataset CSV that points to folders of segmented images.

### Dataset CSV columns

The current tooling uses columns like:

- `condition`
- `set location`
- `tag`
- `note`
- `setID` or `set ID`

### What these mean

- `condition`
  - Label for the biological or experimental condition.
- `set location`
  - Folder path containing the segmented images for that condition.
- `tag`
  - Filename substring used to match the correct images in that folder.
- `note`
  - Optional free-text note.
- `setID` or `set ID`
  - Numeric set identifier.

### Example

```csv
set ID,condition,set location,tag,note
1,MEF_wildtype,C:\path\to\segmented\MEF_wildtype,c1,example apply set
2,MEF_LMNA--,C:\path\to\segmented\MEF_LMNA--,c1,example apply set
```

## Usability Protocol

This section is the recommended user flow through the GUI.

## Recommended Order of Operations

Use the workflow in this order:

1. Prepare or collect your raw images.
2. Segment the images with CellProfiler.
3. If needed, create SHG masks with MATLAB.
4. If needed, use the CellProfiler masking pipeline to apply masks to staining images.
5. Build a VAMPIRE model from segmented images.
6. Apply the saved VAMPIRE model to new segmented image sets.

Not every project needs every step. Some users may already have segmented images and can start at model building.

## Step-by-Step GUI Instructions

### A. Segmentation section

Use this section when starting from raw microscopy images.

1. Open the GUI with `python VAMPIREv3_pyqt6.py`.
2. In the `SEGMENTATION` panel, choose one or more raw image files.
3. Select the segmentation pipeline you want to use.
4. Confirm the CellProfiler executable path.
5. Choose a segmented output folder.
6. Choose whether to run headless or open CellProfiler interactively.
7. Click `Start Segmentation`.

What to expect:

- Headless mode attempts to run the pipeline automatically.
- Interactive mode opens CellProfiler so the user can inspect or modify pipeline settings.
- Output images and spreadsheets are written to the selected segmentation output folder.

### B. Masking section

Use this section when you need SHG-derived masks.

1. In the `MASKING` panel, select the SHG image files or folder.
2. Choose the output folder for masks.
3. Set the masking parameters:
   - bundle width
   - bundle height
   - low SHG percentile
   - ROI mode
   - rotation mode
   - mask output type
4. Select whether to save masks, figures, stats text, and ROI files.
5. Click `Create Masks`.

Important current input rule:

- The MATLAB runner currently looks for SHG image filenames ending with `_0000.tif` or `_0000.tiff`.

If your files do not follow that naming convention, the masking step may not detect them.

### C. Masking pipeline in CellProfiler

Use this when you want to apply masks to staining images through CellProfiler.

1. In the `APPLY MODEL` panel, first use `Open Masking Pipeline`.
2. Confirm the CellProfiler executable.
3. Launch the masking pipeline.
4. Inside CellProfiler, manually choose:
   - the staining-image input folder
   - the mask folder
   - the output folder
5. Run the CellProfiler masking pipeline.

This is a separate stage from the VAMPIRE model application itself.

### D. Build Model section

Use this section to create a new VAMPIRE model from segmented images.

1. Prepare a dataset CSV listing the segmented image folders.
2. In `BUILD MODEL`, upload the build-model CSV.
3. Set the number of coordinates.
4. Set the number of shape modes.
5. Choose the model output folder.
6. Enter a model name.
7. Click `Build Model`.

What happens internally:

- The code extracts object boundaries from segmented images.
- It generates a datasheet CSV and boundary pickle inside each image-set folder.
- It builds the model and saves a `.pickle` file.
- It also saves model figures such as registered object plots and shape mode dendrograms.

### E. Apply Model section

Use this section to apply a previously built model to a new dataset.

1. Prepare a dataset CSV for the segmented image folders you want to analyze.
2. In `APPLY MODEL`, either upload a model `.pkl` or `.pickle`, or use the model built in the current GUI session.
3. Upload the apply-model CSV, or choose a folder if using folder mode.
4. Select the result output folder.
5. Click `Apply Model`.

What happens internally:

- The code extracts boundaries if needed.
- It loads the saved model.
- It assigns objects to shape modes.
- It writes result plots to the output folder.

## Where Users Should Browse for Files

Users will usually need to browse for files in these places:

- raw image folders for segmentation
- SHG image folders for mask creation
- mask output folders produced by MATLAB
- segmented image folders for model build/apply
- dataset CSV files created for VAMPIRE input
- saved model `.pickle` files
- output folders for results and figures

## Warnings and Practical Notes

### Image type and segmentation assumptions

- The build/apply pipeline expects segmented images, not raw grayscale microscopy images.
- If the images are not already labeled, the code attempts connected-component labeling, but quality still depends heavily on clean segmentation.
- Mixed image types inside the same folder may lead to inconsistent results.

### Filename/tag matching

- The `tag` column in the dataset CSV matters.
- The code filters images in a folder using that tag substring.
- If the tag does not match the filenames, the build/apply workflow may appear empty or incomplete.

### Masking input naming

- MATLAB masking currently expects SHG inputs ending in `_0000.tif`.
- If your microscope export format differs, rename files or update the MATLAB runner logic.

### Folder consistency

- When selecting multiple image files for CellProfiler, they should come from the same folder.
- For build/apply workflows, each dataset row should point to the correct segmented image folder for one condition.

### Existing generated files

During model building and application, the code may create files directly inside the image-set folders, including:

- `VAMPIRE datasheet <tag>.csv`
- `<tag>_boundary_coordinate_stack.pickle`

Users should know these are intermediate workflow files and not necessarily original source data.

### GUI/tool compatibility

- CellProfiler must be installed separately.
- MATLAB must be installed separately.
- MATLAB Engine for Python must be installed in the same Python environment as this GUI.
- Some paths may need to be selected manually if auto-detection fails.

## Suggested Future Cleanup

This README is a working draft. Good next improvements would be:

1. Add screenshots of each GUI section.
2. Add one full worked example from raw image to final plot.
3. Add a short troubleshooting section for common errors.
4. Add a formal `requirements.txt`.

## Quick Start Summary

If you already have all software installed:

1. Activate the Python environment.
2. Launch `VAMPIREv3_pyqt6.py`.
3. Segment images if needed.
4. Create SHG masks if needed.
5. Build a model from segmented-image dataset CSVs.
6. Apply the saved model to new segmented-image dataset CSVs.
