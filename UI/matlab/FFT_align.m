%% About

% Author: Ashley Rodriguez
% Date: 5/19/2016
% Date Modified: 5/26/2016
% Description: This function uses FFT-ps analysis to calculate the
% frequencies pixel intensities to determine the collagen fiber orientation
% of a tendon


%% Clear workspace
% Type "edit lol" into Command window
% Type the following into the .m file script
clear;
close all;  
clc;
% You now own Matlab's most powerful function

%% Load image

[fnm, pth] = uigetfile('*.tif', 'Select image to analyze');

fnm_pth = fullfile(pth,fnm); % Create a file pathway so MATLAB can navigate to other folders
pout_init = imread(fnm_pth); % Read the image from whatever pathway the image came from
pout = pout_init(:,:,end); % Some images have multiple Z layers. Only the last Z layer seems to have data
% pout = imrotate(pout,-20); --> Having trouble with the function running
% after rotating
figure, imshow(pout);
title('raw image')

% This wasn't in the paper but I think sharpening the image would help w/
% dividing the intensities into bands
% We can ask the user first... but they should
qstring = 'Sharpening the image will help the code run. Would you like to sharpen?';
enhanceChoice = questdlg(qstring, 'Image Enhancement', ...
            'Yes', 'No','Woof', 'Woof'); 
        
    if strcmp(enhanceChoice,'Yes') 
        pout_imadjust = imadjust(pout);
        % pout_histeq = histeq(pout);
        % pout_adapthisteq = imadjust(adapthisteq(pout));
        pout_sharp = imsharpen(pout_imadjust, 'Threshold',0.5);% 'Amount', 2);
        figure, imshow(pout_sharp); 
        title('sharpened image')
    else
        % do nothing and continue with the code
        pout_sharp = pout;
    end


%% Window washing co. 

% Divide image into "many smaller windows" 
% Ask user for window parameters
dlg_title = 'Input Window Size Parameters';
prompt(1,1) = {'Enter Bundle Width (pixels):'};
prompt(2,1) = {'Enter Bundle height (pixels):'};
num_lines = 1;
defAns = {'25', '25'}; % default answer

answer1 = inputdlg(prompt, dlg_title, num_lines, defAns); % User input

windowSize(1) = str2double(answer1{1});
windowSize(2) = str2double(answer1{2});

pout_tiles= mat2tiles(pout_sharp, windowSize); % It's been tiled


%% Fun with FFT


% Pre-allocate everything for speed
transforms = cell(size(pout_tiles)); %pre-allocate transform matrix/cell
gauss = cell(size(pout_tiles)); % pre-allocate gauss filter.
imageTileSize = numel(pout_tiles); % define how large for loop should be

normTransform = cell(size(pout_tiles)); % pre-allocate normalized transforms
BWellipses = cell(size(pout_tiles)); % pre-allocate the transform spectrum images
ellipse_orient = cell(size(pout_tiles)); % pre-allocate angle for ellipse orientations
grayTransforms = cell(size(pout_tiles));
ellipses = cell(size(pout_tiles));
ellipse_orientCell = cell(size(pout_tiles));

% FFT
for ii = 1:imageTileSize
     
    transforms{ii} = fftshift(abs(fft2(pout_tiles{ii})).^2); % Take the FFT of the image
    sigma = 1; % for Gaussian filter
    gauss{ii} = imgaussfilt(transforms{ii}, sigma, 'FilterSize',3);
    normTransform{ii} = log(gauss{ii}+1); % scale signal
        
    % high pass filter to remove all but top 10% contiguous pixels by
    % intensity in each window
    
    grayTransforms{ii} = mat2gray(normTransform{ii}(:,:,1),[min(min(normTransform{ii})),max(max(normTransform{ii}))]); % turn the normalized transforms as grayscale image 
    ellipses{ii} = im2bw(grayTransforms{ii}, graythresh(grayTransforms{ii})); % turn the grayscale into a binary image so that region props can determine the x-axis orientation

    BWellipses{ii} = bwareaopen(ellipses{ii},7); % clean out random pixels --> may have to finagle with the number
    
