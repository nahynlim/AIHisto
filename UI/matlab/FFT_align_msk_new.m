function [] = FFT_align_msk_new()
% FFT_align_msk (UPDATED)
% Adds: circular angle differences, 4/8-neighbor coherence check,
% eccentricity as confidence gating (Good vs Unknown), optional spatial cleanup,


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
DamThreshDeg   = 15;     % (deg) neighbor angle discontinuity threshold
EccMin         = 0.80;   % eccentricity >= EccMin => reliable orientation
Use8Neighbor   = false;  % true = 8-neighbor; false = 4-neighbor
SaveUnknownMask = true;  % save BWunknown mask (low-confidence tiles)
DoSpatialCleanup = true; % apply small morphological cleanup to BWdam
MinDamObjPixels = 3*15;  % min object size in pixels for BWdam cleanup (scaled later)

% Circular (wrap-safe) angular difference (deg)
circDiff = @(a,b) abs(atan2d(sind(a-b), cosd(a-b)));

% ==========================
% UI + SETUP (unchanged)
% ==========================
if (~exist('inipth','var') || inipth==0)
    inipth='C:\Users\Spence\Documents\CloudStation';
end

[fnm, pth] = uigetfile('*.tif', 'Select image to analyze',inipth);
inipth=pth;
if (fnm == 0)
    uiwait(warndlg('You''re doing it wrong!'));
    return;
end

if strcmp(fnm(1),'c')
    Sdir = dir(fullfile(pth,'*c000.tif'));
else
    Sdir = dir(fullfile(pth,'*.tif'));
end
fnames = {Sdir.name};

sr_v = listdlg('PromptString', 'Choose SHG channel images', ...
    'SelectionMode', 'Multiple', 'Name', '.tif SHG collagen images', ...
    'InitialValue', 1:min(2,length(fnames)), 'ListString', fnames, 'Listsize',[300 400]);
if isempty(sr_v)
    uiwait(warndlg('OOPS! There doesn''t seem to be anything here!'));
    return;
end

filename = cell(length(sr_v),1);
for i=1:length(sr_v)
    filename{i} = fullfile(pth, fnames{sr_v(i)});
end

maskChoice = questdlg('Do you need to create a mask?', 'Masking option', ...
    'That sounds great', 'Already did', 'What?', 'That sounds great');

ang_var = zeros(length(filename),3);
ang_dev = zeros(length(filename),2);
ang_var_noDam = zeros(length(filename),3);
ang_dev_noDam = zeros(length(filename),2);

enhanceChoice = questdlg('Sharpen and enhance all images?', 'Image Enhancement', ...
    'Yes', 'No','unsure', 'Yes');

answer1 = inputdlg({'Enter Bundle Width (pixels):', 'Enter Bundle height (pixels):'}, ...
    'Input Window Size Parameters', 1, {'15', '15'});
windowSize = [str2double(answer1{1}), str2double(answer1{2})];

saveChoice = questdlg('Would you like to save your figures?', 'Save Figures', ...
    'Yes','No','I''m not sure','Yes');

h1 = waitbar(0,'Analyzing images...');

rfnm = cell(length(filename),1);
for k = 1:length(filename)
    [~,rfnm{k}] = fileparts(filename{k});
end

nameInt = rfnm{1};
[fnm2,pth2] = uiputfile([nameInt,'_SHGstats.txt'], 'Choose Collagen Fiber Organization Output File');
if (fnm2==0)
    warndlg('Not Saving Data');
    return;
end
SHGcircstats = fullfile(pth2,fnm2);

% ==========================
% ROI MASK (unchanged logic)
% ==========================
if strcmp(maskChoice,'That sounds great')
    pout_draw = imread(filename{1});
    figure; imshow(pout_draw, []);
    uiwait(msgbox('Draw border around the ROI'));
    Hply = impoly;
    poly_pos = wait(Hply);
    delete(Hply);
    hold on
    plot(poly_pos([1:end,1],1), poly_pos([1:end,1],2),'r+-');
    cmsk = poly_pos(:,1);
    rmsk = poly_pos(:,2);

    BWroi = roipoly(pout_draw(:,:,end), cmsk, rmsk);
    roiOut = fullfile(pth2, [rfnm{1} '_ROI.tif']);
    imwrite(uint8(BWroi)*255, roiOut);
else
    BWroi = [];
end

