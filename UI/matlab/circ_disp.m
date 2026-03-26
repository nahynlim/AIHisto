function [ang_var, ang_dev] = circ_disp(dta)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%%  [ang_var, ang_dev] = circ_disp(dta)
%%------------------------------------------------
%%DESCRIPTION:
%%   Calculates the circular dispersion
%%================================================
%%INPUT:
%%  dta  -  [MxN] each row is a sample, each
%%                column a different angle (deg)
%%OUTPUT:
%%  ang_var -  [3xN] circular variance (rad^2)
%%%                  angular variance (rad^2)
%%                   standard variance (rad^2)
%%  ang_dev - [2xN] angular deviation (deg)
%%                  circ stnd dev  (deg)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
    
[M,N] = size(dta);
 
%Y = sum(sind(dta))./M;
Y = nanmean(sind(dta));
%X = sum(cosd(dta))./M;
X = nanmean(cosd(dta));

R = sqrt(X.^2 + Y.^2);

ang_var(1,:) = 1 - R;
ang_var(2,:) = 2*(1-R);
ang_var(3,:) = -2*log(R);

ang_dev(1,:) = 180/pi*sqrt(2*(1-R.^2));
ang_dev(2,:) = 180/pi*sqrt(-2*log(R));

return;
