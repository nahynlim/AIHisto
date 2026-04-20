# built-in libraries
import os
from tkinter import END
import subprocess

# external libraries
from PIL import Image
from scipy.ndimage import center_of_mass, label, generate_binary_structure
import numpy as np
import cv2
import pandas as pd
from skimage import measure


def createimstack(tag, setfolder):
    """Load an image stack for a given set folder.

    If `tag` is empty/None, load *all* supported images in the folder.
    Otherwise, load only images whose filename contains `tag` (case-insensitive),
    preserving the legacy behavior.
    """
    ext = ['.tiff', '.tif', '.jpeg', '.jpg', '.png', '.bmp', '.gif']
    imlist = [_ for _ in os.listdir(setfolder) if _.lower().endswith(tuple(ext))]
    if tag is not None and str(tag).strip() != "":
        imlist = [_ for _ in imlist if str(tag).lower() in _.lower()]
    imlist = sorted(imlist)
    imlistpath = [os.path.join(setfolder, _) for _ in imlist]
    imstack = [np.array(Image.open(im)) for im in imlistpath]
    return imstack, imlistpath, imlist


def check_label_status(im):
    """Heuristic: labeled images tend to have many unique integer values."""
    try:
        uniq = np.unique(im)
        # ignore background 0 if present
        uniq = uniq[uniq != 0]
        return 'labeled' if uniq.size > 1 else 'unlabeled'
    except Exception:
        return 'unlabeled'


def mask2boundary(mask):
    contours, hierarchy = cv2.findContours(np.ascontiguousarray(mask, dtype=np.uint8), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return np.empty((0, 2), dtype=int)
    c = max(contours, key=len)
    contour = c[:, 0, :]
    contour[:, 0] += 1
    contour[:, 1] += 1
    boundary = np.column_stack([contour[:, 1], contour[:, 0]]).astype(int)
    return boundary


def getboundary(csv, progress_bar, entries):
    print('## getboundary.py')
    ui = pd.read_csv(csv)
    setpaths = ui['set location']

    # iterate through image set
    for setfolderidx, setfolder in enumerate(setpaths):
        tag = ui['tag'][setfolderidx]
        safe_tag = tag if (tag is not None and str(tag).strip() != "") else "dataset"

        registry = []
        datasheet = 'VAMPIRE datasheet ' + safe_tag + '.csv'
        registry_dst = os.path.join(setfolder, datasheet)

        boundarymaster = []
        boundarydst = os.path.join(setfolder, safe_tag + '_boundary_coordinate_stack.pickle')

        if os.path.exists(registry_dst):
            print('registry or boundary already exist')
            continue

        imstack, imlistpath, imlist = createimstack(tag, setfolder)

        try:
            inputim = check_label_status(imstack[0])  # intensity label in greyscale
        except Exception:
            entries['Status'].delete(0, END)
            entries['Status'].insert(0, 'error: update your CSV file or check image paths')
            return

        if inputim != 'labeled':
            s = generate_binary_structure(2, 2)
            imstack = [label(im, structure=s)[0] for im in imstack]

        # iterate through labeled greyscale image
        for imidx, im in enumerate(imstack):
            labels = list(set(im.flatten()))[1:]
            labels = sorted(labels)

            # iterate through labeled object in image
            for objidx, lab in enumerate(labels):
                mask = np.array((im == lab).astype(int), dtype='uint8')
                boundary = mask2boundary(mask)
                if len(boundary) < 5:
                    continue

                centroid = [int(np.around(_, 0)) for _ in center_of_mass(mask)]
                centroid.reverse()  # swap to correct x,y

                prop = measure.regionprops(mask)[0]
                area = prop['area']
                perimeter = prop['perimeter']
                majoraxis = prop['major_axis_length']
                minoraxis = prop['minor_axis_length']
                circularity = 4 * np.pi * area / (perimeter ** 2) if perimeter else 0.0

                try:
                    ar = majoraxis / minoraxis
                except Exception:
                    ar = 0

                props = [area, perimeter, majoraxis, minoraxis, circularity, ar]
                fronttag = [imlist[imidx], imidx + 1, objidx + 1]
                registry_item = fronttag + centroid + props
                registry.append(registry_item)
                boundarymaster.append(boundary)

                # progress update (keep legacy scale but guard against division by zero)
                denom_labels = max(len(labels), 1)
                denom_stack = max(len(imstack), 1)
                denom_sets = max(len(setpaths), 1)

                progress = 100 * (objidx + 1) / denom_labels / denom_stack / denom_sets                            + 100 * (imidx + 1) / denom_stack / denom_sets                            + 100 * (setfolderidx + 1) / denom_sets

                if progress_bar is not None:
                    progress_bar["value"] = progress / 2
                    progress_bar.update()

        if len(boundarymaster) != len(registry):
            raise Exception('boundary coordinates length does not match registry length')

        if not os.path.exists(boundarydst):
            df = pd.DataFrame({0: pd.array(boundarymaster, dtype=object)})
            df.to_pickle(boundarydst)
            # Hide the file on Windows (safe no-op on other OSes)
            try:
                if os.name == 'nt':
                    subprocess.check_call(["attrib", "+H", boundarydst])
            except Exception:
                pass

        if not os.path.exists(registry_dst):
            df_registry = pd.DataFrame(registry)
            df_registry.columns = ['Filename', 'ImageID', 'ObjectID', 'X', 'Y', 'Area', 'Perimeter',
                                   'Major Axis', 'Minor Axis', 'Circularity', 'Aspect Ratio']
            df_registry.index = df_registry.index + 1
            df_registry.to_csv(registry_dst, index=False)

    entries['Status'].delete(0, END)
    entries['Status'].insert(0, 'object csv created...')
    return
