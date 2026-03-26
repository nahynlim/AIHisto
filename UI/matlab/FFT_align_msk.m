function [] = FFT_align_msk()

tic
ver = version('-release');
if strcmp(ver,'2016b') || strcmp(ver,'2014a') || strcmp(ver,'2024a')
    if ~exist('parpool')
        parpool local
    end
else
    labs = parpool('size');
    if labs==0
        parpool open
    end
end

clearvars -except inipth;
close all;

if (~exist('inipth','var') || inipth==0)
    inipth='C:\Users\Spence\Documents\CloudStation';
end

[fnm, pth] = uigetfile('*.tif', 'Select image to analyze',inipth);
inipth=pth;
if (fnm == 0)
    uiwait(warndlg('You''re doing it wrong!'));
    return;
end
eg_file = fullfile(pth,fnm);

if strcmp(fnm(1),'c')
    Sdir = dir(fullfile(pth,'*c005.tif'));
else
    Sdir = dir(fullfile(pth,'*.tif'));
end
fnames = {Sdir.name};

sr_v = listdlg('PromptString', 'Choose SHG channel 5 images', ...
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

qstring = 'Do you need to create a mask?';
maskChoice = questdlg(qstring, 'Masking option', ...
    'That sounds great', 'Already did', 'What?', 'That sounds great');

ang_var = zeros(length(filename),3);
ang_dev = zeros(length(filename),2);

qstring = 'Sharpen and enhance all images?';
enhanceChoice = questdlg(qstring, 'Image Enhancement', 'Yes', 'No','Woof', 'Yes');

dlg_title = 'Input Window Size Parameters';
prompt = {'Enter Bundle Width (pixels):', 'Enter Bundle height (pixels):'};
defAns = {'15', '15'};
answer1 = inputdlg(prompt, dlg_title, 1, defAns);
windowSize = [str2double(answer1{1}), str2double(answer1{2})];

qstringFig = 'Would you like to save your figures?';
saveChoice = questdlg(qstringFig,'Save Figures','Yes','No','I''m not sure','Yes');

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
FFT_mask_file = regexprep(SHGcircstats,'_SHGstats','_SHGmask');

if strcmp(maskChoice,'That sounds great')
    pout_draw = imread(filename{1});
    drawFig = figure;
    imshow(pout_draw);
    uiwait(msgbox('Draw border around the ROI'));
    hold on
    Hply = impoly;
    poly_pos = wait(Hply);
    delete(Hply);
    hold on 
    plot(poly_pos([1:end,1],1), poly_pos([1:end,1],2),'r+-');
    cmsk = poly_pos(:,1);
    rmsk = poly_pos(:,2);
end

PercDam = zeros(length(filename),1);
N_total = zeros(length(filename),1);

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
        BW4 = ones(size(pout)); % no mask
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

    pout_tiles= mat2tiles(pout_sharp, windowSize);
    BW_tiles=mat2tiles(BW4,windowSize);
    tileSize=windowSize(1)*windowSize(2);

    [row, col] = size(pout_tiles);
    imageDim = size(pout_sharp);
    X=0:windowSize(2):imageDim(2);
    if length(X)<size(BW_tiles,2)
        X=cat(2,X,X(end)+windowSize(2));
    end
    Y=windowSize(1)/2:windowSize(2):imageDim(1);
    if length(Y)<size(BW_tiles,1)
        Y=cat(2,Y,Y(end)+windowSize(1));
    end
    [x, y] = meshgrid(X,Y);

    transforms = cell(size(pout_tiles));
    normTransform = cell(size(pout_tiles));
    filtTransform = cell(size(pout_tiles));
    BWellipses = cell(size(pout_tiles));
    ellipse_orient = cell(size(pout_tiles));
    grayTransforms = cell(size(pout_tiles));
    ellipses = cell(size(pout_tiles));
    Eccent = nan(size(pout_tiles));

    imageTileSize = numel(pout_tiles);

    parfor ii = 1:imageTileSize
        if sum(BW_tiles{ii}(:)) < 0.75*tileSize
            ellipse_orient{ii} = NaN;
            Eccent(ii)=NaN;
            continue
        end
        transforms{ii} = fftshift(abs(fft2(pout_tiles{ii})));
        normTransform{ii} = log(transforms{ii}+1);
        h = ones(3,3) / 9;
        filtTransform{ii} = imfilter(normTransform{ii},h);

        grayTransforms{ii} = mat2gray(filtTransform{ii});
        top10 = quantile(grayTransforms{ii}(:),.90);
        ellipses{ii} = imbinarize(grayTransforms{ii}, top10);

        BWellipses{ii} = bwareaopen(ellipses{ii},12);

        CC = bwconncomp(BWellipses{ii});
        if CC.NumObjects == 1
            S = regionprops(BWellipses{ii},'orientation','eccentricity');
        else
            BWellipses{ii} = BWellipses{ii}*2;
            S = regionprops(BWellipses{ii},'orientation','eccentricity');
            if isempty(S)
                ellipse_orient{ii} = NaN;
                Eccent(ii)=0;
                continue
            end
            S(1)=[];
        end

        ellipse_orient{ii} = S.Orientation;
        Eccent(ii) = S.Eccentricity;
    end

    ellipseAngles = cell2mat(ellipse_orient);
    fiberAngles = ellipseAngles + 90;
    fiberAngles(fiberAngles > 90) = fiberAngles(fiberAngles > 90) - 180;

    Badinds = find(Eccent < 0.85);
    fiberAngles(Badinds) = NaN;
    Tinds = find(~isnan(Eccent));
    N_total(jj) = numel(Tinds);

    fprintf('After filtering bad eccentricities: Valid fiber angles = %d\n', sum(~isnan(fiberAngles)));


    temp = cat(2, nan(size(fiberAngles,1),1), fiberAngles(:,1:end-1));
    diffL = abs(fiberAngles - temp);

    temp = cat(2, fiberAngles(:,2:end), nan(size(fiberAngles,1),1));
    diffR = abs(fiberAngles - temp);

    DamThresh = 30;
    Daminds = find(diffL > DamThresh | diffR > DamThresh | Eccent < 0.9);

    BWdam = zeros(size(BW4));
    for i=1:length(Daminds)
        [I,J] = ind2sub(size(Eccent),Daminds(i));
        BWdam((I-1)*windowSize(1)+1:I*windowSize(1), (J-1)*windowSize(2)+1:J*windowSize(2)) = ones(windowSize);
    end
    BWdam = imrotate(BWdam, -90);
    PercDam(jj) = length(Daminds)/length(Tinds);

    arrowLength = 15;
    u = arrowLength*cosd(fiberAngles);
    v = -arrowLength*sind(fiberAngles);

    theta_mat = fiberAngles;
    [y_pos,x_pos] = ind2sub(size(theta_mat),1:numel(theta_mat));
    x_pos = x_pos';
    y_pos = y_pos';
    theta = reshape(theta_mat, [], 1);
    theta_noDam = theta;
    theta_noDam(Daminds) = NaN;

    theta_noDam_stats = theta_noDam(~isnan(theta_noDam));
    theta_stats = theta(~isnan(theta));

    pixScale = 1024 / 276.79;

    write_angles(theta, rfnm{jj}, pth2, windowSize, x_pos, y_pos, pixArea, pixScale);

    % Quiver Plot
    qPlot = figure;
    imshow(pout_sharp);
    hold on;
    q = quiver(x(Tinds), y(Tinds), u(Tinds), v(Tinds), 'ShowArrowHead','on', 'AutoScale', 'off');
    set(q, 'Color', 'g', 'LineWidth', 1);
    q2 = quiver(x(Daminds), y(Daminds), u(Daminds), v(Daminds), 'ShowArrowHead','on', 'AutoScale', 'off');
    set(q2, 'Color', 'r', 'LineWidth', 1);
    q3 = quiver(x(Badinds), y(Badinds), u(Badinds), v(Badinds), 'ShowArrowHead','on', 'AutoScale', 'off');
    set(q3, 'Color', 'r');
    hold off;

    % Histogram
    histFig = figure;
    numBins = 25;
    if (sum(~isnan(theta))/numel(theta)) > 0.05
        histfit(theta_stats, numBins);
        title('Angular Frequency');
        xlabel('Angle (degrees)');
        ylabel('Angular Frequency (number of samples)');
    end

    if strcmp(saveChoice,'Yes')
        strOut_quiver = fullfile(pth2, [rfnm{jj} '_quiver.tiff']);
        strOut_hist = fullfile(pth2, [rfnm{jj} '_hist.tiff']);
        saveas(qPlot, strOut_quiver);
        saveas(histFig, strOut_hist);
    end

    % Circular Statistics
    [ang_var(jj,:), ang_dev(jj,:)] = circ_disp(theta_stats);
    [ang_var_noDam(jj,:), ang_dev_noDam(jj,:)] = circ_disp(theta_noDam_stats);
end

close(h1);

% Write report

head_txt = {
    '%Sample Name	N_good (%)	N_total (#)	Cropped Area (pix)	Cir-Var (rad^2)	Ang-Var (rad^2)	Standard-Var (rad^2)	Ang-Dev(deg)	Cir-Dev (deg)	Cir-Var_noDam (rad^2)	Ang-Var_noDam (rad^2)	Standard-Var_noDam (rad^2)	Ang-Dev_noDam (deg)	Cir-Dev_noDam (deg)'
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
inc = N_good > 50;

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

% Display average summary (ignoring slices with >50% damage)
damLog = find(N_good < 50);
dt_comp = [N_good, N_total, pixArea*ones(size(N_good)), circularVariance, angularVariance, standardVariance, ...
    angularDeviation, circularDeviation, circularVariance_noDam, angularVariance_noDam, standardVariance_noDam, ...
    angularDeviation_noDam, circularDeviation_noDam];

if ~isempty(damLog)
    dt_comp(damLog,:) = [];
end

dt_mean = mean(dt_comp, 1);

head_scrn = '%Sample Name	N_good (%)	N_total (#)	Cropped Area (pix)	Cir-Var (rad^2)	Ang-Var (rad^2)	Standard-Var (rad^2)	Ang-Dev(deg)	Cir-Dev (deg)	Cir-Var_noDam (rad^2)	Ang-Var_noDam (rad^2)	Standard-Var_noDam (rad^2)	Ang-Dev_noDam (deg)	Cir-Dev_noDam (deg)';

fprintf('%s\n', head_scrn);
fprintf('%s\t%.3f\t%.0f\t%.0f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\t%.6f\n', ...
    nameInt, dt_mean(1), dt_mean(2), dt_mean(3), dt_mean(4), dt_mean(5), dt_mean(6), dt_mean(7), dt_mean(8), dt_mean(9), dt_mean(10), dt_mean(11), dt_mean(12), dt_mean(13));

toc

disp('--- Variables in workspace ---');
whos

fprintf('Image %d: Total tiles=%d, Valid tiles=%d\n', jj, numel(fiberAngles), sum(~isnan(fiberAngles(:))));

end

