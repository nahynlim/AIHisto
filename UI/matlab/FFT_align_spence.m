%% About

% Description: This function uses FFT analysis to calculate the
% frequencies pixel intensities to determine the collagen fiber orientation
% of a tendon

%% Initialization

% Setup parallel processing
% labs=parpool('size');
ver = version('-release');
if strcmp(ver,'2015a') || strcmp(ver,'2014a')
    if ~exist('parpool') %labs==0
        parpool local
    end
else
    labs=matlabpool('size');
    if labs==0
        matlabpool open
    end
end
% Clear workspace
clearvars -except inipth;
close all;  

%% Load SHG image

if (~exist('inipth','var') | inipth==0)
    inipth='C:\Users\Spence\Documents\CloudStation';
end


[fnm, pth] = uigetfile('*_005.tif', 'Select image to analyze',inipth);
inipth=pth;

if (fnm ==0)
    uiwait(warndlg('You''re doing it wrong!'));
    return;
end

eg_file = fullfile(pth,fnm)

Sdir = dir(fullfile(pth,'*.tif'));

fnames = {Sdir.name};

sr_v = listdlg(...
        'PromptString', 'Choose SHG collagen images', ...
        'SelectionMode', 'Multiple', ...
        'Name', '.tif SHG collagen images', ...
        'InitialValue', 1:2, ...
        'ListString', fnames,...
        'Listsize',[300 400]);
    
if(isempty(sr_v))
  uiwait(warndlg('OOPS! There doesn''t seem to be anything here!'));
    return;
end  


    for i=1:length(sr_v)
        filename(i,1) = {fullfile(pth, char(fnames(sr_v(i))))};
    end
    
%%%%
% fnm_pth = fullfile(pth,fnm); % Create a file pathway so MATLAB can navigate to other folders

ang_var = zeros(length(filename(:,1)),3);
ang_dev = zeros(length(filename(:,1)),2);

% Before entering a for loop, ask user if s/he would like to enhance all
% images'

qstring = 'Lookin'' sharp! Would you like all images to look dapper (sharpen/enhanced) as well?';
enhanceChoice = questdlg(qstring, 'Image Enhancement', ...
            'Yes', 'No','Woof', 'Yes'); 

% Ask about window size before jj for loop
    % Ask user for window parameters
    dlg_title = 'Input Window Size Parameters';
    prompt(1,1) = {'Enter Bundle Width (pixels):'};
    prompt(2,1) = {'Enter Bundle height (pixels):'};
    num_lines = 1;
    defAns = {'25', '25'}; % default answer

    answer1 = inputdlg(prompt, dlg_title, num_lines, defAns); % User input

    windowSize(1) = str2double(answer1{1});
    windowSize(2) = str2double(answer1{2});

    h1 = waitbar(0,'Analyzing images...');
for jj = 1:length(filename(:,1))
        
        waitbar(jj/length(filename(:,1)));
        pout_init = imread(char(filename(jj)));

    %     pout_init = imread(fnm_pth); % Read the image from whatever pathway the image came from
    pout = pout_init(:,:,end); % Some images have multiple Z layers. Only the last Z layer seems to have data
    clear pout_init


    % Angles are between -90 and 90 deg, so tendon must be horizontal in image
    % pout = imrotate(pout,90);

    % Create mask of tendon area
    BW=im2bw(pout,graythresh(pout));
    BW2=imclose(BW,strel('disk', 6, 4));
    BW3=imfill(BW2,'holes');
    BW4=bwareaopen(BW3,round(size(BW3,1)*size(BW3,2)*.1));
    clear BW BW2 BW3
    BW4=ones(size(pout));  % Uncomment if tendon fills FOV
    B = bwboundaries(BW4);

    figure, imshow(pout);
    hold on
    plot(B{1}(:,2),B{1}(:,1),'r')
    hold off
    title('raw image')

