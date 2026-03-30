function results = run_FFT_align_msk_v3_autoROI_from_python( ...
    filename, pth2, doEnhance, bundleW, bundleH, varargin)
% run_FFT_align_msk_v3_autoROI_from_python
%
% Hybrid MATLAB wrapper:
% - Python-callable with explicit inputs
% - Interactive GUI-style prompts if inputs are omitted
%
% Main added features:
%   1) Prompt user to pick SHG image/folder if filename not given
%   2) Interactive selection of SHG images ending in _0000.tif
%   3) Prompt user for sharpen/enhance
%   4) Prompt user for bundle width/height
%   5) Prompt user for low-SHG percentile
%   6) Prompt user for rotation mode / user angle
%   7) Prompt user whether to autodetect ROI or not
%
% ROI modes:
%   'auto'  -> auto-detect ROI from first selected image
%   'draw'  -> draw polygon ROI on first selected image
%   'none'  -> analyze whole image
%
% Example Python-style call:
%   results = run_FFT_align_msk_v3_autoROI_from_python( ...
%       filenames, outdir, true, 15, 15, ...
%       'interactive', false, ...
%       'mask_mode', 'auto');
%
% Example interactive call:
%   results = run_FFT_align_msk_v3_autoROI_from_python();

tStart = tic;

% --------------------------
% Optional parallel pool
% --------------------------
p = gcp('nocreate');
if isempty(p)
    try
        parpool;
    catch
    end
end

% --------------------------
% Parse optional arguments
% --------------------------
ip = inputParser;
ip.CaseSensitive = false;

addParameter(ip, 'interactive', [], @(x)islogical(x) || isnumeric(x) || isempty(x));
addParameter(ip, 'mask_mode', '', @(x)ischar(x) || isstring(x));
addParameter(ip, 'maskVerts', [], @(x)isnumeric(x) || isempty(x));

addParameter(ip, 'low_shg_percentile', [], @(x)isnumeric(x) && (isempty(x) || isscalar(x)));
addParameter(ip, 'rot_mode', '', @(x)ischar(x) || isstring(x));
addParameter(ip, 'user_angle', 0, @(x)isnumeric(x) && isscalar(x));
addParameter(ip, 'mask_types', 'all', @(x)iscell(x) || ischar(x) || isstring(x));

addParameter(ip, 'save_masks', true, @(x)islogical(x) || isnumeric(x));
addParameter(ip, 'save_stats', true, @(x)islogical(x) || isnumeric(x));
addParameter(ip, 'save_roi', true, @(x)islogical(x) || isnumeric(x));
addParameter(ip, 'save_figures', true, @(x)islogical(x) || isnumeric(x));
addParameter(ip, 'save_unknown_mask', false, @(x)islogical(x) || isnumeric(x));
addParameter(ip, 'overwrite', true, @(x)islogical(x) || isnumeric(x));

addParameter(ip, 'control_files', {}, @(x)iscell(x) || isstring(x) || ischar(x));

addParameter(ip, 'dam_thresh_deg', 15, @(x)isnumeric(x) && isscalar(x));
addParameter(ip, 'ecc_min', 0.80, @(x)isnumeric(x) && isscalar(x));
addParameter(ip, 'do_spatial_cleanup', true, @(x)islogical(x) || isnumeric(x));
addParameter(ip, 'min_dam_obj_pixels', 3*15, @(x)isnumeric(x) && isscalar(x));
addParameter(ip, 'tile_frac_thresh', 0.75, @(x)isnumeric(x) && isscalar(x));

parse(ip, varargin{:});
OPT = ip.Results;

OPT.save_masks         = logical(OPT.save_masks);
OPT.save_stats         = logical(OPT.save_stats);
OPT.save_roi           = logical(OPT.save_roi);
OPT.save_figures       = logical(OPT.save_figures);
OPT.save_unknown_mask  = logical(OPT.save_unknown_mask);
OPT.overwrite          = logical(OPT.overwrite);
OPT.do_spatial_cleanup = logical(OPT.do_spatial_cleanup);

if ischar(OPT.control_files)
    OPT.control_files = {OPT.control_files};
elseif isstring(OPT.control_files)
    OPT.control_files = cellstr(OPT.control_files);
end

if ischar(OPT.mask_types)
    OPT.mask_types = {char(OPT.mask_types)};
elseif isstring(OPT.mask_types)
    OPT.mask_types = cellstr(OPT.mask_types);
end
OPT.mask_types = lower(string(OPT.mask_types));

% --------------------------
% Decide interactive mode
% --------------------------
if nargin < 1 || isempty(filename)
    filename = [];
end
if nargin < 2 || isempty(pth2)
    pth2 = '';
end
if nargin < 3 || isempty(doEnhance)
    doEnhance = [];
end
if nargin < 4 || isempty(bundleW)
    bundleW = [];
end
if nargin < 5 || isempty(bundleH)
    bundleH = [];
end

if isempty(OPT.interactive)
    interactive = isempty(filename) || isempty(pth2) || isempty(doEnhance) || isempty(bundleW) || isempty(bundleH);
else
    interactive = logical(OPT.interactive);
end

