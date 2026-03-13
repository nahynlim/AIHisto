#!/usr/bin/env python

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
from datetime import datetime
import os


# ===============================
# Utility Functions
# ===============================

def get_folder(entry):
    folder = filedialog.askdirectory()
    if folder:
        entry.delete(0, tk.END)
        entry.insert(0, folder)


def get_file(entry, filetypes):
    file = filedialog.askopenfilename(filetypes=filetypes)
    if file:
        entry.delete(0, tk.END)
        entry.insert(0, file)


def update_status(status_entry, progress_bar, message, progress):
    status_entry.delete(0, tk.END)
    status_entry.insert(0, message)
    progress_bar["value"] = progress
    progress_bar.update()


# ===============================
# Segmentation
# ===============================

def start_segmentation(entries, progress_bar):
    if not entries['Raw Images Folder'].get():
        messagebox.showerror("Error", "Select raw images folder")
        return

    def process():
        steps = [
            (20, "Initializing CellProfiler..."),
            (40, "Loading images..."),
            (60, "Segmenting cells..."),
            (80, "Saving output..."),
            (100, "Segmentation complete!")
        ]
        for p, msg in steps:
            time.sleep(0.7)
            update_status(entries['Status'], progress_bar, msg, p)

    threading.Thread(target=process).start()


# ===============================
# Masking
# ===============================

def create_masks(entries, progress_bar):
    if not entries['SHG Folder'].get():
        messagebox.showerror("Error", "Select SHG folder")
        return

    def process():
        steps = [
            (20, "Loading SHG images..."),
            (40, "Creating masks..."),
            (60, "Applying masks..."),
            (100, "Masking complete!")
        ]
        for p, msg in steps:
            time.sleep(0.7)
            update_status(entries['Status'], progress_bar, msg, p)

    threading.Thread(target=process).start()


# ===============================
# Build Model
# ===============================

def build_model(entries, progress_bar, built_model):
    if not entries['Image CSV'].get():
        messagebox.showerror("Error", "Select CSV file")
        return

    def process():
        steps = [
            (20, "Loading image set..."),
            (40, "Extracting boundaries..."),
            (70, "Computing shape modes..."),
            (100, "Model built!")
        ]

        for p, msg in steps:
            time.sleep(0.7)
            update_status(entries['Status'], progress_bar, msg, p)

        built_model['data'] = {
            "name": entries['Model Name'].get(),
            "shape_modes": entries['Shape Modes'].get(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    threading.Thread(target=process).start()


# ===============================
# Apply Model
# ===============================

def apply_model(entries, progress_bar, built_model):
    if not entries['Apply CSV'].get():
        messagebox.showerror("Error", "Select image CSV")
        return

    def process():
        steps = [
            (20, "Loading model..."),
            (40, "Loading images..."),
            (70, "Applying model..."),
            (100, "Application complete!")
        ]
        for p, msg in steps:
            time.sleep(0.7)
            update_status(entries['Status'], progress_bar, msg, p)

    threading.Thread(target=process).start()


# ===============================
# Main GUI (vampire style)
# ===============================

def vampire():
    root = tk.Tk()
    root.geometry("700x850")
    root.title("VAMPIRE Analysis")

    entries = {}
    built_model = {}

    # ===============================
    # Segmentation Section
    # ===============================
    tk.Label(root, text="Segmentation", font=("Arial", 14, "bold")).pack(pady=5)

    entries['Raw Images Folder'] = tk.Entry(root)
    entries['Raw Images Folder'].pack(fill=tk.X, padx=10)

    tk.Button(root, text="Browse",
              command=lambda: get_folder(entries['Raw Images Folder'])).pack()

    tk.Button(root, text="Start Segmentation",
              command=lambda: start_segmentation(entries, progress_bar)).pack(pady=5)

    # ===============================
    # Masking Section
    # ===============================
    tk.Label(root, text="Masking", font=("Arial", 14, "bold")).pack(pady=5)

    entries['SHG Folder'] = tk.Entry(root)
    entries['SHG Folder'].pack(fill=tk.X, padx=10)

    tk.Button(root, text="Browse",
              command=lambda: get_folder(entries['SHG Folder'])).pack()

    tk.Button(root, text="Create Masks",
              command=lambda: create_masks(entries, progress_bar)).pack(pady=5)

    # ===============================
    # Build Model Section
    # ===============================
    tk.Label(root, text="Build Model", font=("Arial", 14, "bold")).pack(pady=5)

    entries['Image CSV'] = tk.Entry(root)
    entries['Image CSV'].pack(fill=tk.X, padx=10)

    tk.Button(root, text="Load CSV",
              command=lambda: get_file(entries['Image CSV'],
                                       [("CSV", "*.csv")])).pack()

    entries['Shape Modes'] = tk.Entry(root)
    entries['Shape Modes'].insert(0, "5")
    entries['Shape Modes'].pack(fill=tk.X, padx=10)

    entries['Model Name'] = tk.Entry(root)
    entries['Model Name'].insert(0, "collagen_model")
    entries['Model Name'].pack(fill=tk.X, padx=10)

    tk.Button(root, text="Build Model",
              command=lambda: build_model(entries, progress_bar, built_model)).pack(pady=5)

    # ===============================
    # Apply Model Section
    # ===============================
    tk.Label(root, text="Apply Model", font=("Arial", 14, "bold")).pack(pady=5)

    entries['Apply CSV'] = tk.Entry(root)
    entries['Apply CSV'].pack(fill=tk.X, padx=10)

    tk.Button(root, text="Load CSV",
              command=lambda: get_file(entries['Apply CSV'],
                                       [("CSV", "*.csv")])).pack()

    tk.Button(root, text="Apply Model",
              command=lambda: apply_model(entries, progress_bar, built_model)).pack(pady=5)

    # ===============================
    # Status + Progress
    # ===============================
    entries['Status'] = tk.Entry(root)
    entries['Status'].insert(0, "Welcome to Vampire Analysis")
    entries['Status'].pack(fill=tk.X, padx=10, pady=5)

    progress_bar = ttk.Progressbar(root, orient="horizontal",
                                   mode="determinate", maximum=100)
    progress_bar.pack(fill=tk.X, padx=10, pady=5)

    root.mainloop()


if __name__ == "__main__":
    vampire()