PercDam = zeros(length(filename),1);
N_total = zeros(length(filename),1);

% ==========================
% OPEN SUMMARY FILE
% ==========================
summaryFile = fullfile(pth2, 'SHG_damage_summary.txt');
fid = fopen(summaryFile, 'w');

fprintf(fid, 'Sample\tGoodTiles\tDamTiles\tUnknownTiles\tDamFrac\tCV_all\tCV_noDam\tDeltaCV\n');


% ==========================
% MAIN LOOP
% ==========================
for jj = 1:length(filename)
    waitbar(jj/length(filename), h1);

    pout_init = imread(filename{jj});
    pout = pout_init(:,:,end);
    clear pout_init

    if strcmp(maskChoice,'That sounds great')
        BW4 = roipoly(pout, cmsk, rmsk);
        pout_mask = maskout(pout,BW4);
        pixArea = bwarea(BW4);
    else
        BW4 = ones(size(pout));
        pout_mask = pout;
        pixArea = numel(pout);
    end

    if strcmp(enhanceChoice,'Yes')
        pout_imadjust = imadjust(pout_mask);
        thresh = graythresh(pout_imadjust);
        pout_sharp = imsharpen(pout_imadjust, 'Threshold',thresh);
    else
        pout_sharp = pout_mask;
    end
    clear pout pout_imadjust

    % Tile SHG and ROI
    pout_tiles = mat2tiles(pout_sharp, windowSize);
    BW_tiles   = mat2tiles(BW4, windowSize);
    tileSize   = windowSize(1)*windowSize(2);

    imageDim = size(pout_sharp);

    % Build quiver grid (keep your existing logic)
    X = 0:windowSize(2):imageDim(2);
    if length(X) < size(BW_tiles,2)
        X = cat(2,X,X(end)+windowSize(2));
    end
    Y = windowSize(1)/2:windowSize(2):imageDim(1);
    if length(Y) < size(BW_tiles,1)
        Y = cat(2,Y,Y(end)+windowSize(1));
    end
    [x, y] = meshgrid(X,Y);

    ellipse_orient = cell(size(pout_tiles));
    Eccent = nan(size(pout_tiles));

    imageTileSize = numel(pout_tiles);

    % ==========================
    % FFT ORIENTATION PER TILE
    % ==========================
    parfor ii = 1:imageTileSize
        if sum(BW_tiles{ii}(:)) < 0.75*tileSize
            ellipse_orient{ii} = NaN;
            Eccent(ii)=NaN;
            continue
        end

        transforms = fftshift(abs(fft2(pout_tiles{ii})));
        normTransform = log(transforms + 1);

        h = ones(3,3)/9;
        filtTransform = imfilter(normTransform, h);
        grayT = mat2gray(filtTransform);

        top10 = quantile(grayT(:), 0.90);
        ell = imbinarize(grayT, top10);
        ell = bwareaopen(ell, 12);

        CC = bwconncomp(ell);
        if CC.NumObjects == 1
            S = regionprops(ell,'orientation','eccentricity');
        else
            ell2 = ell*2;
            S = regionprops(ell2,'orientation','eccentricity');
            if isempty(S)
                ellipse_orient{ii} = NaN;
                Eccent(ii)=0;
                continue
            end
            S(1) = []; % drop merged component heuristic (keeps original behavior)
        end

        ellipse_orient{ii} = S.Orientation;
        Eccent(ii) = S.Eccentricity;
    end

    % ==========================
    % TILE ANGLES
    % ==========================
    ellipseAngles = cell2mat(ellipse_orient);            % tile grid
    fiberAngles = ellipseAngles + 90;                    % convert FFT ellipse axis to fiber direction
    fiberAngles(fiberAngles > 90) = fiberAngles(fiberAngles > 90) - 180; % keep in [-90,90]

    % Valid tile definition (inside ROI, FFT computed)
    ValidTile = ~isnan(fiberAngles) & ~isnan(Eccent);

    % Confidence split by eccentricity
    UnknownTile = ValidTile & (Eccent < EccMin);         % low-confidence orientation
    GoodTile    = ValidTile & (Eccent >= EccMin);        % reliable orientation

    % N_total based on all valid tiles (or just GoodTile — pick one; PI often prefers GoodTile)
    N_total(jj) = nnz(GoodTile);

    % ==========================
    % DAMAGE DETECTION (OPTIMIZED)
    % - wrap-safe circular diffs
    % - 4/8-neighbor comparisons
    % - only on GoodTile
    % ==========================
    [nRows, nCols] = size(fiberAngles);
    DamTile = false(nRows, nCols);

    for r = 1:nRows
        for c = 1:nCols
            if ~GoodTile(r,c)
                continue
            end

            theta = fiberAngles(r,c);

            nbr = [];

            % 4-neighbor
            if r>1   && GoodTile(r-1,c), nbr(end+1) = fiberAngles(r-1,c); end %#ok<AGROW>
            if r<nRows && GoodTile(r+1,c), nbr(end+1) = fiberAngles(r+1,c); end %#ok<AGROW>
            if c>1   && GoodTile(r,c-1), nbr(end+1) = fiberAngles(r,c-1); end %#ok<AGROW>
            if c<nCols && GoodTile(r,c+1), nbr(end+1) = fiberAngles(r,c+1); end %#ok<AGROW>

            if Use8Neighbor
                if r>1 && c>1       && GoodTile(r-1,c-1), nbr(end+1) = fiberAngles(r-1,c-1); end %#ok<AGROW>
                if r>1 && c<nCols   && GoodTile(r-1,c+1), nbr(end+1) = fiberAngles(r-1,c+1); end %#ok<AGROW>
                if r<nRows && c>1   && GoodTile(r+1,c-1), nbr(end+1) = fiberAngles(r+1,c-1); end %#ok<AGROW>
                if r<nRows && c<nCols && GoodTile(r+1,c+1), nbr(end+1) = fiberAngles(r+1,c+1); end %#ok<AGROW>
            end

            if isempty(nbr)
                continue
            end

            diffs = arrayfun(@(t) circDiff(theta, t), nbr);

            if any(diffs > DamThreshDeg)
                DamTile(r,c) = true;
            end
        end
    end

    % Linear indices for quiver coloring (tile grid)
    Daminds     = find(DamTile);
    Unknowninds = find(UnknownTile);
    Goodinds    = find(GoodTile);
    GoodNoDaminds = find(GoodTile & ~DamTile);

    % ==========================
    % EXPAND TILE MASK -> PIXELS
    % ==========================
    BWdam = zeros(size(BW4));
    for ii = 1:numel(Daminds)
        [I,J] = ind2sub(size(DamTile), Daminds(ii));
        BWdam((I-1)*windowSize(1)+1:I*windowSize(1), (J-1)*windowSize(2)+1:J*windowSize(2)) = 1;
    end

    BWunknown = zeros(size(BW4));
    if SaveUnknownMask
        for ii = 1:numel(Unknowninds)
            [I,J] = ind2sub(size(UnknownTile), Unknowninds(ii));
            BWunknown((I-1)*windowSize(1)+1:I*windowSize(1), (J-1)*windowSize(2)+1:J*windowSize(2)) = 1;
        end
    end

    % Optional cleanup (reduce salt-and-pepper)
    if DoSpatialCleanup
        minPx = max(1, MinDamObjPixels * windowSize(1)); % scale by tile height
        BWdam = bwareaopen(logical(BWdam), minPx);
        BWdam = imclose(BWdam, strel('disk',2));
        BWdam = double(BWdam);
        if SaveUnknownMask
            BWunknown = bwareaopen(logical(BWunknown), minPx);
            BWunknown = double(BWunknown);
        end
    end

    % ==========================
    % SAVE MASKS (SAME ORIENTATION AS SHG & DAPI)
    % ==========================
    maskOut = fullfile(pth2, [rfnm{jj} '_BWdam.tif']);
    imwrite(uint8(BWdam)*255, maskOut);

    if SaveUnknownMask
        unkOut = fullfile(pth2, [rfnm{jj} '_BWunknown.tif']);
        imwrite(uint8(BWunknown)*255, unkOut);
    end

    % (If you still need a rotated version for legacy display, do it after saving)
    % BWdam_disp = imrotate(BWdam, -90);

    % Damage percentage: fraction of damaged among "GoodTile"
    PercDam(jj) = nnz(DamTile) / max(1, nnz(GoodTile));

    % ==========================
    % QUIVER (UPDATED COLORS)
    % ==========================
    arrowLength = 15;
    u = arrowLength*cosd(fiberAngles);
    v = -arrowLength*sind(fiberAngles);

    qPlot = figure;
    imshow(pout_sharp, []); hold on;

    % Good tiles (green) including damaged ones (will be overwritten by red)
    qG = quiver(x(Goodinds), y(Goodinds), u(Goodinds), v(Goodinds), ...
        'ShowArrowHead','on', 'AutoScale','off');
    set(qG, 'Color','g', 'LineWidth',1);

    % Damaged tiles (red)
    qD = quiver(x(Daminds), y(Daminds), u(Daminds), v(Daminds), ...
        'ShowArrowHead','on', 'AutoScale','off');
    set(qD, 'Color','r', 'LineWidth',1);

    % Unknown/low-confidence (gray)
    if ~isempty(Unknowninds)
        qU = quiver(x(Unknowninds), y(Unknowninds), u(Unknowninds), v(Unknowninds), ...
            'ShowArrowHead','on', 'AutoScale','off');
        set(qU, 'Color','yellow', 'LineWidth',1);
    end

    hold off;
    title('SHG Fiber Orientation (Green=Good, Red=Damaged, yellow=Unknown)');
    % ==========================