% --------------------------
% Interactive file selection
% --------------------------
if interactive
    persistent inipth
    if isempty(inipth) || isequal(inipth,0)
        inipth = pwd;
    end

    [fnm, pth] = uigetfile('*.tif', 'Select SHG image to analyze', inipth);
    inipth = pth;

    if isequal(fnm,0)
        error('No image selected.');
    end

    % find all SHG images ending in _0000.tif
    Sdir = dir(fullfile(pth, '*.tif'));
    allNames = {Sdir.name};
    isSHG = endsWith(lower(allNames), '_0000.tif');
    Sdir = Sdir(isSHG);
    fnames = {Sdir.name};

    if isempty(fnames)
        error('No SHG images ending in _0000.tif were found in this folder.');
    end

    sr_v = listdlg( ...
        'PromptString', 'Choose SHG channel images', ...
        'SelectionMode', 'Multiple', ...
        'Name', '.tif SHG collagen images', ...
        'InitialValue', 1:min(2,length(fnames)), ...
        'ListString', fnames, ...
        'ListSize', [300 400]);

    if isempty(sr_v)
        error('No SHG images selected.');
    end

    filename = cell(numel(sr_v),1);
    for i = 1:numel(sr_v)
        filename{i} = fullfile(pth, fnames{sr_v(i)});
    end

    if isempty(pth2)
        nameInt = erase(fnames{sr_v(1)}, '.tif');
        [fnm2, pth2_gui] = uiputfile([nameInt '_SHGstats.txt'], ...
            'Choose Collagen Fiber Organization Output File');
        if isequal(fnm2,0)
            error('Output path selection cancelled.');
        end
        pth2 = pth2_gui;
    end

    enhanceChoice = questdlg('Sharpen and enhance all images?', ...
        'Image Enhancement', 'Yes', 'No', 'Yes');
    if isempty(enhanceChoice)
        error('Enhancement selection cancelled.');
    end
    doEnhance = strcmpi(enhanceChoice, 'Yes');

    answer1 = inputdlg( ...
        {'Enter Bundle Width (pixels):', 'Enter Bundle height (pixels):'}, ...
        'Input Window Size Parameters', 1, {'15', '15'});
    if isempty(answer1)
        error('Window size entry cancelled.');
    end
    bundleW = str2double(answer1{1});
    bundleH = str2double(answer1{2});
    if ~isfinite(bundleW) || ~isfinite(bundleH) || bundleW <= 0 || bundleH <= 0
        error('Bundle width and height must be positive numbers.');
    end

    lowShgAnswer = inputdlg( ...
        {'Enter normalized low-SHG percentile (i.e. 10 or 15):'}, ...
        'Low SHG Threshold', 1, {'10'});
    if isempty(lowShgAnswer)
        error('Low SHG threshold entry cancelled.');
    end
    OPT.low_shg_percentile = str2double(lowShgAnswer{1});
    if ~isfinite(OPT.low_shg_percentile) || OPT.low_shg_percentile < 0 || OPT.low_shg_percentile > 100
        error('Low SHG percentile must be between 0 and 100.');
    end

    rotOptions = { ...
        'None (keep image as is)', ...
        'Make Vertical (rotate +90)', ...
        'Make Horizontal (rotate -90)', ...
        'User angle (enter degrees)'};

    rotIdx = listdlg( ...
        'PromptString', 'Choose image orientation for analysis', ...
        'SelectionMode', 'Single', ...
        'Name', 'Image Orientation', ...
        'ListString', rotOptions, ...
        'InitialValue', 1, ...
        'ListSize', [320 180]);

    if isempty(rotIdx)
        error('Rotation selection cancelled.');
    end

    switch rotIdx
        case 1
            OPT.rot_mode = 'none';
        case 2
            OPT.rot_mode = 'vertical';
        case 3
            OPT.rot_mode = 'horizontal';
        case 4
            OPT.rot_mode = 'user';
        otherwise
            OPT.rot_mode = 'none';
    end

    if strcmpi(OPT.rot_mode, 'user')
        angAns = inputdlg( ...
            {'Enter rotation angle in degrees (positive = CCW, negative = CW):'}, ...
            'User Rotation Angle', 1, {'45'});
        if isempty(angAns)
            error('Rotation angle entry cancelled.');
        end
        OPT.user_angle = str2double(angAns{1});
        if ~isfinite(OPT.user_angle)
            error('Rotation angle must be a number.');
        end
    end

    % ROI question
    roiQuestion = questdlg( ...
        'Would you like to autodetect the ROI?', ...
        'ROI Selection', ...
        'Yes - autodetect', 'No - choose manually', 'No mask', ...
        'Yes - autodetect');

    if isempty(roiQuestion)
        error('ROI selection cancelled.');
    end

    switch roiQuestion
        case 'Yes - autodetect'
            OPT.mask_mode = 'auto';
        case 'No - choose manually'
            drawOrNone = questdlg( ...
                'Would you like to draw an ROI, or use the whole image?', ...
                'Manual ROI Option', ...
                'Draw ROI', 'No mask', 'Draw ROI');
            if isempty(drawOrNone)
                error('ROI mode selection cancelled.');
            end
            if strcmpi(drawOrNone, 'Draw ROI')
                OPT.mask_mode = 'draw';
            else
                OPT.mask_mode = 'none';
            end
        case 'No mask'
            OPT.mask_mode = 'none';
        otherwise
            OPT.mask_mode = 'auto';
    end
