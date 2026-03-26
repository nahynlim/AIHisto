function [] = FFT_align_msk_update() %(as of 03/24/2026)
% FFT_align_msk (v2 - FIXED)
% Fixes: ROI mask is created once outside the main loop and reused across
% all images, eliminating per-image edge artifacts caused by repeated
% roipoly calls and center_crop_or_pad inside the loop.
% Adds: normalized SHG intensity threshold from control images,
% user-selectable image rotation, lowSHG / highSHG masks,
% left/right angle difference damage check,
% eccentricity-based damage gating, optional spatial cleanup.

tic

% Start parallel pool if not already running
p = gcp('nocreate');
if isempty(p)
    parpool;
end

clearvars -except inipth;
close all;

% ==========================
% OPTIMIZATION PARAMETERS
% ==========================
DamThreshDeg     = 15;    % (deg) neighbor angle discontinuity threshold
EccMin           = 0.80;  % eccentricity >= EccMin => reliable orientation
DoSpatialCleanup = true;  % apply morphological cleanup to BWdam
MinDamObjPixels  = 3*15;  % min object size in pixels for BWdam cleanup (scaled later)

% ==========================
% UI + SETUP
% ==========================
if (~exist('inipth','var') || inipth==0)
    inipth = 'C:\Users\Spence\Documents\CloudStation';
end

[fnm, pth] = uigetfile('*.tif', 'Select SHG image to analyze', inipth);
inipth = pth;
if (fnm == 0)
    uiwait(warndlg('You''re doing it wrong!'));
    return;
end

% Filter to SHG images ending in _0000.tif
Sdir     = dir(fullfile(pth, '*.tif'));
allNames = {Sdir.name};
isSHG    = endsWith(lower(allNames), '_0000.tif');
Sdir     = Sdir(isSHG);
fnames   = {Sdir.name};

if isempty(fnames)
    errordlg('No SHG images ending in _0000.tif were found in this folder.');
    return;
end

sr_v = listdlg('PromptString', 'Choose SHG channel images', ...
    'SelectionMode', 'Multiple', 'Name', '.tif SHG collagen images', ...
    'InitialValue', 1:min(2,length(fnames)), 'ListString', fnames, 'Listsize', [300 400]);
if isempty(sr_v)
    uiwait(warndlg('OOPS! There doesn''t seem to be anything here!'));
    return;
end

filename = cell(length(sr_v), 1);
for i = 1:length(sr_v)
    filename{i} = fullfile(pth, fnames{sr_v(i)});
end

% Auto-detect control files by _L pattern
controlFiles = {};
for i = 1:length(fnames)
    thisName = lower(fnames{i});
    if ~isempty(regexp(thisName, '(^|_)\d+l(_|$)', 'once'))
        controlFiles{end+1, 1} = fullfile(pth, fnames{i}); %#ok<AGROW>
    end
end

if isempty(controlFiles)
    errordlg('No control SHG images were auto-detected. Expected _0000.tif filenames containing patterns like 3L.');
    return;
end

maskChoice = questdlg('Do you need to create a mask?', 'Masking option', ...
    'That sounds great', 'Already did', 'What?', 'That sounds great');

ang_var       = zeros(length(filename), 3);
ang_dev       = zeros(length(filename), 2);
ang_var_noDam = zeros(length(filename), 3);
ang_dev_noDam = zeros(length(filename), 2);

enhanceChoice = questdlg('Sharpen and enhance all images?', 'Image Enhancement', ...
    'Yes', 'No', 'unsure', 'Yes');

answer1    = inputdlg({'Enter Bundle Width (pixels):', 'Enter Bundle height (pixels):'}, ...
    'Input Window Size Parameters', 1, {'15', '15'});
windowSize = [str2double(answer1{1}), str2double(answer1{2})];

lowShgAnswer = inputdlg({'Enter normalized low-SHG percentile (i.e 15):'}, ...
    'Low SHG Threshold', 1, {'10'});
if isempty(lowShgAnswer)
    return;
end
lowShgPercentile = str2double(lowShgAnswer{1});
if ~isfinite(lowShgPercentile) || lowShgPercentile < 0 || lowShgPercentile > 100
    errordlg('Low SHG percentile must be between 0 and 100.');
    return;