% ANGLE VECTORS (DEFINE)
% ==========================
theta = fiberAngles(:);

theta_good      = theta(GoodTile(:) & ~isnan(theta));
theta_goodNoDam = theta(GoodTile(:) & ~DamTile(:) & ~isnan(theta));
theta_dam       = theta(DamTile(:) & ~isnan(theta));
theta_unknown   = theta(UnknownTile(:) & ~isnan(theta));

edges   = -90:5:90;
centers = edges(1:end-1) + diff(edges)/2;

c_good = zeros(1, numel(centers));
c_dam  = zeros(1, numel(centers));
c_unk  = zeros(1, numel(centers));

if ~isempty(theta_good)
    c_good = histcounts(theta_good, edges, 'Normalization','probability');
end
if ~isempty(theta_dam)
    c_dam  = histcounts(theta_dam, edges, 'Normalization','probability');
end
if ~isempty(theta_unknown)
    c_unk  = histcounts(theta_unknown, edges, 'Normalization','probability');
end

histFig = figure;
bar(centers, [c_good(:), c_dam(:), c_unk(:)], 'grouped');  % NO overlap

xlabel('Angle (deg)');
ylabel('Probability');
title('Fiber Orientation Distribution (Grouped)');
legend({'Good','Damaged','Unknown'}, 'Location','best');
grid on

    % ==========================
    % CIRCULAR STATS (use "good" angles)
    % ==========================
    theta_stats = theta_good;                % vector of angles (deg)
    theta_noDam_stats = theta_goodNoDam;     % vector of angles (deg)

    % Keep legacy behavior: write angles file (still writes all theta including NaNs)
    theta_mat = fiberAngles;
    [y_pos,x_pos] = ind2sub(size(theta_mat),1:numel(theta_mat));
    x_pos = x_pos'; y_pos = y_pos';
    theta_vec = reshape(theta_mat, [], 1);

    pixScale = 1024 / 276.79;
    write_angles(theta_vec, rfnm{jj}, pth2, windowSize, x_pos, y_pos, pixArea, pixScale);

    % Save figures
    if strcmp(saveChoice,'Yes')
        saveas(qPlot, fullfile(pth2, [rfnm{jj} '_quiver.tiff']));
        saveas(histFig, fullfile(pth2, [rfnm{jj} '_hist.tiff']));
    end

    % Circular dispersion stats
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

    fprintf('Image %d: Good tiles=%d, Damaged tiles=%d, Unknown tiles=%d\n', ...
        jj, nnz(GoodTile), nnz(DamTile), nnz(UnknownTile));
    % ==========================