else
    if isstring(filename), filename = cellstr(filename); end
    if ischar(filename), filename = {filename}; end

    if isempty(filename) || ~iscell(filename)
        error('filename must be a non-empty cell array or string/char path.');
    end

    if isempty(pth2)
        error('pth2 must be provided when interactive=false.');
    end

    if isempty(doEnhance)
        doEnhance = true;
    end
    if isempty(bundleW), bundleW = 15; end
    if isempty(bundleH), bundleH = 15; end

    if isempty(OPT.low_shg_percentile)
        OPT.low_shg_percentile = 10;
    end
    if isempty(OPT.rot_mode)
        OPT.rot_mode = 'none';
    end
    if isempty(OPT.mask_mode)
        OPT.mask_mode = 'auto';
    end
end

if isstring(pth2), pth2 = char(pth2); end
if ~exist(pth2, 'dir')
    mkdir(pth2);
end

windowSize = [bundleW, bundleH];

DamThreshDeg     = OPT.dam_thresh_deg;
EccMin           = OPT.ecc_min;
DoSpatialCleanup = OPT.do_spatial_cleanup;
MinDamObjPixels  = OPT.min_dam_obj_pixels;
tileFracThresh   = OPT.tile_frac_thresh;
SaveUnknownMask  = OPT.save_unknown_mask;

% --------------------------
% Rotation mapping
% --------------------------
switch lower(string(OPT.rot_mode))
    case "none"
        rotChoice = 'None';
    case "vertical"
        rotChoice = 'Make Vertical';
    case "horizontal"
        rotChoice = 'Make Horizontal';
    case "user"
        rotChoice = 'User angle';
    otherwise
        error('Unsupported rot_mode.');
end
userAngle = OPT.user_angle;

% --------------------------
% Sample names
% --------------------------
nFiles = numel(filename);
rfnm = cell(nFiles,1);
for k = 1:nFiles
    [~, rfnm{k}] = fileparts(filename{k});
end

% --------------------------
% Reference image / ROI
% --------------------------
pout_ref = imread(filename{1});
pout_ref_gray = pout_ref(:,:,end);
refSize = size(pout_ref_gray);

BWroi_base = [];

switch lower(string(OPT.mask_mode))
    case "auto"
        BWroi_base = roi_autodetection_internal_from_path(filename{1}, pth2, OPT.save_roi, OPT.overwrite);

        if interactive
            hAutoRoi = figure('Name', 'Auto-detected ROI (used for all images)', 'NumberTitle', 'off');
            imshow(pout_ref_gray, []);
            hold on;
            B = bwboundaries(BWroi_base);
            if ~isempty(B)
                plot(B{1}(:,2), B{1}(:,1), 'r', 'LineWidth', 2);
            end
            hold off;
        end

    case "draw"
        if isempty(OPT.maskVerts)
            h = figure('Name', 'Draw ROI on first image', 'NumberTitle', 'off');
            imshow(pout_ref_gray, []);
            title('Draw ROI polygon, double-click to finish');
            hpoly = impoly;
            if isempty(hpoly)
                error('ROI drawing failed.');
            end
            verts = wait(hpoly);
            if isempty(verts)
                error('ROI drawing cancelled.');
            end
            OPT.maskVerts = verts;
            close(h);
        end

        BWroi_base = roipoly(pout_ref_gray, OPT.maskVerts(:,1), OPT.maskVerts(:,2));

        if OPT.save_roi
            roiOut = fullfile(pth2, [rfnm{1} '_ROI.tif']);
            if ~OPT.overwrite
                roiOut = local_avoid_overwrite(roiOut);
            end
            imwrite(uint8(BWroi_base)*255, roiOut);
        end

    case "none"
        BWroi_base = [];

    otherwise
        error('mask_mode must be auto, draw, or none.');
end

% --------------------------
% Control file detection
% --------------------------
controlFiles = OPT.control_files;
if isempty(controlFiles)
    controlFiles = auto_detect_control_files_from_list(filename);
end
if isempty(controlFiles)
    controlFiles = filename;
end

% --------------------------
% Build normalized control intensity distribution
% --------------------------
normalizedControlVals = [];
for jj = 1:numel(controlFiles)
    vals = collect_normalized_tile_intensity_mask( ...
        controlFiles{jj}, BWroi_base, refSize, windowSize, ...
        tileFracThresh, rotChoice, userAngle);
    normalizedControlVals = [normalizedControlVals; vals(:)]; %#ok<AGROW>
end

normalizedControlVals = normalizedControlVals(isfinite(normalizedControlVals) & normalizedControlVals > 0);
if isempty(normalizedControlVals)
    error('No valid control tile intensities found for low-SHG threshold.');
end

lowShgThresh = prctile(normalizedControlVals, OPT.low_shg_percentile);