end

% Rotation options
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
    return;
end

switch rotIdx
    case 1, rotChoice = 'None';
    case 2, rotChoice = 'Make Vertical';
    case 3, rotChoice = 'Make Horizontal';
    case 4, rotChoice = 'User angle';
    otherwise, rotChoice = 'None';
end

userAngle = 0;
if strcmp(rotChoice, 'User angle')
    angAns = inputdlg( ...
        {'Enter rotation angle in degrees (positive = CCW, negative = CW):'}, ...
        'User Rotation Angle', 1, {'45'});
    if isempty(angAns)
        return;
    end
    userAngle = str2double(angAns{1});
    if ~isfinite(userAngle)
        errordlg('Rotation angle must be a number.');
        return;
    end
end

saveChoice = questdlg('Would you like to save your figures?', 'Save Figures', ...
    'Yes', 'No', 'I''m not sure', 'Yes');

h1 = waitbar(0, 'Analyzing images...');

rfnm = cell(length(filename), 1);
for k = 1:length(filename)
    [~, rfnm{k}] = fileparts(filename{k});
end

nameInt = rfnm{1};
[fnm2, pth2] = uiputfile([nameInt, '_SHGstats.txt'], 'Choose Collagen Fiber Organization Output File');
if (fnm2 == 0)
    warndlg('Not Saving Data');
    return;
end
SHGcircstats = fullfile(pth2, fnm2);

% ==========================
% ROI MASK — created ONCE outside the loop, reused for all images
% This prevents per-image edge artifacts that occurred when roipoly
% and center_crop_or_pad were called inside the loop.
% ==========================
cmsk       = [];
rmsk       = [];
BWroi_base = [];   % base ROI mask in original image coordinates
refSize    = [];   % reference image size for ROI

if strcmp(maskChoice, 'That sounds great')
    pout_draw = imread(filename{1});
    pout_draw = pout_draw(:,:,end);
    refSize   = size(pout_draw);   % store reference size

    hRoi = create_roi_figure();
    show_roi_image(hRoi, pout_draw);
    uiwait(msgbox('Draw border around the ROI'));
    Hply     = impoly;
    poly_pos = wait(Hply);
    delete(Hply);
    hold on
    plot(poly_pos([1:end,1], 1), poly_pos([1:end,1], 2), 'r+-');
    cmsk = poly_pos(:,1);
    rmsk = poly_pos(:,2);

    % Create ROI mask once from the first image
    BWroi_base = roipoly(pout_draw, cmsk, rmsk);
    roiOut     = fullfile(pth2, [rfnm{1} '_ROI.tif']);
    imwrite(uint8(BWroi_base)*255, roiOut);
    close(hRoi);
end

PercDam    = zeros(length(filename), 1);
N_total    = zeros(length(filename), 1);
FracLowSHG = zeros(length(filename), 1);
pixArea_all = zeros(length(filename), 1);

tileFracThresh      = 0.75;
normalizedControlVals = [];

% Collect normalized tile intensities from control images
for jj = 1:length(controlFiles)
    vals = collect_normalized_tile_intensity(controlFiles{jj}, strcmp(maskChoice, 'That sounds great'), ...
        cmsk, rmsk, windowSize, tileFracThresh, rotChoice, userAngle);
    normalizedControlVals = [normalizedControlVals; vals(:)]; %#ok<AGROW>
end

normalizedControlVals = normalizedControlVals(isfinite(normalizedControlVals) & normalizedControlVals > 0);
if isempty(normalizedControlVals)
    errordlg('No valid control tile intensities were found for the normalized low-SHG threshold.');
    return;
end

lowShgThresh = prctile(normalizedControlVals, lowShgPercentile);

% QC plot for control threshold
ctrlThreshFig = figure('Visible', 'on', 'Name', 'Low SHG Threshold QC', 'NumberTitle', 'off');
histogram(normalizedControlVals, 40, 'FaceColor', [0.25 0.45 0.75], 'EdgeColor', 'none');
hold on;
xline(lowShgThresh, 'r', 'LineWidth', 2);
hold off;
xlabel('Normalized SHG tile intensity (tile / image median)');
ylabel('Tile count');
title(sprintf('Control normalized SHG threshold QC (Percentile = %.1f, Threshold = %.4f)', ...
    lowShgPercentile, lowShgThresh), 'Interpreter', 'none');
