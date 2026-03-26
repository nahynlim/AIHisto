function [] = FFT_align_msk_SHG_controlRef_singleOrBatch()

tic

% =========================================================
% Parallel pool
% =========================================================
try
    p = gcp('nocreate');
    if isempty(p)
        parpool;
    end
catch
    warning('Could not start parallel pool. Continuing anyway.');
end

clearvars -except inipth;
close all;

% =========================================================
% Initial folder
% =========================================================
if (~exist('inipth','var') || isequal(inipth,0))
    inipth = 'C:\Users\Spence\Documents\CloudStation';
end

% =========================================================
% User picks any file in the folder
% =========================================================
[fnm, pth] = uigetfile('*.tif', 'Select any TIFF image in the folder', inipth);
if isequal(fnm,0)
    uiwait(warndlg('No file selected.'));
    return;
end
inipth = pth;

% =========================================================
% Collect all TIFFs, keep only SHG = channel 0000
% =========================================================
Sdir = dir(fullfile(pth, '*.tif'));
allNames = {Sdir.name};

isSHG = endsWith(allNames, '_0000.tif');
Sdir = Sdir(isSHG);
fnames = {Sdir.name};

if isempty(fnames)
    errordlg('No SHG images ending in _0000.tif were found in this folder.');
    return;
end

allSHGFiles = cell(length(fnames),1);
for i = 1:length(fnames)
    allSHGFiles{i} = fullfile(pth, fnames{i});
end

allSHGNames = cell(length(allSHGFiles),1);
for i = 1:length(allSHGFiles)
    [~, allSHGNames{i}] = fileparts(allSHGFiles{i});
end

fprintf('\n--- SHG images detected (channel 0000 only) ---\n');
disp(allSHGNames);

% =========================================================
% Auto-detect Control / Injured from ALL SHG filenames
% Control example: ..._3L_..._0000.tif
% Injured example: ..._3R_..._0000.tif
% =========================================================
allGroupLabel = cell(length(allSHGNames),1);
allGroupLabel(:) = {'Other'};

ctrl_idx_all = [];
inj_idx_all = [];

for i = 1:length(allSHGNames)
    thisName = lower(allSHGNames{i});

    isControl = ~isempty(regexp(thisName, '(^|_)\d+l(_|$)', 'once'));
    isInjured = ~isempty(regexp(thisName, '(^|_)\d+r(_|$)', 'once'));

    if isControl
        ctrl_idx_all(end+1) = i; %#ok<AGROW>
        allGroupLabel{i} = 'Control';
    elseif isInjured
        inj_idx_all(end+1) = i; %#ok<AGROW>
        allGroupLabel{i} = 'Injured';
    else
        allGroupLabel{i} = 'Other';
    end
end

fprintf('\n--- Auto-detected groups from SHG filenames ---\n');
fprintf('Controls detected: %d\n', numel(ctrl_idx_all));
fprintf('Injured detected: %d\n', numel(inj_idx_all));

if ~isempty(ctrl_idx_all)
    fprintf('Control SHG files:\n');
    disp(allSHGNames(ctrl_idx_all));
end

if ~isempty(inj_idx_all)
    fprintf('Injured SHG files:\n');
    disp(allSHGNames(inj_idx_all));
end

if isempty(ctrl_idx_all)
    errordlg(['No control SHG images were auto-detected. ', ...
              'Expected filenames containing patterns like 3L.']);
    return;
end

% =========================================================
% Choose analysis mode: one image or all images
% =========================================================
analysisMode = questdlg( ...
    'Would you like to analyze one SHG image or all SHG images?', ...
    'Analysis Mode', ...
    'One image', 'All images', 'All images');

if isempty(analysisMode)
    return;
end

