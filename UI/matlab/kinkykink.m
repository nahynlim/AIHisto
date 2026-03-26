function [] = kinkykink()

%% About

% Reads back in SHG image with *_SHGangles.txt file to fit quiver back to
% it

%% Load Images
[fnm_image pth_image] = uigetfile('*_c005.tif', 'Select collage channel for SHG Image')

    if (fnm_image ==0)
        uiwait(warndlg('You''re doing it wrong!'));
        return;
    end

image_file = fullfile(pth_image,fnm_image);

%% Load Angle files
pth_guess = regexprep(pth_image,'Cropped1','SHG mask'); %now, smarter
[fnm_angles pth_angles] = uigetfile(strcat('*_', fnm_image(14:end-4),'_SHGangles.txt'), 'Select _SHGangles.txt file',pth_guess)

    if (fnm_angles ==0)
        uiwait(warndlg('Nope! Wrong!'));
        return;
    end

angles_file = fullfile(pth_angles,fnm_angles);
dT = load(angles_file);


theta = dT(:,3);

%% Bundle an image

bundleSize = [15 15];
pout = imread(image_file);
pout_tiles= mat2tiles(pout, bundleSize);

% Determine coordinates of future quiver plot
% Note that arrow origin is at left boundary of subregion
[row, col] = size(pout_tiles);
imageDim = size(pout);
X=0:bundleSize(2):imageDim(2);
% if length(X)<size(BW_tiles,2)
%     X=cat(2,X,X(end)+windowSize(2));    % In case tiling image produces residual tiles
% end
Y=bundleSize(1)/2:bundleSize(2):imageDim(1);

[x, y] = meshgrid(X,Y); % x and y coordinates for meshgrid
theta_mat = reshape(theta,[row,col])

%% Find u and v for quiver

arrowLength =  15;
u = arrowLength*cosd(theta_mat); % horizontal arrow component for quiver 
v = -arrowLength*sind(theta_mat); % vertical arrow component for quiver (neg sign is due to yaxis pointing down in image)

u(end,:) = [];
v(end,:) = [];
%% Make a quiver

qPlot = figure;
imshow(pout);
hold on

q = quiver(x, y, u, v, 'ShowArrowHead','on','AutoScale', 'off');
set(q,'Color','g', 'LineWidth',1);
hold off

%construct a line
% h = imline(gca);
% position = wait(h);

    Himr = imline(gca);
    
%     setPosition(Himr, get(Hrct,'Position'))
    
    ln_pos = wait(Himr);
    ln_pos = round(ln_pos);
    delete(Himr);
    
     Hln = line(ln_pos(:,1),ln_pos(:,2), 'color','yellow');
% setColor(h,[1 0 0]);
% id = addNewPositionCallback(h,@(pos) title(mat2str(pos,3)));
% removeNewPositionCallback(h,id);

%transform line position from 1024x1024 to 69x69
corr_fact = length(pout_tiles(:,1)) / length(pout(:,1));
ln_pos_corr = round(ln_pos./corr_fact);

a = ln_pos_corr(1,:);
b = ln_pos_corr(2,:);
m = (a(2) - b(2)) / (a(1) - b(1));
n = b(2) - b(1) * m;

x = min(a(1), b(1)) : max(a(1), b(1));
y = m * x + n;
y = round(y);

for i = 1 : length(x)
    result(i,:) = [x(i), y(i)];
end

vect_ln = theta_mat(result);
% x_sel = ln_pos(:,1);
% y_sel = ln_pos(:,2);
%improfile
% dT_ln = improfile(theta_mat,x_sel, y_sel);
% dT_ln = improfile(theta_mat,20, 10);


end

