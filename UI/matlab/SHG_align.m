%% About

% Author: Ashley Rodriguez
% Date: 03/02/2016 
% Modified by: Ashley Rodriguez
% Date Modified: 05/11/2016

% Description: The software will load a tif image taken from the SHG
% microscope and determine the angular orientation of the collagen fibers

%% Clear Workspace
clear all; 
close all force;
clc

%% Image Processing

% upload image
[rawImage, pth] = uigetfile('.tif', 'Select Image to Analyze'); % pop-up menu to load image to analyze

file_pth = fullfile(pth,rawImage);
loadedImage = imread(file_pth);

figure(1)
    imshow(rawImage); % show raw image
    title('Raw Image taken from SHG');

% Crop image
imageSize = [1 1 499 249]; % size of the rectangle that will appear ---> Can change this size
h = imrect(gca, imageSize); % draw the rectangle on the image
addNewPositionCallback(h,@(p)title(mat2str(p,3)));
fcn = makeConstrainToRectFcn('imrect',get(gca,'XLim'),get(gca,'YLim'));
setPositionConstraintFcn(h,fcn);
position  = wait(h); % double click to execute rest of code
cropImage = imcrop(loadedImage,position); % crop rectangle after positioned

%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% Contrast and Enhance
qstring = 'Binary will probably analyze the image better. Proceed w/ a binary image?';
enhanceChoice = questdlg(qstring, 'Image Enhancement', ...
            'Yes', 'No','Woof', 'Woof'); 

    if strcmp(enhanceChoice,'Yes') 
   
%%%% Grayscale
%         pout_imadjust = im2bw(cropImage, 0.35);
        pout_imadjust1 = imadjust(cropImage);
%         pout_histeq = histeq(cropImage);
%         pout_adapthisteq = imadjust(adapthisteq(cropImage));
        pout_imadjust = imsharpen(pout_imadjust1, 'Threshold', 0.5);
        
        figure(2), imshow(pout_imadjust);
        title('Imadjust');


%%%%%% Binary
%         thresh = graythresh(cropImage);
%         pout_imadjust = im2bw(cropImage,thresh);
%         figure(2), imshow(pout_imadjust);
%     else
%         pout_imadjust = cropImage;
%         figure(2), imshow(pout_imadjust)
%         
    end
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


    
%% Determine Image gradient

% imgradient and imgradientxy use a sobel filter as default
[Gx Gy] = imgradientxy(pout_imadjust); % horizontal and vertical gradients
[Gmag Gdir] = imgradient(Gx, Gy); % gradient magnitude and direction

figure(3)
    subplot(2,2, [1 2])
    imshow(Gx)
    title('horizontal gradient');
    hold on
    subplot(2,2, [3 4])
    imshow(Gy)
    title('vertical gradient');

figure(4)
    imshow(Gdir, []);
    title('Gradient direction');

figure(5)
    imshow(Gmag, []);
    title('Gradient Magnitude');
    
%% Tiles 
% Determine average gradients in 10 x 10 blocks --> left over that does not
% fit in 10 x 10 block gets truncated 
% 
% Ask user for bundle parameters
dlg_title = 'Input Bundle Parameters';
prompt(1,1) = {'Enter Bundle Width (pixels):'};
prompt(2,1) = {'Enter Bundle height (pixels):'};
num_lines = 1;
defAns = {'5', '5'};

answer1 = inputdlg(prompt, dlg_title, num_lines, defAns);

answer(1) = str2double(answer1{1});
answer(2) = str2double(answer1{2});

% Gradient tiling and averaging
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Gx_cell = mat2tiles(Gx, answer);
Gy_cell = mat2tiles(Gy, answer);

% Gx_cellSize = numel(Gx_cell);
% Gy_cellSize = numel(Gy_cell);
% 
% for ii = 1:Gx_cellSize
%     Gx_cell{ii} = mean(mean(Gx_cell{ii}));
% end
% 
% for jj = 1:Gy_cellSize
%     Gy_cell{jj} = mean(mean(Gy_cell{jj}));
% end

Gx_mat = cell2mat(Gx_cell);
Gy_mat = cell2mat(Gy_cell);

Gx_mat = zeros(size(Gx_cell));
Gy_mat = zeros(size(Gy_cell));

%take the last value in the tile
for ii = 1:numel(Gx_cell)
    
    Gx_mat(ii) = Gx_cell{ii}(end);
    
end

for jj = 1:numel(Gy_cell);
    
    Gy_mat(jj) = Gy_cell{jj}(end);
    
end



%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
% This has no effect on the quiver. This is here to get a feel for the
% theta values we are getting
% Gdir_cell = mat2tiles(Gdir,answer);
% Gdir_cellSize = numel(Gdir_cell);
% 
% for jj = 1:Gdir_cellSize
%     Gdir_cell{jj} = mean(mean(Gdir_cell{jj}));
% end
% 
% theta_mat = zeros(size((Gdir_cell)));
% 
% for jj = 1:numel(Gdir_cell)
%     
%     theta_mat(jj) = Gdir_cell{jj}(end);
%     
% end
% 
% 
% Gdir_mat = cell2mat(Gdir_cell);

% Bin and average pixel intensity values

pixBundles = mat2tiles(pout_imadjust, answer);
pixBundlesSize = numel(pixBundles);


