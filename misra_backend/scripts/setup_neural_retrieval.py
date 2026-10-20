"""Explicit public-weight download/provisioning; inference never downloads models."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'misra_backend'))
os.environ.setdefault('DB_URL','sqlite:///:memory:')
from services.neural_retrieval_service import MODELS, file_hash, model_root, verify_model


def validate_converter_version(version):
    """CVE-2026-24747 affects weights_only loaders through PyTorch 2.9.1."""
    match=re.match(r'^(\d+)\.(\d+)',version)
    if not match or tuple(map(int,match.groups())) < (2,10):
        raise ValueError('Embedding checkpoint conversion requires patched PyTorch >=2.10.0. Existing verified safetensors snapshots can run without checkpoint conversion.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download',action='store_true',help='Download pinned public weights; no application/student data is sent.')
    args=parser.parse_args()
    for role,spec in MODELS.items():
        if not args.download:
            verify_model(role);print(role+': pinned local model verified',flush=True);continue
        folder=model_root()/spec['directory']/spec['revision']
        if (folder/'misra-model.json').exists():
            verify_model(role);print(role+': existing verified snapshot',flush=True);continue
        from huggingface_hub import snapshot_download
        weights='pytorch_model.bin' if role=='embedding' else 'model.safetensors'
        names=['config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','sentencepiece.bpe.model','README.md',weights]
        print(role+': downloading exact revision '+spec['revision'],flush=True)
        snapshot_download(spec['id'],revision=spec['revision'],local_dir=folder,allow_patterns=names)
        source_hash=None
        if role=='embedding' and not (folder/'model.safetensors').exists():
            # Upstream BGE-M3 publishes only .bin at this revision. Load official,
            # pinned tensors once with torch's restricted weights-only loader;
            # produce safetensors for all subsequent offline runtime loads.
            import torch
            from safetensors.torch import save_file
            validate_converter_version(torch.__version__)
            source_hash=file_hash(folder/weights)
            tensors=torch.load(folder/weights,map_location='cpu',weights_only=True,mmap=True)
            if not isinstance(tensors,dict) or any(not isinstance(v,torch.Tensor) for v in tensors.values()):
                raise ValueError('Pinned embedding weights are not a plain tensor state dictionary.')
            temporary=folder/'model.safetensors.tmp'
            save_file(tensors,str(temporary),metadata={'format':'pt','source_revision':spec['revision']})
            temporary.replace(folder/'model.safetensors')
            del tensors
        assets=[name for name in names if name not in {'README.md','pytorch_model.bin'}]
        if 'model.safetensors' not in assets:assets.append('model.safetensors')
        manifest={'model':spec['id'],'revision':spec['revision'],'license':spec['license'],
                  'upstream_bin_sha256':source_hash,'files':{name:file_hash(folder/name) for name in assets}}
        with (folder/'misra-model.json').open('x',encoding='utf-8') as stream:json.dump(manifest,stream,indent=2)
        verify_model(role);print(role+': provisioned and verified',flush=True)


if __name__=='__main__':main()
