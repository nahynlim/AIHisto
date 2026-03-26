function txtfile = write_angles(theta,rfnm,pth,windowSize,x_pos,y_pos,pixArea,pixScale)
% This function writes the angles found from the FFT_align function to a
% .txt file
               
                    
SHGangles = fullfile(pth,[rfnm,'_SHGangles.txt']);
% format to output txt
angles_header(1,1) = {sprintf('%%SHG Fiber Angles')};
angles_header(2,1) = {sprintf('%%Sample name:\t%s',rfnm)};
angles_header(3,1) = {sprintf('%%Bundlesize:\twidth(pix): %.0f\theight(pix): %.0f',[windowSize])};
angles_header(4,1) = {sprintf('%%Pixels/um:\t%.3f',pixScale)};
angles_header(5,1) = {sprintf('%%Cropped Area (pix):\t%.0f',pixArea)};
angles_header(6,1) = {sprintf('%%x_pos\ty_pos\ttheta (deg)')};
angles_report = {sprintf(['%.0f\t%.0f\t%.3f\n'],[x_pos y_pos theta]')};
                             
                         
% rpt_txt = [head_txt; dt_report];
angles_txt = [angles_header; angles_report];

% write report to folder
write_report(angles_txt,SHGangles);

end