qcFigPath = '';
if OPT.save_figures
    ctrlThreshFig = figure('Visible', 'off', 'Name', 'Low SHG Threshold QC', 'NumberTitle', 'off');
    histogram(normalizedControlVals, 40);
    hold on;
    xline(lowShgThresh, 'r', 'LineWidth', 2);
    hold off;
    xlabel('Normalized SHG tile intensity (tile / image median)');
    ylabel('Tile count');
    title(sprintf('Control normalized SHG threshold QC (Percentile = %.1f, Threshold = %.4f)', ...
        OPT.low_shg_percentile, lowShgThresh), 'Interpreter', 'none');
    grid on;

    qcFigPath = fullfile(pth2, 'ControlThreshold_QC.tiff');
    if ~OPT.overwrite
        qcFigPath = local_avoid_overwrite(qcFigPath);
    end
    exportgraphics(ctrlThreshFig, qcFigPath, 'Resolution', 200);
    close(ctrlThreshFig);
end

% --------------------------
% Outputs
% --------------------------
ang_var          = nan(nFiles, 3);
ang_dev          = nan(nFiles, 2);
ang_var_noDam    = nan(nFiles, 3);
ang_dev_noDam    = nan(nFiles, 2);

PercDam          = zeros(nFiles, 1);
N_total          = zeros(nFiles, 1);
FracLowSHG       = zeros(nFiles, 1);
pixArea_all      = zeros(nFiles, 1);

damMaskPaths     = cell(nFiles,1);
notDamMaskPaths  = cell(nFiles,1);
lowMaskPaths     = cell(nFiles,1);
highMaskPaths    = cell(nFiles,1);
unknownMaskPaths = cell(nFiles,1);
quiverPaths      = cell(nFiles,1);
histPaths        = cell(nFiles,1);
summaryPaths     = cell(nFiles,1);
anglePaths       = cell(nFiles,1);

summaryFile = fullfile(pth2, 'SHG_damage_summary.txt');
fid = -1;

if OPT.save_stats
    fid = fopen(summaryFile, 'w');
    if fid == -1
        error('Cannot open summary file: %s', summaryFile);
    end
    fprintf(fid, 'Sample\tValidTiles\tDamagedTiles\tNotDamagedTiles\tDamFrac\tCV_all\tCV_noDam\tDeltaCV\n');
end