for kk = 1: pixBundlesSize
   
    pixBundles_cell{kk} = mean(mean(pixBundles{kk}));
    
end

meanPixBundles = cell2mat(pixBundles_cell);
intensePix = meanPixBundles;% = reshape(meanPixBundles, [numel(meanPixBundles),1]);

% Calculate angular orientation
theta_mat = rad2deg(atan2(Gx_mat,-Gy_mat)); % if (Gx,Gy) is the gradient, then (-Gy,Gx) is the orthogonal
tem = (theta_mat < 0);
theta_mat(tem) = theta_mat(tem) + 180; % add 180 to the values that are negative


HeatMap(theta_mat); % colorbar?

% Reformat theta from matrix to vector (for .txt output)

theta = reshape(theta_mat, [numel(theta_mat),1]);

% Set up and filter quiver plot

rad = zeros(size(theta_mat)); % pre-allocate a radius matrix

% Parameters for disregarding noisy areas
exit_loop = 0; % initialize a value to exit a while loop
abort_loop = false; % initialize loop start
iteration = 1; % initialize number of times loop runs
pixLog = zeros(size(theta_mat)); % pre-allocate a logical matrix to store T/F if bundles are close


% Find similar pixel intensities--> indication of noise
for i = 1:numel(intensePix)-3
    
    step = intensePix(i) < (intensePix(i+1:i+3) + 25) & (intensePix(i)> (intensePix(i+1:i+3) - 25)); % if the pixel value at a single index is similar to the next 3 pixel bundles
    
    if sum(step) > 0 % if neighbor pixel bundles are similiar values
        pixLog(i) = 1; % then the logical index is 1
    else
        pixLog(i) = 0; % if they are not similar, then the logical index is 0
    end
    
    if pixLog(i) == 0 % if the neighbor pixels are similar
        rad(i) = 0; % then the arrow length is 0
    else 
        rad(i) = 5; % otherwise the arrow length is 1 (shows up)
    end
    
    
end


% Arrow production team
u = rad.*cosd(theta_mat); % create arrow vector orientation for quiver
v = rad.*sind(theta_mat);

u(u==5) = 0;
v(v==5) = 0;


%% Create Quiver plot

% Quiver plot
figure(6)
imshow(pout_imadjust);
% imshow(Gx+Gy) % show the image after edge detection and gradient direction 
hold on
% Incorporate quiver
imageDim = size(pout_imadjust);
[row col] = size(theta_mat);
[x y] = meshgrid(linspace(0, imageDim(2), col) ,linspace(0, imageDim(1), row)); % try indexing out boundaries than a linearly spaced vector
q = quiver(x, y, u, v, 'ShowArrowHead','off','AutoScale', 'off');
set(q,'Color','r', 'LineWidth',1);


%% Histograms

figure(7);
    numBins = 9; % number of bins to display in the histogram
%     hist(theta,numBins);
    rose(theta)
    title('Angular Frequency');
    
figure(9);
    hist(intensePix,numBins); % pixel intensity histograms
    title('Pixel Intensity')

  
%% Determine variance, standard deviation, and average angle

stdev_dist = std(theta);
circVar_rad = cir_var(degtorad(theta));
circVar_deg = radtodeg(circVar_rad);
meanRad = circ_mean(degtorad(theta));
meanDeg = radtodeg(meanRad);

%% Write to Text File and Output Data

% % Header Information
% head_txt(1,1) = {sprintf('Patellar Tendon Collagen Angular Orientation')};
% head_txt(2,1) = {sprintf('%%Date:\t%s', ...
%                          datestr(now, 'yyyy.mm.dd'))};
% head_txt(3,1) = {sprintf('Angle(deg)')};
% 
% % Output data to string
% % will there be more output than just angle?
% data_txt(1,1) = {sprintf('%.2f\n', theta)};
% % data_txt_meanDeg(1,1) = {sprintf('%.3f\n', meanDeg)};
% % data_txt_circVar(1,1) = {sprintf('%.3f\n', circVar_deg)};
% 
% % output_txt = [head_txt; csd_txt; data_txt];
% output_txt = [head_txt; data_txt];
% 

% % Write Data to .txt File
% [ nfnm, npth ] = uiputfile('*_SHG_align.txt', ...
%                         'Choose Output File');%, ...
%                         %SHG_align_file);
% if(nfnm == 0)
%     warndlg('Not Saving Data');
%     return;
% end
% SHG_align_file = fullfile(npth ,nfnm);
% 
% write_report(output_txt, SHG_align_file);


%% Write to .txt

[fnm, npth] = uiputfile('*_SHG_align.txt', ...
                        'Choose Output File');%, ...
                        %SHG_align_file);
                                              
if(fnm == 0)
    warndlg('Not Saving Data');
    return;
end

fID = fopen(fnm,'w'); % Open file to write in
                        
fprintf(fID, 'Patellar Tendon Collagen Angular Orientation\n');
fprintf(fID, '%%Date:\t%s\n', datestr(now, 'yyyy.mm.dd'));
fprintf(fID, 'Angle(deg)\n');%\tMean Angle\tCircular Variance\n');

%Output data to string

fprintf(fID, '%.2f\n', theta);%,meanDeg,circVar_deg);

fclose(fID); % close file





