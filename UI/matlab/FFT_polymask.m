function poly_pos = FFT_polymask(image)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% ABOUT

% Author: Ashley Rodriguez
% Date: 11/17/2016
% Date Modified: 12/14/2016
% Description: This function reads in an image, and has the user draw a polygon around a
% region of interst. The position of the ROI is then saved for additional
% processing.

%% INPUTS:
    % *SHG image file
    
%% OUTPUTS:
    % *SHG_msk.tiff
    
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


%% Load original image and save w/ different suffix


% Hfig = findobj('tag','shg-poly-fig');
% if(isempty(Hfig))
%     Hfig = figure('tag','shg-poly-fig', ...
%                   'FileName', fullfile(pwd,'*.tif'));
%     
% end

if (nargin < 1)
%     def_file = get(Hfig,'FileName');
    [n_fnm, n_pth] = uigetfile('*c004.tif',...
                 'Choose SHG image');
               
   if (n_fnm ==0)
       uiwait(warndlg('Feeling empty inside? Eat a cookie.'));
       return;
   end
   
   eg_file1 = fullfile(n_pth,n_fnm);
   
else 
   
end
 

  
% Load all c002 and c005 images from directory to be used in subplot
Sdir_c004 = dir(fullfile(n_pth,'*c004.tif'));
Sdir_c005 = dir(fullfile(n_pth,'*c005.tif'));

fnames_c004 = {Sdir_c004.name};
fnames_c005 = {Sdir_c005.name};

for i = 1:length(fnames_c004);
    
    filename_c004(i,1) = {fullfile(n_pth,char(fnames_c004{i}))};
    filename_c005(i,1) = {fullfile(n_pth,char(fnames_c005{i}))};
end

    
   
% match same stack with collagen channel
   
%    stack_idx = strfind(n_fnm1,'c')+3;
% %    stack_num = n_fnm1(stack_idx:stack_idx+3); % z00#
%    
%    n_fnm2 = n_fnm1;
%    n_fnm2(stack_idx) = '5';
   
%     [n_fnm2, n_pth2] = uigetfile(c5_filter,...
%                  'Choose collagen channel image');
               
%    if (n_fnm2 ==0)
%        uiwait(warndlg('Feeling empty inside? So is this program.'));
%        return;
%    end
%    
%    eg_file2 = fullfile(n_pth,n_fnm2);
    

% Masking will always be on 2nd image
A = imread(filename_c004{2});
B = imread(filename_c005{2});

eg_file = imfuse(A,B);

% shg_image = imread(eg_file);
% set(Hfig,'FileName',eg_file);
% shg_image = imread(eg_file);

%% Show the goods
answer  = 'No'; % set initial while loop parameter

while strcmp(answer,'No');
    
    close all
    
    g = figure('Color',[0 0 0]);
    figure(g)
    imshow(eg_file);

    uiwait(msgbox('Draw ROI around injury site (or whatever for uninj)'));
    hold on
    Hply = impoly;
    poly_pos = wait(Hply);
    delete(Hply);
    hold on;
    plot(poly_pos([1:end,1],1), poly_pos([1:end,1],2),'r+-');

    fft_mask = roipoly(eg_file, poly_pos(:,1), poly_pos(:,2));

    cmsk = poly_pos(:,1);
    rmsk = poly_pos(:,2);
    
     h = figure('Color',[1 1 1]);
    
    for j = 1:length(filename_c004)
        
        if length(filename_c004) < 6
            nrow = 2;
        else
            nrow = 3;
        end
        img_c004 = imread(filename_c004{j});
        img_c005 = imread(filename_c005{j});
        shg_fuse = imfuse(img_c004,img_c005);
        
        %     hold on;
        figure(h)
        subplot(nrow,2,j);
        imshow(shg_fuse);
        %     pos = get(gca,'Position');
        %     set(gca,'Position',[pos(1)-0.01, pos(2)-0.01, pos(3)+0.25, pos(4)+0.1]);
        hold on
        plot(poly_pos([1:end,1],1), poly_pos([1:end,1],2),'r+-');
        title(['Z= ' num2str(j)],'fontname','Segoe UI Light','fontsize',12)
        
    end
    
    
    % ask user if satisfied with mask
    qstring = 'Are you satisfied with your masking skills?';
    answer = questdlg(qstring,'How''d you do?', ...
            'Yes','No','No');
        
    if strcmp(answer,'Yes')
        continue;
    
    end
end


% imTmsk = roipoly(xG, yG, imP2P, poly_pos(:,1), poly_pos(:,2));
 
% rename
%regexp(); 
%% Save the mask position

% % Header Information
head_txt(1,1) = {sprintf('SHG mask position')};
head_txt(2,1) = {sprintf('%%Date:\t%s', ...
                         datestr(now, 'yyyy.mm.dd'))};
head_txt(3,1) = {sprintf('Column index\tRow index')};

% Output data to string
data_txt(1,1) = {sprintf('%.2f\t%.2f\n', poly_pos')};
% data_txt(1,2) = {sprintf('%.2f\n', poly_pos(:,2))};

% % output_txt = [head_txt; csd_txt; data_txt];
output_txt = [head_txt; data_txt];
% 

% % Write Data to .txt File
[ nfnm, npth ] = uiputfile('*_FFTmsk.txt', ...
                        'Choose Output File');%, ...
                        %SHG_align_file);
if(nfnm == 0)
    warndlg(':( Not saving. You worked so hard!');
    return;
end

FFT_mask_file = fullfile(npth ,nfnm);

write_report(output_txt, FFT_mask_file);