% PRINT SUMMARY (inside loop)
% ==========================
cv_overall = ang_var(jj,1);
cv_noDam = ang_var_noDam(jj,1);
delta_cv = cv_overall - cv_noDam;

% ==========================
% WRITE PER-IMAGE SUMMARY
% ==========================
fprintf(fid, '%s\t%d\t%d\t%d\t%.4f\t%.6f\t%.6f\t%.6f\n', ...
    rfnm{jj}, ...
    nnz(GoodTile), ...
    nnz(DamTile), ...
    nnz(UnknownTile), ...
    PercDam(jj), ...
    cv_overall, ...
    cv_noDam, ...
    delta_cv);


if delta_cv > 0
    fprintf('Removing damaged tiles reduces dispersion (improved coherence).\n');
elseif delta_cv < 0
    fprintf('Warning: Removing damaged tiles increased dispersion.\n');
else
    fprintf('No change in dispersion after removing damaged tiles.\n');
end



fprintf('\n[%s] cv_overall=%.4f | CV_noDam=%.4f | ΔCV=%.4f | DamFrac=%.3f\n', ...
    rfnm{jj}, cv_overall, cv_noDam, delta_cv, PercDam(jj));
perTiffSummaryFile = fullfile(pth2, [rfnm{jj} '_damageSummary.txt']);
fid2 = fopen(perTiffSummaryFile, 'w');

