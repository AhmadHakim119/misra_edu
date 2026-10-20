"""Local PDF redaction drafts. Original files and non-mask rendered pixels survive.

Colour separation is a candidate mask, never proof of teacher/student authorship.
No inpainting, guessed handwriting, live OCR or automatic readiness approval.
"""
import cv2
import numpy as np
from PIL import Image
from pypdf.generic import (DecodedStreamObject, DictionaryObject,
    NameObject, NumberObject)


def _box_mask(size,boxes):
    """Explicit normalized regions only; no inferred teacher/student ownership."""
    width,height=size;result=np.zeros((height,width),dtype=bool)
    for box in boxes:
        if not isinstance(box,(list,tuple)) or len(box)!=4:
            raise ValueError('A reviewed region needs x, y, width and height.')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) for v in box):
            raise ValueError('Region coordinates must be finite numbers.')
        x,y,w,h=box
        if min(x,y)<0 or min(w,h)<=0 or x+w>1 or y+h>1:
            raise ValueError('Reviewed regions must stay within the full page.')
        result[int(y*height):min(height,int(np.ceil((y+h)*height))),
               int(x*width):min(width,int(np.ceil((x+w)*width)))]=True
    return result


def redact_reviewed_red_regions(image,regions,*,protected_regions=()):
    """Candidate teacher-ink removal within reviewed regions, preserving diagrams.

    A protected region always wins. No attempt is made to reconstruct student
    strokes under teacher ink. Any nearby blue/dark ink requires overlap review.
    This function never declares an output ready for inference.
    """
    rgb=np.asarray(image.convert('RGB')).copy();v=rgb.astype(np.int16)
    permitted=_box_mask(image.size,regions)&~_box_mask(image.size,protected_regions)
    red=(v[:,:,0]>30)&(v[:,:,0]-v[:,:,1]>5)&(v[:,:,0]-v[:,:,2]>3)
    # Include a one-pixel antialias fringe, restricted to the reviewed region.
    mask=(cv2.dilate((red&permitted).astype(np.uint8),np.ones((3,3),np.uint8))>0)&permitted
    if float(mask.mean())>.08:raise ValueError('Candidate mask is too broad; review the annotation regions.')
    blue=(v[:,:,2]-v[:,:,0]>10)&(v[:,:,2]-v[:,:,1]>10)
    dark=rgb.max(axis=2)<100
    adjacent=cv2.dilate(mask.astype(np.uint8),np.ones((3,3),np.uint8))>0
    overlap=int(((blue|dark)&adjacent).sum())
    cleaned=rgb.copy();cleaned[mask]=255
    return Image.fromarray(cleaned),Image.fromarray(mask.astype(np.uint8)*255),{
        'ready_for_inference':False,'masked_pixel_count':int(mask.sum()),
        'overlap_review_required':overlap>0,'nearby_student_ink_candidate_count':overlap,
        'protected_pixel_preservation_verified':bool(np.array_equal(cleaned[~permitted],rgb[~permitted])),
        'unmasked_pixel_preservation_verified':bool(np.array_equal(cleaned[~mask],rgb[~mask]))}


def redact_red_ink(image):
    rgb=np.asarray(image.convert('RGB')).copy();values=rgb.astype(np.int16)
    red,green,blue=values[:,:,0],values[:,:,1],values[:,:,2]
    mask=(red>30)&(red-green>=12)&(red-blue>=6)&((red-np.minimum(green,blue))>red*.12)
    fraction=float(mask.mean())
    if fraction>.05:
        raise ValueError('Too much red content for a safe draft mask; review this page manually.')
    # Dark/blue ink adjacent to removed red can indicate an overlap. It must be
    # checked against the original; lost underlying ink cannot be reconstructed.
    dark=(rgb.max(axis=2)<120)&~mask
    nearby=cv2.dilate(mask.astype(np.uint8),np.ones((5,5),np.uint8))>0
    overlap_pixels=int((dark&nearby).sum())
    cleaned=rgb.copy();cleaned[mask]=255
    count,_,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
    regions=[];height,width=mask.shape
    for x,y,w,h,area in stats[1:]:
        if area>=8:regions.append({'x':float(x/width),'y':float(y/height),
            'width':float(w/width),'height':float(h/height),'pixels':int(area)})
    return Image.fromarray(cleaned),Image.fromarray(mask.astype(np.uint8)*255),{
        'red_pixel_count':int(mask.sum()),'red_pixel_fraction':fraction,
        'nearby_dark_pixel_count':overlap_pixels,'overlap_review_required':overlap_pixels>0,
        'candidate_component_count':count-1,'regions':regions,
        'pixel_preservation_verified':bool(np.array_equal(cleaned[~mask],rgb[~mask]))}


def append_lossless_page(writer,image,width,height):
    """New RGB/Flate image PDF page, with no recoverable original-image layer."""
    image=image.convert('RGB');page=writer.add_blank_page(width=width,height=height)
    stream=DecodedStreamObject();stream.set_data(image.tobytes())
    stream.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),
        NameObject('/Width'):NumberObject(image.width),NameObject('/Height'):NumberObject(image.height),
        NameObject('/ColorSpace'):NameObject('/DeviceRGB'),NameObject('/BitsPerComponent'):NumberObject(8)})
    encoded=stream.flate_encode()
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Im0'):writer._add_object(encoded)})})
    content=DecodedStreamObject();content.set_data(f'q {float(width)} 0 0 {float(height)} 0 0 cm /Im0 Do Q'.encode('ascii'))
    page[NameObject('/Contents')]=writer._add_object(content)
    return page
