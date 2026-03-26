function txtfile = write_report(rpt_txt, txtfile)
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% txtfile = write_report(rpt_txt, txtfile)
%%------------------------------------------------
%%DESCRIPTION:
%%  Writes the report text to file (ASCII
%% tab-delimited text file)
%%================================================
%%INPUT:
%% rpt_txt  - [Nx1] cell string with report text
%% txtfile  -  txtfile
%%                default = uigetfile
%%OUTPUT:
%% txtfile  -  output text file
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


if(nargin<2)
  [fnm,pth] = uiputfile('*.txt','Choose output file');
  if(fnm==0)
    return;
  end
  txtfile = fullfile(pth,fnm);
end


fid = fopen(txtfile,'wt');
for(i=1:length(rpt_txt))
  fprintf(fid,'%s\n',char(rpt_txt(i)));
end
fclose(fid);


disp(sprintf('Report written to file: %s',txtfile));

return;

