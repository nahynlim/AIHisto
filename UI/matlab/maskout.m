function masked = maskout(img, mask)

%% mask - mask file, same size as img. Doesn't matter what data type
%% img - original image you wish to mask

%%
masked  = bsxfun(@times, img, cast(mask, class(img)));

end