%    % This wasn't in the paper but I think sharpening the image would help w/
% % dividing the intensities into bands
% % We can ask the user first... but they should
% qstring = 'Sharpening the image will help the code run. Would you like to sharpen?';
% enhanceChoice = questdlg(qstring, 'Image Enhancement', ...
%             'Yes', 'No','Woof', 'Yes'); 
        
    % This is from before entering the (jj) for loop-de-loop
        if strcmp(enhanceChoice,'Yes') 
            pout_imadjust = imadjust(pout);
            % pout_histeq = histeq(pout);
            % pout_adapthisteq = imadjust(adapthisteq(pout));
            pout_sharp = imsharpen(pout_imadjust, 'Threshold',0.5);% 'Amount', 2);
            figure, imshow(pout_sharp);
            hold on
            plot(B{1}(:,2),B{1}(:,1),'r')
            hold off
            title('sharpened image')
        else
            % do nothing and continue with the code
            pout_sharp = pout;
        end
    clear pout pout_imadjust


    %% Window washing co. 
    
%     % Divide image into "many smaller windows" 
%     % Ask user for window parameters
%     dlg_title = 'Input Window Size Parameters';
%     prompt(1,1) = {'Enter Bundle Width (pixels):'};
%     prompt(2,1) = {'Enter Bundle height (pixels):'};
%     num_lines = 1;
%     defAns = {'25', '25'}; % default answer
% 
%     answer1 = inputdlg(prompt, dlg_title, num_lines, defAns); % User input
% 
%     windowSize(1) = str2double(answer1{1});
%     windowSize(2) = str2double(answer1{2});

    pout_tiles= mat2tiles(pout_sharp, windowSize); % It's been tiled
    BW_tiles=mat2tiles(BW4,windowSize);     % Tile binary image as well (will be used to produce damage mask)
    tileSize=windowSize(1)*windowSize(2);

    % Determine coordinates of future quiver plot
    % Note that arrow origin is at left boundary of subregion
    [row, col] = size(pout_tiles);
    imageDim = size(pout_sharp);
    X=0:windowSize(2):imageDim(2);
    if length(X)<size(BW_tiles,2)
        X=cat(2,X,X(end)+windowSize(2));    % In case tiling image produces residual tiles
    end
    Y=windowSize(1)/2:windowSize(2):imageDim(1);
    if length(Y)<size(BW_tiles,1)
        Y=cat(2,Y,Y(end)+windowSize(1));
    end
    [x, y] = meshgrid(X,Y); % x and y coordinates for meshgrid

    %% Fun with FFT


    % Pre-allocate everything for speed
    transforms = cell(size(pout_tiles)); %pre-allocate transform matrix/cell
    gauss = cell(size(pout_tiles)); % pre-allocate gauss filter.
    imageTileSize = numel(pout_tiles); % define how large for loop should be

    normTransform = cell(size(pout_tiles)); % pre-allocate normalized transforms
    filtTransform = cell(size(pout_tiles)); % pre-allocate filtered transforms
    BWellipses = cell(size(pout_tiles)); % pre-allocate the transform spectrum images
    ellipse_orient = cell(size(pout_tiles)); % pre-allocate angle for ellipse orientations
    grayTransforms = cell(size(pout_tiles));
    ellipses = cell(size(pout_tiles));
    CI = cell(size(pout_tiles));
    Eccent = nan(size(pout_tiles));

    tic
    % wh = waitbar(0,'Please Wait');
    parfor ii = 1:imageTileSize
        
        % Exclude tiles outside tendon area
        if sum(sum(BW_tiles{ii}))<.75*tileSize
            ellipse_orient{ii} = NaN;
            Eccent(ii)=NaN;
            continue
        end

        transforms{ii} = fftshift(abs(fft2(pout_tiles{ii}))); % Take the FFT of the image
    %     sigma = 1; % for Gaussian filter
    %     gauss{ii} = imgaussfilt(transforms{ii}, sigma, 'FilterSize',3);
    %     normTransform{ii} = log(gauss{ii}+1); % scale signal
        normTransform{ii} = log(transforms{ii}+1); % scale signal since DC contribution is very high
        h = ones(3,3) / 9; % Filter FFT with equal-weigted 3x3 box filter (works better than Gauss filter)
        filtTransform{ii} = imfilter(normTransform{ii},h);

        % Remove all but top 10% pixels by intensity in each window
        grayTransforms{ii} = mat2gray(filtTransform{ii}); % turn the normalized transforms as grayscale image
        top10 = quantile(reshape(grayTransforms{ii},1,[]),.9);
        ellipses{ii} = im2bw(grayTransforms{ii}, top10); % turn the grayscale into a binary image so that region props can determine the x-axis orientation

        BWellipses{ii} = bwareaopen(ellipses{ii},8); % clean out random pixels

        % If there are multiple objects when thresholding the FFT, make Matlab
        % fit an allipse to all of them at once as though they were one object
        CC = bwconncomp(BWellipses{ii});
        if CC.NumObjects==1
            S = regionprops(BWellipses{ii},'orientation','eccentricity');
        else
            BWellipses{ii}=BWellipses{ii}*2;        % Assign all objects the same label = 2
            S = regionprops(BWellipses{ii},'orientation','eccentricity');%,'ConvexImage');      % Determine angle and eccentricity of ellipse
            if isempty(S)           % If there are no objects
                ellipse_orient{ii} = NaN;
                Eccent(ii)=0;
                continue
            end
            S(1)=[];
        end

        ellipse_orient{ii} = S.Orientation;
    %     CI{ii}=S.MajorAxisLength/S.MinorAxisLength-1;   % From Sereysky 0 - circle, inf - line
        Eccent(ii)=S.Eccentricity;  %0 - circle, 1 - line

    %     waitbar(ii/imageTileSize)
    end % end parfor ii
    % close(wh)
    toc

    % It's easier to work from a matrix than a cell
    ellipseAngles = cell2mat(ellipse_orient); % These angles are oriented perpendicular to actual fiber orientation
    fiberAngles = ellipseAngles + 90;
    inds=find(fiberAngles>90);
    fiberAngles(inds)=fiberAngles(inds)-180;    % Convert to range between -90 and 90

    clear ellipse_orient ellipseAngles

    % Check if FFT-ps is accurately calculated by just viewing the first FFT
    % image
    % figure, imagesc(filtTransform{1}); colormap(gray);
    % title('example of first FFT spectrum')
    % 
    % % Show first ellipse after binarizing
    % figure,
    % imshow(imresize(BWellipses{1},10));
    % title('example of first FFT-ps image after binarizing')


    %% Quiver Plot

    % Remove angles that are fit poorly and hence inaccurate
    Badinds=find(Eccent<.85);
    fiberAngles(Badinds)=NaN;
    Tinds=find(~isnan(Eccent));     % Number of tiles fit (within tendon area)

    % Determine damage based on angular difference threshold and eccentricity
    % threshold
    temp=cat(2,nan(size(fiberAngles,1),1),fiberAngles(:,1:end-1));
    diffL = abs(fiberAngles - temp);        % Difference with left neighbor

    temp=cat(2,fiberAngles(:,2:end),nan(size(fiberAngles,1),1));
    diffR = abs(fiberAngles - temp);        % Difference with right neighbor

    DamThresh=30; % deg
    Daminds=find(diffL>DamThresh | diffR>DamThresh | Eccent<.9);
    % Daminds=find(Eccent<.9);

    % Produce binary image of damage regions
    BWdam=zeros(size(BW4));
    for i=1:length(Daminds)
        [I,J] = ind2sub(size(Eccent),Daminds(i));
        BWdam((I-1)*windowSize(1)+1:I*windowSize(1),(J-1)*windowSize(2)+1:J*windowSize(2)) = ones(windowSize);

    end
    BWdam = imrotate(BWdam,-90);
    figure, imshow(BWdam)

    % Form quiver lengths
    arrowLength =  25;
    u = arrowLength*cosd(fiberAngles); % horizontal arrow component for quiver 
    v = -arrowLength*sind(fiberAngles); % vertical arrow component for quiver (neg sign is due to yaxis pointing down in image)

    theta_mat = fiberAngles; % actual fiber orientation angles
    theta = reshape(theta_mat, [numel(theta_mat),1]); % reshape for the histogram

    % superimpose quiver on image
    figure
    imshow(pout_sharp);
    hold on

    % Plot undamaged regions in red
    q = quiver(x(Tinds),y(Tinds),u(Tinds),v(Tinds), 'ShowArrowHead','on','AutoScale', 'off');
    set(q,'Color','r', 'LineWidth',1);

    % Plot damage regions in green
    q2 = quiver(x(Daminds),y(Daminds),u(Daminds),v(Daminds), 'ShowArrowHead','on','AutoScale', 'off');
    set(q2,'Color','g', 'LineWidth',1);
    hold off

    % Determine percent area of tendon that is damaged
    PercDam = length(Daminds)/length(Tinds)

    % Angle histogram
    figure,
    numBins = 25; % number of bins to display in the histogram
    histfit(theta,numBins);
    title('Angular Frequency');
    xlabel('Angle (degrees');
    ylabel('Angular Frequency (number of samples)')


    % figure,
    % flowerPot = rose(deg2rad(theta), numBins); % plant the angle seed in the flower pot and watch it grow
    % title('Angular Histogram in a Flower Pot');



    %% Circular Statistics

    % stdev_dist = std(theta); % standard deviation
    % circVar_rad = cir_var(degtorad(theta_mat)); % circular variance in radians
    % circVar_deg = radtodeg(circVar_rad); % circular variance in degrees
    % meanRad = circ_mean(degtorad(theta)); % circular mean in radians
    % meanDeg = radtodeg(meanRad); % circular mean in degrees

    %   Calculates the circular dispersion
    [ang_var(jj,:), ang_dev(jj,:)] = circ_disp(theta);