grid on;
drawnow;

if strcmp(saveChoice, 'Yes')
    saveas(ctrlThreshFig, fullfile(pth2, 'ControlThreshold_QC.tiff'));
end

% ==========================
% OPEN SUMMARY FILE
% ==========================
summaryFile = fullfile(pth2, 'SHG_damage_summary.txt');
fid         = fopen(summaryFile, 'w');
fprintf(fid, 'Sample\tValidTiles\tDamagedTiles\tNotDamagedTiles\tDamFrac\tCV_all\tCV_noDam\tDeltaCV\n');

% ==========================
% MAIN LOOP
% ==========================
for jj = 1:length(filename)
    waitbar(jj/length(filename), h1);

    pout_init = imread(filename{jj});
    pout_orig = pout_init(:,:,end);
    clear pout_init

    % Apply user rotation
    pout         = apply_user_rotation(pout_orig, rotChoice, userAngle);
    validSupport = rotated_support_mask(size(pout_orig), rotChoice, userAngle);

    % -----------------------------------------------------------------
    % ROI APPLICATION — reuse BWroi_base created before the loop.
    % Avoids repeated roipoly calls and center_crop_or_pad that caused
    % edge artifacts in the saved masks.
    % -----------------------------------------------------------------
    if strcmp(maskChoice, 'That sounds great')
        % Resize base ROI if this image differs from reference size
        if ~isequal(size(pout_orig), refSize)
            BW4_orig = imresize(BWroi_base, size(pout_orig), 'nearest');
        else
            BW4_orig = BWroi_base;
        end

        % Rotate ROI to match rotated image, intersect with valid support
        BW4      = apply_user_rotation(BW4_orig, rotChoice, userAngle);
        BW4      = logical(BW4) & validSupport;

        pout_mask = maskout(pout, BW4);
        pixArea   = bwarea(BW4_orig);
    else
        BW4      = validSupport;
        BW4_orig = undo_user_rotation(BW4, rotChoice, userAngle, size(pout_orig));
        pout_mask = pout;
        pixArea   = bwarea(logical(BW4));
    end
    pixArea_all(jj) = pixArea;

    % Enhance image if requested
    if strcmp(enhanceChoice, 'Yes')
        pout_imadjust = imadjust(pout_mask);
        thresh        = graythresh(pout_imadjust);
        pout_sharp    = imsharpen(pout_imadjust, 'Threshold', thresh);
    else
        pout_sharp = pout_mask;
    end
    clear pout pout_imadjust

    % Tile SHG image and ROI mask
    pout_tiles     = mat2tiles(pout_sharp, windowSize);
    pout_tiles_raw = mat2tiles(pout_mask, windowSize);
    BW_tiles       = mat2tiles(BW4, windowSize);
    tileSize       = windowSize(1) * windowSize(2);

    imageDim = size(pout_sharp);

    % Build quiver grid coordinates
    X = 0:windowSize(2):imageDim(2);
    if length(X) < size(BW_tiles, 2)
        X = cat(2, X, X(end)+windowSize(2));
    end
    Y = windowSize(1)/2:windowSize(2):imageDim(1);
    if length(Y) < size(BW_tiles, 1)
        Y = cat(2, Y, Y(end)+windowSize(1));
    end
    [x, y] = meshgrid(X, Y);

    ellipse_orient    = cell(size(pout_tiles));
    Eccent            = nan(size(pout_tiles));
    tileMeanIntensity = nan(size(pout_tiles));

    imageTileSize = numel(pout_tiles);

    % ==========================
    % FFT ORIENTATION PER TILE
    % ==========================
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

        h             = ones(3,3)/9;
        filtTransform = imfilter(normTransform, h);
        grayT         = mat2gray(filtTransform);

        top10 = quantile(grayT(:), 0.90);
        ell   = imbinarize(grayT, top10);
        ell   = bwareaopen(ell, 12);

        CC = bwconncomp(ell);
        if CC.NumObjects == 1
            S = regionprops(ell, 'orientation', 'eccentricity');
        else
            ell2 = ell*2;
            S    = regionprops(ell2, 'orientation', 'eccentricity');
            if isempty(S)
                ellipse_orient{ii} = NaN;
                Eccent(ii)         = 0;
                continue
            end
            S(1) = []; % drop merged component (preserves original behavior)
        end

        ellipse_orient{ii} = S.Orientation;
        Eccent(ii)         = S.Eccentricity;
    end

    tileMeanIntensityNorm = normalize_tile_values(tileMeanIntensity);

    % ==========================
    % TILE ANGLES
    % ==========================
    ellipseAngles                           = cell2mat(ellipse_orient);
    fiberAngles                             = ellipseAngles + 90;
    fiberAngles(fiberAngles > 90)           = fiberAngles(fiberAngles > 90) - 180; % keep in [-90,90]

    % Valid tile: inside ROI and FFT successfully computed
    ValidTile = ~isnan(fiberAngles) & ~isnan(Eccent);

    % Left/right neighbor angle differences (non-circular, kept for compatibility)
    tempL = cat(2, nan(size(fiberAngles,1),1), fiberAngles(:,1:end-1));
    diffL = abs(fiberAngles - tempL);
    tempR = cat(2, fiberAngles(:,2:end), nan(size(fiberAngles,1),1));
    diffR = abs(fiberAngles - tempR);

    % Damage: low eccentricity OR large left/right angle jump
    DamTile    = ValidTile & (Eccent < EccMin | diffL > DamThreshDeg | diffR > DamThreshDeg);
    N_total(jj) = nnz(ValidTile);

    % Index sets for quiver coloring
    Daminds    = find(DamTile);
    NotDamTile = ValidTile & ~DamTile;
    NotDaminds = find(NotDamTile);

    % ==========================
    % EXPAND TILE MASK TO PIXELS
    % ==========================
    BWdam = zeros(size(BW4));
    for ii = 1:numel(Daminds)
        [I, J] = ind2sub(size(DamTile), Daminds(ii));
        BWdam((I-1)*windowSize(1)+1 : I*windowSize(1), ...
              (J-1)*windowSize(2)+1 : J*windowSize(2)) = 1;
    end

    % Optional morphological cleanup to reduce salt-and-pepper noise
    if DoSpatialCleanup
        minPx = max(1, MinDamObjPixels * windowSize(1));
        BWdam = bwareaopen(logical(BWdam), minPx);
        BWdam = imclose(BWdam, strel('disk', 2));
        BWdam = double(BWdam);
    end
    BWnotDam = logical(BW4) & ~logical(BWdam);

    % Low SHG intensity mask
    lowIntensityTile = tileMeanIntensityNorm < lowShgThresh;
    lowIntensityTile(~isfinite(tileMeanIntensityNorm)) = false;

    BWlow  = zeros(size(BW4));
    indsLow = find(lowIntensityTile);
    for ii = 1:numel(indsLow)
        [I, J] = ind2sub(size(lowIntensityTile), indsLow(ii));
        BWlow((I-1)*windowSize(1)+1 : I*windowSize(1), ...
              (J-1)*windowSize(2)+1 : J*windowSize(2)) = 1;
    end
    BWlow  = logical(BWlow) & logical(BW4);
    BWhigh = logical(BW4) & ~BWlow;
    FracLowSHG(jj) = nnz(lowIntensityTile) / max(1, nnz(isfinite(tileMeanIntensityNorm)));

    % ==========================
    % SAVE MASKS — rotate back to original image orientation before saving
    % so masks align with SHG and DAPI channels
    % ==========================
    BWdam_save    = undo_user_rotation(logical(BWdam),    rotChoice, userAngle, size(pout_orig));
    BWnotDam_save = undo_user_rotation(logical(BWnotDam), rotChoice, userAngle, size(pout_orig));
    BWlow_save    = undo_user_rotation(logical(BWlow),    rotChoice, userAngle, size(pout_orig));
    BWhigh_save   = undo_user_rotation(logical(BWhigh),   rotChoice, userAngle, size(pout_orig));

    imwrite(uint8(BWdam_save)*255,    fullfile(pth2, [rfnm{jj} '_BWdam.tif']));
    imwrite(uint8(BWnotDam_save)*255, fullfile(pth2, [rfnm{jj} '_BWnotDam.tif']));
    imwrite(uint8(BWlow_save)*255,    fullfile(pth2, [rfnm{jj} '_BWlowSHG.tif']));
    imwrite(uint8(BWhigh_save)*255,   fullfile(pth2, [rfnm{jj} '_BWhighSHG.tif']));

    % Damage fraction: damaged tiles / all valid tiles
    PercDam(jj) = nnz(DamTile) / max(1, nnz(ValidTile));

    % ==========================
    % QUIVER PLOT
    % ==========================
    arrowLength = 15;
    u = arrowLength * cosd(fiberAngles);
    v = -arrowLength * sind(fiberAngles);

    qPlot = figure('Visible', 'on', 'Name', [rfnm{jj} ' Quiver'], 'NumberTitle', 'off');
    imshow(pout_sharp, []); hold on;

    % Not-damaged tiles: green
    qG = quiver(x(NotDaminds), y(NotDaminds), u(NotDaminds), v(NotDaminds), ...
        'ShowArrowHead', 'on', 'AutoScale', 'off');
    set(qG, 'Color', 'g', 'LineWidth', 1);

    % Damaged tiles: red
    qD = quiver(x(Daminds), y(Daminds), u(Daminds), v(Daminds), ...
        'ShowArrowHead', 'on', 'AutoScale', 'off');
    set(qD, 'Color', 'r', 'LineWidth', 1);

    hold off;
    title('SHG Fiber Orientation (Green = Not damaged, Red = Damaged)');
    drawnow;

    % ==========================
    % ANGLE VECTORS
    % ==========================
    theta           = fiberAngles(:);
    theta_good      = theta(ValidTile(:) & ~isnan(theta));
    theta_goodNoDam = theta(NotDamTile(:) & ~isnan(theta));
    theta_dam       = theta(DamTile(:) & ~isnan(theta));  %#ok<NASGU>

    % ==========================
    % CIRCULAR STATS
    % ==========================
    theta_stats       = theta_good;
    theta_noDam_stats = theta_goodNoDam;

    % Angular frequency histogram with normal fit
    histFig = figure('Visible', 'on', 'Name', [rfnm{jj} ' Angular Frequency'], 'NumberTitle', 'off');
    numBins = 25;
    if ~isempty(theta_stats)
        histfit(theta_stats, numBins);
    else
        histogram([]);
    end
    xlabel('Angle (deg)');
    ylabel('Angular Frequency');
    title('Angular Frequency');
    grid on
    drawnow;

    % Write angles file (legacy format, includes NaN tiles)
    theta_mat = fiberAngles;
    [y_pos, x_pos] = ind2sub(size(theta_mat), 1:numel(theta_mat));
    x_pos     = x_pos';
    y_pos     = y_pos';
    theta_vec = reshape(theta_mat, [], 1);

    pixScale = 1024 / 276.79;
    write_angles(theta_vec, rfnm{jj}, pth2, windowSize, x_pos, y_pos, pixArea, pixScale);

    % Save figures
    if strcmp(saveChoice, 'Yes')
        saveas(qPlot,   fullfile(pth2, [rfnm{jj} '_quiver.tiff']));
        saveas(histFig, fullfile(pth2, [rfnm{jj} '_hist.tiff']));
    end

    % Circular dispersion statistics
    if ~isempty(theta_stats)
        [ang_var(jj,:), ang_dev(jj,:)] = circ_disp(theta_stats);
    else
        ang_var(jj,:) = nan; ang_dev(jj,:) = nan;
    end

    if ~isempty(theta_noDam_stats)
        [ang_var_noDam(jj,:), ang_dev_noDam(jj,:)] = circ_disp(theta_noDam_stats);
    else
        ang_var_noDam(jj,:) = nan; ang_dev_noDam(jj,:) = nan;
    end

    fprintf('Image %d: valid tiles=%d, damaged tiles=%d, not-damaged tiles=%d\n', ...
        jj, nnz(ValidTile), nnz(DamTile), nnz(NotDamTile));

    % ==========================
    % PER-IMAGE SUMMARY
    % ==========================
    cv_overall = ang_var(jj,1);
    cv_noDam   = ang_var_noDam(jj,1);
    delta_cv   = cv_overall - cv_noDam;

    fprintf(fid, '%s\t%d\t%d\t%d\t%.4f\t%.6f\t%.6f\t%.6f\n', ...
        rfnm{jj}, nnz(ValidTile), nnz(DamTile), nnz(NotDamTile), ...
        PercDam(jj), cv_overall, cv_noDam, delta_cv);

    if delta_cv > 0
        fprintf('Removing damaged tiles reduces dispersion (improved coherence).\n');
    elseif delta_cv < 0
        fprintf('Warning: Removing damaged tiles increased dispersion.\n');
    else
        fprintf('No change in dispersion after removing damaged tiles.\n');
    end

    fprintf('\n[%s] cv_overall=%.4f | CV_noDam=%.4f | DeltaCV=%.4f | DamFrac=%.3f\n', ...
        rfnm{jj}, cv_overall, cv_noDam, delta_cv, PercDam(jj));

    % Write per-image summary text file
    fid2 = fopen(fullfile(pth2, [rfnm{jj} '_damageSummary.txt']), 'w');
    fprintf(fid2, 'Sample:\t%s\n',          rfnm{jj});
    fprintf(fid2, 'ValidTiles:\t%d\n',      nnz(ValidTile));
    fprintf(fid2, 'DamagedTiles:\t%d\n',    nnz(DamTile));
    fprintf(fid2, 'NotDamagedTiles:\t%d\n', nnz(NotDamTile));
    fprintf(fid2, 'DamFrac:\t%.4f\n',       PercDam(jj));
    fprintf(fid2, 'cv_overall:\t%.6f\n',    cv_overall);
    fprintf(fid2, 'CV_noDam:\t%.6f\n',      cv_noDam);
    fprintf(fid2, 'DeltaCV:\t%.6f\n',       delta_cv);
    fclose(fid2);