%     grayTransforms{ii} = imagesc(normTransform{ii});  colormap(gray)% display transform spectrums as images 
%     transformImages{ii} = getimage(grayTransforms{ii}); % get the images
    
    ellipse_orientCell{ii} = struct2cell(regionprops(BWellipses{ii},'orientation'));
    ellipse_orient{ii}= mean(cell2mat(ellipse_orientCell{ii})); % Taking the mean here probably isn't accurate... Second opinion?
    
end

% It's easier to work from a matrix than a cell
ellipseAngles = cell2mat(ellipse_orient); % These angles are oriented perpendicular to actual fiber orientation
ellipseAngles(ellipseAngles== 180) = 0; % filter out vertical confusion
ellipseAngles(ellipseAngles == 360) = 0; % filter out vertical confusion

% Check if FFT-ps is accurately calculated by just viewing the first FFT
% image
figure, imagesc(normTransform{1}); colormap(gray);
title('example of first FFT spectrum')

% Show first ellipse after binarizing
figure,
imshow(imresize(BWellipses{1},10));
title('example of first FFT-ps image after binarizing')


%% Quiver Plot

arrowLength =  25;
u = arrowLength*sind(ellipseAngles); % horizontal arrow component for quiver 
v = arrowLength*cosd(ellipseAngles); % vertical arrow component for quiver
u(ellipseAngles == 0) = 0; % filter out angles that are getting confused (vertical angles don't make sense)
v(ellipseAngles == 0) = 0; % filter out angles that are getting confused (vertical angles don't make sense)

theta_mat = rad2deg(atan2(v,u)); % actual fiber orientation angles
% theta_mat(theta_mat== 90) = 0; % filter out vertical confusion
% theta_mat(theta_mat == 270) = 0; % filter out vertical confusion

%_________________________________________
% Find absolute angles

% Determine what quadrant quiver components are in
q1 = find(u > 0 & v > 0); %(+,+) QI
q2 = find(u < 0 & v > 0); % (-,+) QII
q3 = find(u < 0 & v < 0); % (-,-) QIII
q4 = find(u > 0 & v < 0); % (+,-) QIV
    
% ***************************************** We should double check this.
theta_mat(q1) = theta_mat(q1) + 0; % do nothing in quadrant I
theta_mat(q2) = 180 - theta_mat(q2); % Find absolute angle in quadrant II
theta_mat(q3) = theta_mat(q3) - 180; % Find absolute angle in quadrant III
theta_mat(q4) = 360-theta_mat(q4); % Find absolute angle in quadrant IV

theta = reshape(theta_mat, [numel(theta_mat),1]); % reshape for the histogram

%_________________________________________


% superimpose quiver on image
figure, imshow(pout_sharp);
hold on
[row, col] = size(ellipseAngles);
imageDim = size(pout_sharp);
[x, y] = meshgrid(linspace(0, imageDim(2), col) ,linspace(0, imageDim(1), row)); % x and y coordinates for meshgrid
q = quiver(x,y,u,v, 'ShowArrowHead','on','AutoScale', 'off');
set(q,'Color','b', 'LineWidth',1.2); % The color is blue because Snehal is red/green colorblind :)
hold off


figure,
numBins = 9; % number of bins to display in the histogram
histfit(theta,numBins);
title('Angular Frequency');
xlabel('Angle (degrees');
ylabel('Angular Frequency (number of samples)')


figure,
flowerPot = rose(theta, numBins); % plant the angle seed in the flower pot and watch it grow
title('Angular Histogram in a Flower Pot');

%% Circular Statistics
 % These aren't working......
stdev_dist = std(theta); % standard deviation
circVar_rad = cir_var(degtorad(theta)); % circular variance in radians
circVar_deg = radtodeg(circVar_rad); % circular variance in degrees
meanRad = circ_mean(degtorad(theta)); % circular mean in radians
meanDeg = radtodeg(meanRad); % circular mean in degrees

%% Write report
% Will fine tune after figuring out what outputs
[fnm, npth] = uiputfile('*_FFT_align.txt', ...
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