if strcmp(analysisMode, 'One image')
    one_idx = listdlg( ...
        'PromptString', 'Select ONE SHG image to analyze', ...
        'SelectionMode', 'Single', ...
        'Name', 'Choose SHG Image', ...
        'ListString', allSHGNames, ...
        'ListSize', [350 450]);

    if isempty(one_idx)
        errordlg('You must select one image to analyze.');
        return;
    end

    filename = allSHGFiles(one_idx);
    rfnm = allSHGNames(one_idx);
    groupLabel = allGroupLabel(one_idx);
else
    filename = allSHGFiles;
    rfnm = allSHGNames;
    groupLabel = allGroupLabel;
end

fprintf('\n--- Images selected for analysis ---\n');
disp(rfnm);

% =========================================================
% User options
% =========================================================
maskChoice = questdlg('Do you need to create an ROI mask?', ...
    'Masking option', ...
    'That sounds great', 'Already did', 'What?', 'That sounds great');

enhanceChoice = questdlg('Sharpen and enhance all images?', ...
    'Image Enhancement', 'Yes', 'No', 'Woof', 'Yes');

dlg_title = 'Input Window Size Parameters';
prompt = {'Enter Bundle Width (pixels):', 'Enter Bundle Height (pixels):'};
defAns = {'15', '15'};
answer1 = inputdlg(prompt, dlg_title, 1, defAns);
if isempty(answer1)
    return;
end
windowSize = [str2double(answer1{1}), str2double(answer1{2})];

damagePrompt = { ...
    'Enter FFT angular damage threshold (degrees):', ...
    'Enter minimum valid ROI tile fraction (0-1):'};
damageDef = {'15', '0.75'};
answer2 = inputdlg(damagePrompt, 'Mask Parameters', 1, damageDef);
if isempty(answer2)
    return;
end
DamThresh = str2double(answer2{1});
minTileFrac = str2double(answer2{2});

rotChoice = questdlg('How should the fibers be oriented before analysis?', ...
    'Image Orientation', ...
    'Vertical', 'Horizontal', 'Diagonal', 'Vertical');
if isempty(rotChoice)
    return;
end

diagAngle = 45;
if strcmp(rotChoice, 'Diagonal')
    angAns = inputdlg({'Enter diagonal rotation angle in degrees (e.g. 45 or -45):'}, ...
        'Diagonal Angle', 1, {'45'});
    if isempty(angAns)
        return;
    end
    diagAngle = str2double(angAns{1});
end

saveChoice = questdlg('Would you like to save your figures?', ...
    'Save Figures', 'Yes', 'No', 'I''m not sure', 'Yes');

% =========================================================
% Control threshold method
% =========================================================
ctrlThreshMethod = questdlg( ...
    'Choose control-referenced threshold method for SHG intensity mask', ...
    'Control Threshold Method', ...
    'Percentile', 'Median-MAD', 'Median-MAD');

if isempty(ctrlThreshMethod)
    return;
end

ctrlPct = [];
ctrlMADk = [];

if strcmp(ctrlThreshMethod, 'Percentile')
    ansCtrl = inputdlg({'Enter control percentile (e.g. 20):'}, ...
        'Control Percentile Threshold', 1, {'20'});
    if isempty(ansCtrl)
        return;
    end
    ctrlPct = str2double(ansCtrl{1});
else
    ansCtrl = inputdlg({'Enter MAD multiplier k for median - k*MAD:'}, ...
        'Control Median-MAD Threshold', 1, {'1.5'});
    if isempty(ansCtrl)
        return;
    end
    ctrlMADk = str2double(ansCtrl{1});
end

% =========================================================
% Output setup
% =========================================================
h1 = waitbar(0, 'Preparing analysis...');

nameInt = rfnm{1};
[fnm2, pth2] = uiputfile([nameInt '_SHGstats.txt'], ...
    'Choose Collagen Fiber Organization Output File');
if isequal(fnm2,0)
    warndlg('Not Saving Data');
    return;
end
SHGcircstats = fullfile(pth2, fnm2);

maskDir = fullfile(pth2, 'Exported_Masks');
figDir = fullfile(pth2, 'Figures');

if ~exist(maskDir, 'dir')
    mkdir(maskDir);