end % end main loop

% ==========================
% CLOSE SUMMARY FILE
% ==========================
fclose(fid);
fprintf('Summary written to: %s\n', summaryFile);

close(h1);

% ==========================
% FINAL REPORT
% ==========================
head_txt = {
'%Sample Name	N_notDamaged (%)	N_valid (#)	Cropped Area (pix)	Cir-Var (rad^2)	Ang-Var (rad^2)	Standard-Var (rad^2)	Ang-Dev(deg)	Cir-Dev (deg)	Cir-Var_noDam (rad^2)	Ang-Var_noDam (rad^2)	Standard-Var_noDam (rad^2)	Ang-Dev_noDam (deg)	Cir-Dev_noDam (deg)'
};

circularVariance = ang_var(:,1);
angularVariance  = ang_var(:,2);
standardVariance = ang_var(:,3);
angularDeviation  = ang_dev(:,1);
circularDeviation = ang_dev(:,2);

circularVariance_noDam = ang_var_noDam(:,1);
angularVariance_noDam  = ang_var_noDam(:,2);
standardVariance_noDam = ang_var_noDam(:,3);
angularDeviation_noDam  = ang_dev_noDam(:,1);
circularDeviation_noDam = ang_dev_noDam(:,2);

N_good = 100 - (100 * PercDam);