end % end jj
close(h1)
%% Write report
% % Will fine tune after figuring out what outputs
% [fnm, npth] = uiputfile('*_FFT_align.txt', ...
%                         'Choose Output File');%, ...
%                         SHG_align_file);
%                                               
% if(fnm == 0)
%     warndlg('Not Saving Data');
%     return;
% end
% 
% fID = fopen(fnm,'w'); % Open file to write in
%                         
% fprintf(fID, 'Patellar Tendon Collagen Angular Orientation\n');
% fprintf(fID, '%%Date:\t%s\n', datestr(now, 'yyyy.mm.dd'));
% fprintf(fID, 'Angle(deg)\n');%\tMean Angle\tCircular Variance\n');
% 
% % Output data to string
% 
% fprintf(fID, '%.2f\n', theta);%,meanDeg,circVar_deg);
% 
% fclose(fID); % close file

%--get sample names
    % pull out sample name from pathway
    rfnm = cell(length(filename(:,1)),1);
    for k = 1:length(filename(:,1))   
        [~,rfnm{k}] = fileparts(char(filename(k)));
        
    end
%  sampleNames = rfnm;

%--- Header Information
head_txt(1,1) = {sprintf('%%Patellar Tendon Collagen Angular Organization\n')};
head_txt(2,1) = {sprintf('%%Date:\t%s\n',...
                            datestr(now,'yyyy.mm.dd'))};