end
if ~exist(figDir, 'dir')
    mkdir(figDir);
end

% =========================================================
% Draw ROI on first selected analysis image
% =========================================================
if strcmp(maskChoice, 'That sounds great')
    pout_draw_full = imread(filename{1});
    pout_draw = pout_draw_full(:,:,end);
    pout_draw = apply_user_rotation(pout_draw, rotChoice, diagAngle);

    figure;
    imshow(pout_draw, []);
    title('Draw ROI on rotated image');
    uiwait(msgbox('Draw border around the ROI'));
    hold on;

    Hply = impoly;
    poly_pos = wait(Hply);
    delete(Hply);

    plot(poly_pos([1:end,1],1), poly_pos([1:end,1],2), 'r+-');

    cmsk = poly_pos(:,1);
    rmsk = poly_pos(:,2);
end

% =========================================================
% Build one global control-referenced SHG threshold
% from ALL control SHG images in the folder
% =========================================================
waitbar(0.05, h1, 'Computing control-referenced SHG threshold...');
controlVals = [];

for cc = 1:length(ctrl_idx_all)

    cfile = allSHGFiles{ctrl_idx_all(cc)};
    cimg_init = imread(cfile);
    cimg = cimg_init(:,:,end);
    clear cimg_init

    cimg = apply_user_rotation(cimg, rotChoice, diagAngle);

    if strcmp(maskChoice, 'That sounds great')
        BW4_ctrl = roipoly(cimg, cmsk, rmsk);
        cimg_mask = maskout(cimg, BW4_ctrl);
    else
        BW4_ctrl = true(size(cimg));
        cimg_mask = cimg;
    end

    if strcmp(enhanceChoice, 'Yes')
        cimg_adj = imadjust(cimg_mask);
        thresh_ctrl = graythresh(cimg_adj);
        cimg_proc = imsharpen(cimg_adj, 'Threshold', thresh_ctrl);
    else
        cimg_proc = cimg_mask;
    end

    cimg_tiles = mat2tiles(cimg_proc, windowSize);
    BW_ctrl_tiles = mat2tiles(BW4_ctrl, windowSize);
    tileSize = windowSize(1) * windowSize(2);

    tileMeanIntensity_ctrl = nan(size(cimg_tiles));

    for ii = 1:numel(cimg_tiles)
        thisTile = cimg_tiles{ii};
        thisROITile = BW_ctrl_tiles{ii};

        if sum(thisROITile(:)) < minTileFrac * tileSize
            continue
        end

        roiPix = double(thisTile(thisROITile > 0));
        if ~isempty(roiPix)
            tileMeanIntensity_ctrl(ii) = mean(roiPix);
        end
    end

    validCtrlVals = tileMeanIntensity_ctrl(~isnan(tileMeanIntensity_ctrl));
    controlVals = [controlVals; validCtrlVals(:)]; %#ok<AGROW>
end

if isempty(controlVals)
    errordlg('No valid control ROI tiles were found. Cannot compute control-referenced threshold.');
    return;
end

switch ctrlThreshMethod
    case 'Percentile'
        intensityThresh_global = prctile(controlVals, ctrlPct);
        thresholdInfo = sprintf('%% Control-referenced SHG threshold (%s %.2f) = %.6f', ...
            ctrlThreshMethod, ctrlPct, intensityThresh_global);

    case 'Median-MAD'
        intensityThresh_global = median(controlVals) - ctrlMADk * mad(controlVals,1);
        thresholdInfo = sprintf('%% Control-referenced SHG threshold (%s k=%.2f) = %.6f', ...
            ctrlThreshMethod, ctrlMADk, intensityThresh_global);

    otherwise
        intensityThresh_global = prctile(controlVals, 20);
        thresholdInfo = sprintf('%% Control-referenced SHG threshold (Percentile 20) = %.6f', ...
            intensityThresh_global);
end

fprintf('\n--- Control-referenced SHG threshold ---\n');
fprintf('%s\n', thresholdInfo);
fprintf('Number of pooled control tiles: %d\n\n', numel(controlVals));