dataLines = cell(length(filename), 1);
for ij = 1:length(filename)
    dataLines{ij} = sprintf('%s\t%.3f\t%d\t%d\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f', ...
        rfnm{ij}, N_good(ij), N_total(ij), round(pixArea_all(ij)), ...
        circularVariance(ij), angularVariance(ij), standardVariance(ij), ...
        angularDeviation(ij), circularDeviation(ij), ...
        circularVariance_noDam(ij), angularVariance_noDam(ij), standardVariance_noDam(ij), ...
        angularDeviation_noDam(ij), circularDeviation_noDam(ij));
end

report_text = [head_txt; dataLines];
write_report(report_text, SHGcircstats);

% Console summary — exclude slices with >50% damage
damLog = find(N_good < 50);
dt_comp = [N_good, N_total, pixArea_all, circularVariance, angularVariance, standardVariance, ...
    angularDeviation, circularDeviation, circularVariance_noDam, angularVariance_noDam, ...
    standardVariance_noDam, angularDeviation_noDam, circularDeviation_noDam];

if ~isempty(damLog)
    dt_comp(damLog, :) = [];
end

dt_mean    = mean(dt_comp, 1, 'omitnan');
head_scrn  = head_txt{1};
fprintf('%s\n', head_scrn);
fprintf('%s\t%.3f\t%.0f\t%.0f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\n', ...
    nameInt, dt_mean(1), dt_mean(2), dt_mean(3), dt_mean(4), dt_mean(5), dt_mean(6), ...
    dt_mean(7), dt_mean(8), dt_mean(9), dt_mean(10), dt_mean(11), dt_mean(12), dt_mean(13));

