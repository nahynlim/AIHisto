# About:
AIHisto is a GUI-based pipeline for microscopy image analysis that integrates:

- **CellProfiler** for image segmentation  
- **MATLAB** for SHG-based masking  
- **VAMPIRE** for cell shape modeling and analysis  

The software allows users to segment images, generate SHG masks, build shape models, and apply trained models to new datasets.



# Features:
- GUI-driven workflow (`VAMPIREv2.py`)
- Automated CellProfiler segmentation
- SHG-based collagen masking using MATLAB
- VAMPIRE shape modeling
- Model application to new datasets
- Support for batch datasets via CSV configuration

# Repository Structure:

```
UI/
├── VAMPIREv2.py              # Main GUI launcher
├── vampire/                  # Core VAMPIRE analysis modules
├── pipelines/                # CellProfiler pipelines
├── matlab/                   # SHG masking MATLAB scripts
├── results/                  # Generated outputs
└── Supplementary Data/       # Example data
```

---

# Requirements:

## Python

Recommended Python version:

```
Python >= 3.9
```

Install dependencies using the provided `requirements.txt` file:

```bash
pip install -r requirements.txt
```

Install MATLAB Engine:

```bash
pip install matlabengine
```

## External Software

### CellProfiler

Used for image segmentation.

Download:

https://cellprofiler.org/releases

Typical macOS location:

```
/Applications/CellProfiler.app
```

### MATLAB

Required for SHG masking scripts.

MATLAB scripts are located in:

```
UI/matlab/
```

### MATLAB Engine for Python

Install inside the same Python environment used to run the GUI.

macOS:

```bash
cd /Applications/MATLAB_R20XXx.app/extern/engines/python
python3 -m pip install .
```

Windows:

```bash
cd "C:\Program Files\MATLAB\R20XXx\extern\engines\python"
python -m pip install .
```

# Installation:

Clone the repository:

```bash
git clone https://github.com/<your-org>/AIHisto.git
cd AIHisto/UI
```

Create a Python environment:

macOS / Linux

```bash
python3.9 -m venv .venv
source .venv/bin/activate
```

Windows

```bash
py -3.9 -m venv .venv
.venv\Scripts\activate
```

# Running the GUI:

After activating the environment:

macOS / Linux

```bash
python3 VAMPIREv2.py
```

Windows

```bash
python VAMPIREv2.py
```

# Workflow:

Typical workflow:

1. Segment raw microscopy images using **CellProfiler**
2. Generate **SHG masks** using MATLAB
3. Build a **VAMPIRE shape model**
4. Apply the saved model to new segmented datasets

Some projects may start directly from step 3 if segmented images already exist.


# Dataset CSV Format:
Model building and application require a CSV file describing segmented image folders.

Example:

```
set ID,condition,set location,tag,note
1,MEF_wildtype,C:\data\segmented\MEF_wildtype,c1,example
2,MEF_LMNA--,C:\data\segmented\MEF_LMNA--,c1,example
```

Column descriptions:

| Column | Description |
|------|------|
| condition | experimental condition |
| set location | folder containing segmented images |
| tag | filename substring used to select images |
| note | optional description |
| set ID | dataset identifier |


# Outputs:
Results are saved to:

```
UI/results/
```

Outputs may include:

- VAMPIRE model `.pickle` files
- shape mode assignments
- plots and figures
- dataset CSV summaries


# Notes:
- Model building requires **segmented images**, not raw microscopy images.
- SHG masking expects SHG images ending with `_0000.tif`.
- Intermediate files may be generated in dataset folders during analysis.