% =========================================================
% Preallocate
% =========================================================
nFiles = length(filename);

ang_var = nan(nFiles,3);
ang_dev = nan(nFiles,2);
ang_var_noDam = nan(nFiles,3);
ang_dev_noDam = nan(nFiles,2);

PercDam = nan(nFiles,1);
N_total = nan(nFiles,1);
pixArea_all = nan(nFiles,1);

% =========================================================
% Main analysis loop
% =========================================================
for jj = 1:nFiles

    waitbar(jj/nFiles, h1, sprintf('Analyzing image %d of %d...', jj, nFiles));

    pout_init = imread(filename{jj});
    pout = pout_init(:,:,end);
    clear pout_init

    pout = apply_user_rotation(pout, rotChoice, diagAngle);

    % ROI
    if strcmp(maskChoice, 'That sounds great')
        BW4 = roipoly(pout, cmsk, rmsk);
        pout_mask = maskout(pout, BW4);
        pixArea = bwarea(BW4);
    else
        BW4 = true(size(pout));
        pout_mask = pout;
        pixArea = numel(pout);
    end
    pixArea_all(jj) = pixArea;

    % Enhancement
    if strcmp(enhanceChoice, 'Yes')
        pout_imadjust = imadjust(pout_mask);
        thresh = graythresh(pout_imadjust);
        pout_sharp = imsharpen(pout_imadjust, 'Threshold', thresh);
    else
        pout_sharp = pout_mask;
    end

    % Tiling
    pout_tiles = mat2tiles(pout_sharp, windowSize);
    BW_tiles = mat2tiles(BW4, windowSize);
    tileSize = windowSize(1) * windowSize(2);

    [nRows, nCols] = size(pout_tiles);

    % Tile center coordinates
    xCenters = (0:nCols-1) * windowSize(2) + (windowSize(2)+1)/2;
    yCenters = (0:nRows-1) * windowSize(1) + (windowSize(1)+1)/2;
    [x, y] = meshgrid(xCenters, yCenters);

    ellipse_orient = cell(size(pout_tiles));
    Eccent = nan(size(pout_tiles));
    tileMeanIntensity = nan(size(pout_tiles));

    imageTileSize = numel(pout_tiles);

    parfor ii = 1:imageTileSize

        thisTile = pout_tiles{ii};
        thisROITile = BW_tiles{ii};

        if sum(thisROITile(:)) < minTileFrac * tileSize
            ellipse_orient{ii} = NaN;
            Eccent(ii) = NaN;
            tileMeanIntensity(ii) = NaN;
            continue
        end

        roiPix = double(thisTile(thisROITile > 0));
        if isempty(roiPix)
            tileMeanIntensity(ii) = NaN;
        else
            tileMeanIntensity(ii) = mean(roiPix);
        end

        transforms = fftshift(abs(fft2(thisTile)));
        normTransform = log(transforms + 1);
        h = ones(3,3) / 9;
        filtTransform = imfilter(normTransform, h);

        grayTransform = mat2gray(filtTransform);
        top10 = quantile(grayTransform(:), 0.90);
        ellipses = imbinarize(grayTransform, top10);
        BWellipse = bwareaopen(ellipses, 12);

        CC = bwconncomp(BWellipse);
        if CC.NumObjects == 1
            S = regionprops(BWellipse, 'Orientation', 'Eccentricity');
        else
            BWellipse = BWellipse * 2;
            S = regionprops(BWellipse, 'Orientation', 'Eccentricity');
            if isempty(S)
                ellipse_orient{ii} = NaN;
                Eccent(ii) = 0;
                continue
            end
            S(1) = [];
        end

        if isempty(S)
            ellipse_orient{ii} = NaN;
            Eccent(ii) = NaN;
        else
            ellipse_orient{ii} = S(1).Orientation;
            Eccent(ii) = S(1).Eccentricity;
        end
    end

    % Fiber angles
    ellipseAngles = cell2mat(ellipse_orient);
    fiberAngles = ellipseAngles + 90;
    fiberAngles(fiberAngles > 90) = fiberAngles(fiberAngles > 90) - 180;

    Badinds = find(Eccent < 0.85);
    fiberAngles(Badinds) = NaN;

    Tinds = find(~isnan(fiberAngles));
    N_total(jj) = numel(Tinds);

    fprintf('Image %d: valid fiber-angle tiles = %d\n', jj, sum(~isnan(fiberAngles(:))));

    % Neighbor differences
    tempL = cat(2, nan(size(fiberAngles,1),1), fiberAngles(:,1:end-1));
    diffL = abs(fiberAngles - tempL);

    tempR = cat(2, fiberAngles(:,2:end), nan(size(fiberAngles,1),1));
    diffR = abs(fiberAngles - tempR);

    % FFT damage
    Daminds = find(diffL > DamThresh | diffR > DamThresh | Eccent < 0.90);

    BW_fft_damage = false(size(BW4));
    for i = 1:length(Daminds)
        [I,J] = ind2sub(size(Eccent), Daminds(i));
        r1 = (I-1)*windowSize(1) + 1;
        r2 = min(I*windowSize(1), size(BW_fft_damage,1));
        c1 = (J-1)*windowSize(2) + 1;
        c2 = min(J*windowSize(2), size(BW_fft_damage,2));
        BW_fft_damage(r1:r2, c1:c2) = true;
    end
    BW_fft_damage = BW_fft_damage & BW4;
    BW_fft_organized = BW4 & ~BW_fft_damage;

    PercDam(jj) = length(Daminds) / max(length(Tinds),1);

    % SHG low mask
    lowIntensityTile = tileMeanIntensity < intensityThresh_global;

    BW_shg_low = false(size(BW4));
    indsInt = find(lowIntensityTile);
    for i = 1:numel(indsInt)
        [I,J] = ind2sub(size(lowIntensityTile), indsInt(i));
        r1 = (I-1)*windowSize(1) + 1;
        r2 = min(I*windowSize(1), size(BW_shg_low,1));
        c1 = (J-1)*windowSize(2) + 1;
        c2 = min(J*windowSize(2), size(BW_shg_low,2));
        BW_shg_low(r1:r2, c1:c2) = true;
    end
    BW_shg_low = BW_shg_low & BW4;
    BW_shg_high = BW4 & ~BW_shg_low;

    % Combined masks
    BW_combined_injured = BW_fft_damage & BW_shg_low;
    BW_combined_healthy = BW_fft_organized & BW_shg_high;

    % Export masks
    baseName = rfnm{jj};
    imwrite(uint8(BW_fft_damage)*255, fullfile(maskDir, [baseName '_FFT_damageMask.tif']));
    imwrite(uint8(BW_fft_organized)*255, fullfile(maskDir, [baseName '_FFT_inverseMask.tif']));
    imwrite(uint8(BW_shg_low)*255, fullfile(maskDir, [baseName '_SHGlowMask.tif']));
    imwrite(uint8(BW_shg_high)*255, fullfile(maskDir, [baseName '_SHGhigh_inverseMask.tif']));
    imwrite(uint8(BW_combined_injured)*255, fullfile(maskDir, [baseName '_Combined_injuredMask.tif']));
    imwrite(uint8(BW_combined_healthy)*255, fullfile(maskDir, [baseName '_Combined_healthyMask.tif']));

    % Angle export
    arrowLength = 15;
    u = arrowLength*cosd(fiberAngles);
    v = -arrowLength*sind(fiberAngles);

    theta_mat = fiberAngles;
    [y_pos, x_pos] = ind2sub(size(theta_mat), 1:numel(theta_mat));
    x_pos = x_pos';
    y_pos = y_pos';

    theta = reshape(theta_mat, [], 1);
    theta_noDam = theta;
    theta_noDam(Daminds) = NaN;

    theta_stats = theta(~isnan(theta));
    theta_noDam_stats = theta_noDam(~isnan(theta_noDam));

    pixScale = 1024 / 276.79;
    write_angles(theta, rfnm{jj}, pth2, windowSize, x_pos, y_pos, pixArea, pixScale);

    % Quiver plot
    qPlot = figure;
    imshow(pout_sharp, []);
    hold on;
    if ~isempty(Tinds)
        q = quiver(x(Tinds), y(Tinds), u(Tinds), v(Tinds), ...
            'ShowArrowHead', 'on', 'AutoScale', 'off');
        set(q, 'Color', 'g', 'LineWidth', 1);
    end
    if ~isempty(Daminds)
        q2 = quiver(x(Daminds), y(Daminds), u(Daminds), v(Daminds), ...
            'ShowArrowHead', 'on', 'AutoScale', 'off');
        set(q2, 'Color', 'r', 'LineWidth', 1);
    end
    if ~isempty(Badinds)
        q3 = quiver(x(Badinds), y(Badinds), u(Badinds), v(Badinds), ...
            'ShowArrowHead', 'on', 'AutoScale', 'off');
        set(q3, 'Color', 'y', 'LineWidth', 1);
    end
    title(sprintf('%s - FFT fiber organization', baseName));
    hold off;

    % Histogram
    histFig = figure;
    numBins = 25;
    if ~isempty(theta_stats) && (sum(~isnan(theta))/numel(theta)) > 0.05
        histfit(theta_stats, numBins);
    else
        histogram([]);
    end
    title('Angular Frequency');
    xlabel('Angle (degrees)');
    ylabel('Angular Frequency');

    % Overlay figure
    overlayFig = figure;
    imshow(pout_sharp, []);
    hold on;
    visboundaries(BW_fft_damage, 'Color', 'r', 'LineWidth', 0.5);
    visboundaries(BW_shg_low, 'Color', 'b', 'LineWidth', 0.5);
    visboundaries(BW_combined_injured, 'Color', 'y', 'LineWidth', 1);
    title(sprintf('%s | Red=FFT damage | Blue=Low SHG | Yellow=Combined injured', baseName));
    hold off;

    % Debug figure: quiver + mask together
    debugFig = figure;
    imshow(pout_sharp, []);
    hold on;
    visboundaries(BW_fft_damage, 'Color', 'r', 'LineWidth', 0.5);
    if ~isempty(Tinds)
        qd = quiver(x(Tinds), y(Tinds), u(Tinds), v(Tinds), ...
            'ShowArrowHead', 'on', 'AutoScale', 'off');
        set(qd, 'Color', 'g', 'LineWidth', 1);
    end
    if ~isempty(Daminds)
        qd2 = quiver(x(Daminds), y(Daminds), u(Daminds), v(Daminds), ...
            'ShowArrowHead', 'on', 'AutoScale', 'off');
        set(qd2, 'Color', 'y', 'LineWidth', 1.2);
    end
    title(sprintf('%s | red mask = FFT damage | yellow arrows = damaged tiles', baseName));
    hold off;

    if strcmp(saveChoice, 'Yes')
        saveas(qPlot, fullfile(figDir, [baseName '_quiver.tiff']));
        saveas(histFig, fullfile(figDir, [baseName '_hist.tiff']));
        saveas(overlayFig, fullfile(figDir, [baseName '_maskOverlay.tiff']));
        saveas(debugFig, fullfile(figDir, [baseName '_debug_quiverMask.tiff']));
    end

    % Circular stats
    if ~isempty(theta_stats)
        [ang_var(jj,:), ang_dev(jj,:)] = circ_disp(theta_stats);
    end
    if ~isempty(theta_noDam_stats)
        [ang_var_noDam(jj,:), ang_dev_noDam(jj,:)] = circ_disp(theta_noDam_stats);
    end

  % Leave figures open so user can inspect them