% --------------------------
% Main loop
% --------------------------
for jj = 1:nFiles

    pout_init = imread(filename{jj});
    pout_orig = pout_init(:,:,end);
    clear pout_init

    pout = apply_user_rotation(pout_orig, rotChoice, userAngle);
    validSupport = rotated_support_mask(size(pout_orig), rotChoice, userAngle);

    if ~isempty(BWroi_base)
        if ~isequal(size(pout_orig), refSize)
            BW4_orig = imresize(BWroi_base, size(pout_orig), 'nearest');
        else
            BW4_orig = BWroi_base;
        end

        BW4 = logical(apply_user_rotation(BW4_orig, rotChoice, userAngle));
        BW4 = BW4 & validSupport;
        pout_mask = maskout(pout, BW4);
        pixArea = bwarea(BW4_orig);
    else
        BW4 = validSupport;
        BW4_orig = undo_user_rotation(BW4, rotChoice, userAngle, size(pout_orig));
        pout_mask = pout;
        pixArea = bwarea(logical(BW4));
    end
    pixArea_all(jj) = pixArea;

    if doEnhance
        pout_imadjust = imadjust(pout_mask);
        thresh = graythresh(pout_imadjust);
        pout_sharp = imsharpen(pout_imadjust, 'Threshold', thresh);
    else
        pout_sharp = pout_mask;
    end
    clear pout pout_imadjust

    pout_tiles     = mat2tiles(pout_sharp, windowSize);
    pout_tiles_raw = mat2tiles(pout_mask, windowSize);
    BW_tiles       = mat2tiles(BW4, windowSize);
    tileSize       = windowSize(1) * windowSize(2);

    imageDim = size(pout_sharp);

    X = 0:windowSize(2):imageDim(2);
    if length(X) < size(BW_tiles,2)
        X = cat(2, X, X(end)+windowSize(2));
    end
    Y = windowSize(1)/2:windowSize(2):imageDim(1);
    if length(Y) < size(BW_tiles,1)
        Y = cat(2, Y, Y(end)+windowSize(1));
    end
    [x, y] = meshgrid(X, Y);

    ellipse_orient    = cell(size(pout_tiles));
    Eccent            = nan(size(pout_tiles));
    tileMeanIntensity = nan(size(pout_tiles));
    imageTileSize     = numel(pout_tiles);

    parfor ii = 1:imageTileSize
        if sum(BW_tiles{ii}(:)) < tileFracThresh * tileSize
            ellipse_orient{ii}    = NaN;
            Eccent(ii)            = NaN;
            tileMeanIntensity(ii) = NaN;
            continue
        end

        roiPix = double(pout_tiles_raw{ii}(BW_tiles{ii} > 0));
        if isempty(roiPix)
            tileMeanIntensity(ii) = NaN;
        else
            tileMeanIntensity(ii) = mean(roiPix);
        end

        transforms    = fftshift(abs(fft2(pout_tiles{ii})));
        normTransform = log(transforms + 1);

        h_filt        = ones(3,3)/9;
        filtTransform = imfilter(normTransform, h_filt);
        grayT         = mat2gray(filtTransform);

        top10 = quantile(grayT(:), 0.90);
        ell   = imbinarize(grayT, top10);
        ell   = bwareaopen(ell, 12);

        CC = bwconncomp(ell);
        if CC.NumObjects == 1
            S = regionprops(ell, 'orientation', 'eccentricity');
        else
            ell2 = ell * 2;
            S = regionprops(ell2, 'orientation', 'eccentricity');
            if isempty(S)
                ellipse_orient{ii} = NaN;
                Eccent(ii) = 0;
                continue
            end
            S(1) = [];
        end

        ellipse_orient{ii} = S.Orientation;
        Eccent(ii) = S.Eccentricity;
    end

    tileMeanIntensityNorm = normalize_tile_values(tileMeanIntensity);

    ellipseAngles                 = cell2mat(ellipse_orient);
    fiberAngles                   = ellipseAngles + 90;
    fiberAngles(fiberAngles > 90) = fiberAngles(fiberAngles > 90) - 180;

    ValidTile = ~isnan(fiberAngles) & ~isnan(Eccent);

    tempL = cat(2, nan(size(fiberAngles,1),1), fiberAngles(:,1:end-1));
    diffL = abs(fiberAngles - tempL);
    tempR = cat(2, fiberAngles(:,2:end), nan(size(fiberAngles,1),1));
    diffR = abs(fiberAngles - tempR);

    UnknownTile = ValidTile & (Eccent < EccMin);
    DamTile     = ValidTile & (Eccent < EccMin | diffL > DamThreshDeg | diffR > DamThreshDeg);
    NotDamTile  = ValidTile & ~DamTile;

    N_total(jj) = nnz(ValidTile);

    Daminds     = find(DamTile);
    NotDaminds  = find(NotDamTile);
    Unknowninds = find(UnknownTile);

    BWdam = zeros(size(BW4));
    for ii = 1:numel(Daminds)
        [I, J] = ind2sub(size(DamTile), Daminds(ii));
        BWdam((I-1)*windowSize(1)+1:I*windowSize(1), ...
              (J-1)*windowSize(2)+1:J*windowSize(2)) = 1;
    end

    BWunknown = zeros(size(BW4));
    if SaveUnknownMask
        for ii = 1:numel(Unknowninds)
            [I, J] = ind2sub(size(UnknownTile), Unknowninds(ii));
            BWunknown((I-1)*windowSize(1)+1:I*windowSize(1), ...
                      (J-1)*windowSize(2)+1:J*windowSize(2)) = 1;
        end
    end

    if DoSpatialCleanup
        minPx = max(1, MinDamObjPixels * windowSize(1));
        BWdam = bwareaopen(logical(BWdam), minPx);
        BWdam = imclose(BWdam, strel('disk', 2));
        BWdam = double(BWdam);

        if SaveUnknownMask
            BWunknown = bwareaopen(logical(BWunknown), minPx);
            BWunknown = double(BWunknown);
        end
    end

    BWnotDam = logical(BW4) & ~logical(BWdam);

    lowIntensityTile = tileMeanIntensityNorm < lowShgThresh;
    lowIntensityTile(~isfinite(tileMeanIntensityNorm)) = false;

    BWlow = zeros(size(BW4));
    indsLow = find(lowIntensityTile);
    for ii = 1:numel(indsLow)
        [I, J] = ind2sub(size(lowIntensityTile), indsLow(ii));
        BWlow((I-1)*windowSize(1)+1:I*windowSize(1), ...
              (J-1)*windowSize(2)+1:J*windowSize(2)) = 1;
    end
    BWlow  = logical(BWlow) & logical(BW4);
    BWhigh = logical(BW4) & ~BWlow;

    FracLowSHG(jj) = nnz(lowIntensityTile) / max(1, nnz(isfinite(tileMeanIntensityNorm)));

    BWdam_save    = undo_user_rotation(logical(BWdam), rotChoice, userAngle, size(pout_orig));
    BWnotDam_save = undo_user_rotation(logical(BWnotDam), rotChoice, userAngle, size(pout_orig));
    BWlow_save    = undo_user_rotation(logical(BWlow), rotChoice, userAngle, size(pout_orig));
    BWhigh_save   = undo_user_rotation(logical(BWhigh), rotChoice, userAngle, size(pout_orig));
    BWunk_save    = undo_user_rotation(logical(BWunknown), rotChoice, userAngle, size(pout_orig));

    if OPT.save_masks
        saveAllMasks   = any(OPT.mask_types == "all");
        saveDamMask    = saveAllMasks || any(OPT.mask_types == "damaged");
        saveNotDamMask = saveAllMasks || any(OPT.mask_types == "undamaged");
        saveLowMask    = saveAllMasks || any(OPT.mask_types == "low_shg");
        saveHighMask   = saveAllMasks || any(OPT.mask_types == "high_shg");

        if saveDamMask
            damMaskPaths{jj} = fullfile(pth2, [rfnm{jj} '_BWdam.tif']);
            if ~OPT.overwrite
                damMaskPaths{jj} = local_avoid_overwrite(damMaskPaths{jj});
            end
            imwrite(uint8(BWdam_save)*255, damMaskPaths{jj});
        end

        if saveNotDamMask
            notDamMaskPaths{jj} = fullfile(pth2, [rfnm{jj} '_BWnotDam.tif']);
            if ~OPT.overwrite
                notDamMaskPaths{jj} = local_avoid_overwrite(notDamMaskPaths{jj});
            end
            imwrite(uint8(BWnotDam_save)*255, notDamMaskPaths{jj});
        end

        if saveLowMask
            lowMaskPaths{jj} = fullfile(pth2, [rfnm{jj} '_BWlowSHG.tif']);
            if ~OPT.overwrite
                lowMaskPaths{jj} = local_avoid_overwrite(lowMaskPaths{jj});
            end
            imwrite(uint8(BWlow_save)*255, lowMaskPaths{jj});
        end

        if saveHighMask
            highMaskPaths{jj} = fullfile(pth2, [rfnm{jj} '_BWhighSHG.tif']);
            if ~OPT.overwrite
                highMaskPaths{jj} = local_avoid_overwrite(highMaskPaths{jj});
            end
            imwrite(uint8(BWhigh_save)*255, highMaskPaths{jj});
        end

        if SaveUnknownMask
            unknownMaskPaths{jj} = fullfile(pth2, [rfnm{jj} '_BWunknown.tif']);
            if ~OPT.overwrite
                unknownMaskPaths{jj} = local_avoid_overwrite(unknownMaskPaths{jj});
            end
            imwrite(uint8(BWunk_save)*255, unknownMaskPaths{jj});
        end
    end

    PercDam(jj) = nnz(DamTile) / max(1, nnz(ValidTile));

    arrowLength = 15;
    u = arrowLength * cosd(fiberAngles);
    v = -arrowLength * sind(fiberAngles);

    if OPT.save_figures
        qPlot = figure('Visible', 'off', 'Name', [rfnm{jj} ' Quiver'], 'NumberTitle', 'off');
        imshow(pout_sharp, []); hold on;
        qG = quiver(x(NotDaminds), y(NotDaminds), u(NotDaminds), v(NotDaminds), ...
            'ShowArrowHead', 'on', 'AutoScale', 'off');
        set(qG, 'Color', 'g', 'LineWidth', 1);

        qD = quiver(x(Daminds), y(Daminds), u(Daminds), v(Daminds), ...
            'ShowArrowHead', 'on', 'AutoScale', 'off');
        set(qD, 'Color', 'r', 'LineWidth', 1);
        hold off;
        title('SHG Fiber Orientation (Green = Not damaged, Red = Damaged)');
    end

    theta           = fiberAngles(:);
    theta_good      = theta(ValidTile(:) & ~isnan(theta));
    theta_goodNoDam = theta(NotDamTile(:) & ~isnan(theta));

    if ~isempty(theta_good)
        [ang_var(jj,:), ang_dev(jj,:)] = circ_disp(theta_good);
    end
    if ~isempty(theta_goodNoDam)
        [ang_var_noDam(jj,:), ang_dev_noDam(jj,:)] = circ_disp(theta_goodNoDam);
    end

    cv_overall = ang_var(jj,1);
    cv_noDam   = ang_var_noDam(jj,1);
    delta_cv   = cv_overall - cv_noDam;

    if OPT.save_stats
        fprintf(fid, '%s\t%d\t%d\t%d\t%.4f\t%.6f\t%.6f\t%.6f\n', ...
            rfnm{jj}, nnz(ValidTile), nnz(DamTile), nnz(NotDamTile), ...
            PercDam(jj), cv_overall, cv_noDam, delta_cv);

        summaryPaths{jj} = fullfile(pth2, [rfnm{jj} '_damageSummary.txt']);
        if ~OPT.overwrite
            summaryPaths{jj} = local_avoid_overwrite(summaryPaths{jj});
        end
        fid2 = fopen(summaryPaths{jj}, 'w');
        fprintf(fid2, 'Sample:\t%s\n', rfnm{jj});
        fprintf(fid2, 'ValidTiles:\t%d\n', nnz(ValidTile));
        fprintf(fid2, 'DamagedTiles:\t%d\n', nnz(DamTile));
        fprintf(fid2, 'NotDamagedTiles:\t%d\n', nnz(NotDamTile));
        fprintf(fid2, 'DamFrac:\t%.4f\n', PercDam(jj));
        fprintf(fid2, 'CV_all:\t%.6f\n', cv_overall);
        fprintf(fid2, 'CV_noDam:\t%.6f\n', cv_noDam);
        fprintf(fid2, 'DeltaCV:\t%.6f\n', delta_cv);
        fclose(fid2);

        theta_mat = fiberAngles;
        [y_pos, x_pos] = ind2sub(size(theta_mat), 1:numel(theta_mat));
        x_pos = x_pos(:);
        y_pos = y_pos(:);
        theta_vec = theta_mat(:);

        pixScale = 1024 / 276.79;
        write_angles(theta_vec, rfnm{jj}, pth2, windowSize, x_pos, y_pos, pixArea, pixScale);
        anglePaths{jj} = fullfile(pth2, [rfnm{jj} '_SHGangles.txt']);
    end

    if OPT.save_figures
        histFig = figure('Visible', 'off', 'Name', [rfnm{jj} ' Angular Frequency'], 'NumberTitle', 'off');
        numBins = 25;
        if ~isempty(theta_good)
            histfit(theta_good, numBins);
        else
            histogram([]);
        end
        xlabel('Angle (deg)');
        ylabel('Angular Frequency');
        title('Angular Frequency');
        grid on

        quiverPaths{jj} = fullfile(pth2, [rfnm{jj} '_quiver.tiff']);
        histPaths{jj}   = fullfile(pth2, [rfnm{jj} '_hist.tiff']);
        if ~OPT.overwrite
            quiverPaths{jj} = local_avoid_overwrite(quiverPaths{jj});
            histPaths{jj}   = local_avoid_overwrite(histPaths{jj});
        end

        exportgraphics(qPlot, quiverPaths{jj}, 'Resolution', 200);
        exportgraphics(histFig, histPaths{jj}, 'Resolution', 200);
        close(qPlot);
        close(histFig);
    end