toc
disp('--- Variables in workspace ---');
whos
end


% =========================================================================
% LOCAL HELPER FUNCTIONS
% =========================================================================

function vals = collect_normalized_tile_intensity(imagePath, useROI, cmsk, rmsk, windowSize, tileFracThresh, rotChoice, userAngle)
% Collect per-tile mean SHG intensities from a control image, normalized
% by the image median. Used to set the low-SHG threshold.

img_init = imread(imagePath);
img_orig = img_init(:,:,end);
clear img_init

img_rot      = apply_user_rotation(img_orig, rotChoice, userAngle);
validSupport = rotated_support_mask(size(img_orig), rotChoice, userAngle);

if useROI
    BW_orig = roipoly(img_orig, cmsk, rmsk);
    BW      = apply_user_rotation(BW_orig, rotChoice, userAngle);
    BW      = logical(center_crop_or_pad(BW, size(img_rot), false));
    BW      = BW & validSupport;
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
% Normalize tile intensity values by the image median.

valsNorm = vals;
valid    = isfinite(valsNorm) & valsNorm > 0;
if ~any(valid)
    return;
end

scaleVal = median(valsNorm(valid));
if ~isfinite(scaleVal) || scaleVal <= 0
    return;
end

valsNorm(valid) = valsNorm(valid) ./ scaleVal;
end