head_txt(3,1) = {sprintf(['%%Sample Name\t',...
                            'Circular Variance (rad^2)\t',...
                            'Angular Variance (rad^2)\t',...
                            'Standard Variance (rad^2)\t',...
                            'Angular Deviation(deg)\t',...
                            'Circular Deviation (deg)\n'])};
disp(char(head_txt))                        
%--- Data to string
circularVariance    = ang_var(:,1);
angularVariance     = ang_var(:,2);
standardVariance    = ang_var(:,3);

angularDeviation    = ang_dev(:,1);
circularDeviation   = ang_dev(:,2);

dT_format = [circularVariance, angularVariance, standardVariance, angularDeviation,circularDeviation];

% dt_rpt = cell();

for ij = 1:length(filename(:,1)) 
    
    sampleName = rfnm{ij};
    dt_out = dT_format(ij,:);
    dt_txt =  {sprintf(['%s\t',...
                             '%.3f\t%.3f\t',...
                             '%.3f\t%.3f\t',...
                             '%.3f'], sampleName, dt_out)};
                         
    disp(char(dt_txt))                     
% dt_txt(1,2) = {sprintf(['%.3f\n'],circularVariance')};
% dt_txt(1,3) = {sprintf(['%.3f\n'],angularVariance')};
% dt_txt(1,4) = {sprintf(['%.3f\n'],standardVariance')};
% dt_txt(1,5) = {sprintf(['%.3f\n'],angularDeviation')};
% dt_txt(1,6) = {sprintf(['%.3f\n'],circularDeviation')};
end

% rpt_txt = [head_txt; dt_txt'];
% 
% [nfnm,npth] = uiputfile('*_CFO.txt',...
%                         'Choose Collagen Fiber Organization Output File');
% if (nfnm==0)
%     warndlg('Not Saving Data');
%     return;
% end
% CFO_file = fullfile(npth,nfnm);
% 
% write_report(rpt_txt,CFO_file);