end

if fid ~= -1
    fclose(fid);
end

SHGcircstats = fullfile(pth2, [rfnm{1} '_SHGstats.txt']);
if ~OPT.overwrite
    SHGcircstats = local_avoid_overwrite(SHGcircstats);
end

head_txt = {
'%Sample Name	N_notDamaged (%)	N_valid (#)	Cropped Area (pix)	Cir-Var (rad^2)	Ang-Var (rad^2)	Standard-Var (rad^2)	Ang-Dev(deg)	Cir-Dev (deg)	Cir-Var_noDam (rad^2)	Ang-Var_noDam (rad^2)	Standard-Var_noDam (rad^2)	Ang-Dev_noDam (deg)	Cir-Dev_noDam (deg)'
};

circularVariance  = ang_var(:,1);
angularVariance   = ang_var(:,2);
standardVariance  = ang_var(:,3);
angularDeviation  = ang_dev(:,1);
circularDeviation = ang_dev(:,2);

circularVariance_noDam  = ang_var_noDam(:,1);
angularVariance_noDam   = ang_var_noDam(:,2);
standardVariance_noDam  = ang_var_noDam(:,3);
angularDeviation_noDam  = ang_dev_noDam(:,1);
circularDeviation_noDam = ang_dev_noDam(:,2);