function BW = rotated_support_mask(inSize, rotChoice, userAngle)
% Returns a logical mask of valid (non-zero-padded) pixels after rotation.

BW = apply_user_rotation(true(inSize), rotChoice, userAngle);
BW = logical(BW);
end


function Irot = apply_user_rotation(I, rotChoice, userAngle)
% Rotate image according to the user's choice.

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
% Reverse the rotation applied by apply_user_rotation, cropping/padding
% the result to match outSize.

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
% Crop or zero-pad I to match outSize, centered.
% Used only for undo_user_rotation with 'User angle' to restore original size.

if nargin < 3
    fillValue = 0;
end

out = zeros(outSize, 'like', I);
if fillValue ~= 0
    out(:) = cast(fillValue, 'like', I);
end

inSize = size(I);
r      = min(inSize(1), outSize(1));
c      = min(inSize(2), outSize(2));

srcR1  = floor((inSize(1) - r) / 2) + 1;
srcC1  = floor((inSize(2) - c) / 2) + 1;
dstR1  = floor((outSize(1) - r) / 2) + 1;
dstC1  = floor((outSize(2) - c) / 2) + 1;

out(dstR1:dstR1+r-1, dstC1:dstC1+c-1) = I(srcR1:srcR1+r-1, srcC1:srcC1+c-1);
end


function hFig = create_roi_figure()
% Create a maximized figure window for ROI selection.

hFig = figure('Units', 'normalized', 'Position', [0.05 0.05 0.9 0.85], ...
    'Color', 'w', 'Name', 'ROI Selection', 'NumberTitle', 'off');
try
    set(hFig, 'WindowState', 'maximized');
catch
end
end


function ax = show_roi_image(hFig, img)
% Display image in the ROI selection figure.

ax = axes('Parent', hFig, 'Position', [0.03 0.06 0.94 0.9]);
imshow(img, [], 'Parent', ax, 'InitialMagnification', 'fit');
axis(ax, 'image');
axis(ax, 'tight');
end