fprintf(fid2, 'Sample:\t%s\n', rfnm{jj});
fprintf(fid2, 'GoodTiles:\t%d\n', nnz(GoodTile));
fprintf(fid2, 'DamagedTiles:\t%d\n', nnz(DamTile));
fprintf(fid2, 'UnknownTiles:\t%d\n', nnz(UnknownTile));
fprintf(fid2, 'DamFrac:\t%.4f\n', PercDam(jj));
fprintf(fid2, 'cv_overall:\t%.6f\n', cv_overall);
fprintf(fid2, 'CV_noDam:\t%.6f\n', cv_noDam);
fprintf(fid2, 'DeltaCV:\t%.6f\n', delta_cv);

fclose(fid2);

end
% ==========================
% CLOSE SUMMARY FILE
% ==========================
fclose(fid);
fprintf('Summary written to: %s\n', summaryFile);


close(h1);

% ==========================
% REPORT (unchanged format)
% ==========================
head_txt = {
'%Sample Name	N_good (%)	N_total (#)	Cropped Area (pix)	Cir-Var (rad^2)	Ang-Var (rad^2)	Standard-Var (rad^2)	Ang-Dev(deg)	Cir-Dev (deg)	Cir-Var_noDam (rad^2)	Ang-Var_noDam (rad^2)	Standard-Var_noDam (rad^2)	Ang-Dev_noDam (deg)	Cir-Dev_noDam (deg)'
};

circularVariance = ang_var(:,1);
angularVariance  = ang_var(:,2);
standardVariance = ang_var(:,3);

angularDeviation = ang_dev(:,1);
circularDeviation = ang_dev(:,2);

circularVariance_noDam = ang_var_noDam(:,1);
angularVariance_noDam  = ang_var_noDam(:,2);
standardVariance_noDam = ang_var_noDam(:,3);

angularDeviation_noDam = ang_dev_noDam(:,1);
circularDeviation_noDam = ang_dev_noDam(:,2);

N_good = 100 - (100 * PercDam);

dataLines = cell(length(filename),1);
for ij = 1:length(filename)
    dataLines{ij} = sprintf('%s\t%.3f\t%d\t%d\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f', ...
        rfnm{ij}, N_good(ij), N_total(ij), round(pixArea), ...
        circularVariance(ij), angularVariance(ij), standardVariance(ij), ...
        angularDeviation(ij), circularDeviation(ij), ...
        circularVariance_noDam(ij), angularVariance_noDam(ij), standardVariance_noDam(ij), ...
        angularDeviation_noDam(ij), circularDeviation_noDam(ij));
end

report_text = [head_txt; dataLines];
write_report(report_text, SHGcircstats);

% Console summary (ignore slices with >50% damage)
damLog = find(N_good < 50);
dt_comp = [N_good, N_total, pixArea*ones(size(N_good)), circularVariance, angularVariance, standardVariance, ...
    angularDeviation, circularDeviation, circularVariance_noDam, angularVariance_noDam, standardVariance_noDam, ...
    angularDeviation_noDam, circularDeviation_noDam];

if ~isempty(damLog)
    dt_comp(damLog,:) = [];
end

dt_mean = mean(dt_comp, 1, 'omitnan');

head_scrn = head_txt{1};
fprintf('%s\n', head_scrn);
fprintf('%s\t%.3f\t%.0f\t%.0f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\n', ...
    nameInt, dt_mean(1), dt_mean(2), dt_mean(3), dt_mean(4), dt_mean(5), dt_mean(6), dt_mean(7), dt_mean(8), ...
    dt_mean(9), dt_mean(10), dt_mean(11), dt_mean(12), dt_mean(13));

toc
disp('--- Variables in workspace ---');
whos
end