drawnow;
end

close(h1);

% =========================================================
% Report
% =========================================================
head_txt = {
    '%Sample Name	Group	N_good (%)	N_total (#)	Cropped Area (pix)	Cir-Var (rad^2)	Ang-Var (rad^2)	Standard-Var (rad^2)	Ang-Dev(deg)	Cir-Dev (deg)	Cir-Var_noDam (rad^2)	Ang-Var_noDam (rad^2)	Standard-Var_noDam (rad^2)	Ang-Dev_noDam (deg)	Cir-Dev_noDam (deg)'
};

circularVariance = ang_var(:,1);
angularVariance = ang_var(:,2);
standardVariance = ang_var(:,3);

angularDeviation = ang_dev(:,1);
circularDeviation = ang_dev(:,2);

circularVariance_noDam = ang_var_noDam(:,1);
angularVariance_noDam = ang_var_noDam(:,2);
standardVariance_noDam = ang_var_noDam(:,3);

angularDeviation_noDam = ang_dev_noDam(:,1);
circularDeviation_noDam = ang_dev_noDam(:,2);

N_good = 100 - (100 * PercDam);

dataLines = cell(length(filename),1);
for ij = 1:length(filename)
    dataLines{ij} = sprintf('%s\t%s\t%.3f\t%d\t%d\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f', ...
        rfnm{ij}, groupLabel{ij}, N_good(ij), N_total(ij), round(pixArea_all(ij)), ...
        circularVariance(ij), angularVariance(ij), standardVariance(ij), ...
        angularDeviation(ij), circularDeviation(ij), ...
        circularVariance_noDam(ij), angularVariance_noDam(ij), standardVariance_noDam(ij), ...
        angularDeviation_noDam(ij), circularDeviation_noDam(ij));