N_good = 100 - (100 * PercDam);

dataLines = cell(nFiles, 1);
for ij = 1:nFiles
    dataLines{ij} = sprintf('%s\t%.3f\t%d\t%d\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f', ...
        rfnm{ij}, N_good(ij), N_total(ij), round(pixArea_all(ij)), ...
        circularVariance(ij), angularVariance(ij), standardVariance(ij), ...
        angularDeviation(ij), circularDeviation(ij), ...
        circularVariance_noDam(ij), angularVariance_noDam(ij), standardVariance_noDam(ij), ...
        angularDeviation_noDam(ij), circularDeviation_noDam(ij));
end

if OPT.save_stats
    report_text = [head_txt; dataLines];
    write_report(report_text, SHGcircstats);
end

results = struct();
results.input_files          = filename;
results.output_dir           = pth2;
results.mask_mode            = char(OPT.mask_mode);
results.low_shg_percentile   = OPT.low_shg_percentile;
results.low_shg_threshold    = lowShgThresh;
results.summary_file         = summaryFile;
results.shg_stats_file       = SHGcircstats;
results.control_threshold_qc = qcFigPath;

results.sample_names         = rfnm;
results.valid_tiles          = N_total;
results.damage_fraction      = PercDam;
results.low_shg_fraction     = FracLowSHG;
results.pixel_area           = pixArea_all;

results.circular_variance_all    = ang_var(:,1);
results.circular_variance_noDam  = ang_var_noDam(:,1);

results.dam_mask_paths       = damMaskPaths;
results.not_dam_mask_paths   = notDamMaskPaths;
results.low_mask_paths       = lowMaskPaths;
results.high_mask_paths      = highMaskPaths;
results.unknown_mask_paths   = unknownMaskPaths;
results.quiver_paths         = quiverPaths;
results.hist_paths           = histPaths;
results.per_image_summary    = summaryPaths;
results.angle_paths          = anglePaths;
results.elapsed_sec          = toc(tStart);

end

% =========================================================================
% HELPERS
% =========================================================================

function controlFiles = auto_detect_control_files_from_list(fileList)
controlFiles = {};
for i = 1:numel(fileList)
    [~, nm, ext] = fileparts(fileList{i});
    thisName = lower([nm ext]);
    if ~isempty(regexp(thisName, '(^|_)\d+l(_|$)', 'once'))
        controlFiles{end+1,1} = fileList{i}; %#ok<AGROW>
    end
end
end

function mask = roi_autodetection_internal_from_path(fullpath, savedir, saveROI, overwriteFlag)

img = imread(fullpath);
if ndims(img) == 3
    I = img(:,:,end);
else
    I = img;
end

I  = mat2gray(I);
th = 0.02;
bw = I > th;

bw = bwareaopen(bw, 500);
bw = imfill(bw, 'holes');
bw = imclose(bw, strel('disk', 15));
bw = imopen(bw, strel('disk', 5));

cc = bwconncomp(bw);
numPixels = cellfun(@numel, cc.PixelIdxList);

mask = false(size(bw));
if ~isempty(numPixels)
    [~, idxLargest] = max(numPixels);
    mask(cc.PixelIdxList{idxLargest}) = true;
end

if ~any(mask(:))
    error('ROI auto-detection failed for %s', fullpath);
end

