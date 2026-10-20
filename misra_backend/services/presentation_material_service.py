"""Bounded PPTX text reading with standard-library XML; no macros or external links."""
import re
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

PPTX_TYPE='application/vnd.openxmlformats-officedocument.presentationml.presentation'


def read_slides(path):
    with zipfile.ZipFile(path) as archive:
        items=archive.infolist()
        if len(items)>10000 or sum(item.file_size for item in items)>150*1024*1024:
            raise ValueError('PowerPoint package exceeds the expanded-content limit.')
        if any(item.flag_bits&1 or '..' in PurePosixPath(item.filename).parts or item.filename.startswith('/') or 'vbaProject' in item.filename for item in items):
            raise ValueError('Encrypted, unsafe or macro-enabled presentations are not accepted.')
        def xml(name):
            info=archive.getinfo(name)
            if info.file_size>4*1024*1024:raise ValueError('PowerPoint XML part is too large.')
            data=archive.read(name)
            declarations=data.replace(b'\x00',b'').upper()
            if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:raise ValueError('PowerPoint XML declarations are not supported.')
            return ElementTree.fromstring(data)
        types=xml('[Content_Types].xml')
        if not any(node.attrib.get('ContentType')=='application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml' for node in types):
            raise ValueError('File is not a standard PPTX presentation.')
        rels={node.attrib['Id']:node.attrib for node in xml('ppt/_rels/presentation.xml.rels')}
        presentation=xml('ppt/presentation.xml')
        relation='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
        positions=[node.attrib.get(relation) for node in presentation.iter('{http://schemas.openxmlformats.org/presentationml/2006/main}sldId')]
        if not 1<=len(positions)<=1000 or len(set(positions))!=len(positions):raise ValueError('Choose a presentation with 1–1,000 unique slides.')
        result=[]
        for position in positions:
            link=rels[position];target=link.get('Target','')
            if link.get('TargetMode')=='External' or not re.fullmatch(r'slides/slide\d+\.xml',target):raise ValueError('Presentation slide target is invalid.')
            root=xml('ppt/'+target)
            text='\n'.join(''.join(node.itertext()) for node in root.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t'))
            if len(text)>50000:raise ValueError('Slide text exceeds the reference-page limit.')
            result.append(text)
        return result