end

report_text = [{thresholdInfo}; head_txt; dataLines];
write_report(report_text, SHGcircstats);

% =========================================================
% Mean summary for images with <= 50% damage excluded
% =========================================================
inc = N_good > 50;
dt_comp = [N_good(inc), N_total(inc), pixArea_all(inc), ...
    circularVariance(inc), angularVariance(inc), standardVariance(inc), ...
    angularDeviation(inc), circularDeviation(inc), ...
    circularVariance_noDam(inc), angularVariance_noDam(inc), standardVariance_noDam(inc), ...
    angularDeviation_noDam(inc), circularDeviation_noDam(inc)];

if ~isempty(dt_comp)
    dt_mean = nan(1, size(dt_comp,2));
    for kk = 1:size(dt_comp,2)
        col = dt_comp(:,kk);
        dt_mean(kk) = mean(col(~isnan(col)));
    end

    head_scrn = '%Sample Name	N_good (%)	N_total (#)	Cropped Area (pix)	Cir-Var (rad^2)	Ang-Var (rad^2)	Standard-Var (rad^2)	Ang-Dev(deg)	Cir-Dev (deg)	Cir-Var_noDam (rad^2)	Ang-Var_noDam (rad^2)	Standard-Var_noDam (rad^2)	Ang-Dev_noDam (deg)	Cir-Dev_noDam (deg)';
    fprintf('%s\n', head_scrn);
    fprintf('%s\t%.3f\t%.0f\t%.0f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\n', ...
        nameInt, dt_mean(1), dt_mean(2), dt_mean(3), dt_mean(4), dt_mean(5), dt_mean(6), ...
        dt_mean(7), dt_mean(8), dt_mean(9), dt_mean(10), dt_mean(11), dt_mean(12), dt_mean(13));
end

toc
disp('--- Variables in workspace ---');
whos

end

% =========================================================
% Helper: image rotation
% =========================================================
function Irot = apply_user_rotation(I, rotChoice, diagAngle)

switch rotChoice
    case 'Vertical'
        Irot = I;
    case 'Horizontal'
        Irot = imrotate(I, 90, 'bilinear', 'crop');
    case 'Diagonal'
        Irot = imrotate(I, -diagAngle, 'bilinear', 'crop');
    otherwise
        Irot = I;
end

end