if saveROI
    [~, filename, ~] = fileparts(fullpath);
    mask_name = fullfile(savedir, [filename '_mask.tif']);
    roi_name  = fullfile(savedir, [filename '_ROI.png']);

    if ~overwriteFlag
        mask_name = local_avoid_overwrite(mask_name);
        roi_name  = local_avoid_overwrite(roi_name);
    end

    imwrite(mask, mask_name);

    stats = regionprops(mask, 'BoundingBox');
    bbox = stats(1).BoundingBox;
    B = bwboundaries(mask);
    boundary = B{1};

    hf = figure('Visible', 'off');
    imshow(I, []);
    hold on;
    plot(boundary(:,2), boundary(:,1), 'r', 'LineWidth', 2);
    rectangle('Position', bbox, 'EdgeColor', 'g', 'LineWidth', 2);
    title(filename, 'Interpreter', 'none');
    exportgraphics(hf, roi_name, 'Resolution', 200);
    close(hf);
end
end

function vals = collect_normalized_tile_intensity_mask(imagePath, BWroi_base, refSize, ...
    windowSize, tileFracThresh, rotChoice, userAngle)

img_init = imread(imagePath);
img_orig = img_init(:,:,end);

img_rot      = apply_user_rotation(img_orig, rotChoice, userAngle);
validSupport = rotated_support_mask(size(img_orig), rotChoice, userAngle);

if ~isempty(BWroi_base)
    if ~isequal(size(img_orig), refSize)
        BW_orig = imresize(BWroi_base, size(img_orig), 'nearest');
    else
        BW_orig = BWroi_base;
    end
    BW = logical(apply_user_rotation(BW_orig, rotChoice, userAngle));
    BW = BW & validSupport;
else
    BW = validSupport;
end

img_mask  = maskout(img_rot, BW);
img_tiles = mat2tiles(img_mask, windowSize);
BW_tiles  = mat2tiles(BW, windowSize);
tileSize  = windowSize(1) * windowSize(2);

vals = nan(numel(img_tiles), 1);
for ii = 1:numel(img_tiles)
    thisROITile = BW_tiles{ii};
    if sum(thisROITile(:)) < tileFracThresh * tileSize
        continue
    end
    roiPix = double(img_tiles{ii}(thisROITile > 0));
    if ~isempty(roiPix)
        vals(ii) = mean(roiPix);
    end
end

vals = normalize_tile_values(vals);
vals = vals(isfinite(vals) & vals > 0);
end

function valsNorm = normalize_tile_values(vals)
valsNorm = vals;
valid = isfinite(valsNorm) & valsNorm > 0;
if ~any(valid), return; end

scaleVal = median(valsNorm(valid));
if ~isfinite(scaleVal) || scaleVal <= 0, return; end
valsNorm(valid) = valsNorm(valid) ./ scaleVal;
end

function BW = rotated_support_mask(inSize, rotChoice, userAngle)
BW = apply_user_rotation(true(inSize), rotChoice, userAngle);
BW = logical(BW);
end

function Irot = apply_user_rotation(I, rotChoice, userAngle)
switch rotChoice
    case 'None'
        Irot = I;
    case 'Make Vertical'
        Irot = rot90(I, 1);
    case 'Make Horizontal'
        Irot = rot90(I, -1);
    case 'User angle'
        if islogical(I)
            interpMethod = 'nearest';
        else
            interpMethod = 'bilinear';
        end
        Irot = imrotate(I, userAngle, interpMethod, 'loose');
    otherwise
        Irot = I;
end
end

function Iback = undo_user_rotation(Irot, rotChoice, userAngle, outSize)
switch rotChoice
    case 'None'
        Iback = Irot;
    case 'Make Vertical'
        Iback = rot90(Irot, -1);
    case 'Make Horizontal'
        Iback = rot90(Irot, 1);
    case 'User angle'
        Iback = imrotate(Irot, -userAngle, 'nearest', 'loose');
        Iback = center_crop_or_pad(Iback, outSize, false);
    otherwise
        Iback = Irot;
end

if ~isequal(size(Iback), outSize)
    Iback = center_crop_or_pad(Iback, outSize, false);
end
Iback = logical(Iback);
end

function out = center_crop_or_pad(I, outSize, fillValue)
if nargin < 3
    fillValue = 0;
end

out = zeros(outSize, 'like', I);
if fillValue ~= 0
    out(:) = cast(fillValue, 'like', I);
end

inSize = size(I);
r = min(inSize(1), outSize(1));
c = min(inSize(2), outSize(2));

srcR1 = floor((inSize(1) - r) / 2) + 1;
srcC1 = floor((inSize(2) - c) / 2) + 1;
dstR1 = floor((outSize(1) - r) / 2) + 1;
dstC1 = floor((outSize(2) - c) / 2) + 1;

out(dstR1:dstR1+r-1, dstC1:dstC1+c-1) = I(srcR1:srcR1+r-1, srcC1:srcC1+c-1);
end

function outPath = local_avoid_overwrite(outPath)
if ~exist(outPath, 'file')
    return;
end
[folder, name, ext] = fileparts(outPath);
k = 1;
while true
    candidate = fullfile(folder, sprintf('%s_%03d%s', name, k, ext));
    if ~exist(candidate, 'file')
        outPath = candidate;
        return;
    end
    k = k + 1;
end
end
