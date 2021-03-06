import os, sys
import time
import argparse
import numpy as np
import torch
from torch.utils.data import TensorDataset, DataLoader
from tqdm import tqdm
from scipy.sparse import coo_matrix

from .models import deephic

from .utils.io import spreadM, together

def dataloader(data, batch_size=64):
    inputs = torch.tensor(data['data'], dtype=torch.float)
    inds = torch.tensor(data['inds'], dtype=torch.long)
    dataset = TensorDataset(inputs, inds)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)
    return loader

def data_info(data):
    indices = data['inds']
    compacts = data['compacts'][()]
    sizes = data['sizes'][()]
    return indices, compacts, sizes

get_digit = lambda x: int(''.join(list(filter(str.isdigit, x))))
def filename_parser(filename):
    info_str = filename.split('.')[0].split('_')[2:-1]
    chunk = get_digit(info_str[0])
    stride = get_digit(info_str[1])
    bound = get_digit(info_str[2])
    scale = 1 if info_str[3] == 'nonpool' else get_digit(info_str[3])
    return chunk, stride, bound, scale

def deephic_predictor(deephic_loader, ckpt_file, scale, res_num, device):
    deepmodel = deephic.Generator(scale_factor=scale, in_channel=1, resblock_num=res_num).to(device)
    if not os.path.isfile(ckpt_file):
        ckpt_file = f'save/{ckpt_file}'
    deepmodel.load_state_dict(torch.load(ckpt_file))
    print(f'Loading DeepHiC checkpoint file from "{ckpt_file}"')
    result_data = []
    result_inds = []
    deepmodel.eval()
    with torch.no_grad():
        for batch in tqdm(deephic_loader, desc='DeepHiC Predicting: '):
            lr, inds = batch
            lr = lr.to(device)
            out = deepmodel(lr)
            result_data.append(out.to('cpu').numpy())
            result_inds.append(inds.numpy())
    result_data = np.concatenate(result_data, axis=0)
    result_inds = np.concatenate(result_inds, axis=0)
    deep_hics = together(result_data, result_inds, tag='Reconstructing: ')
    return deep_hics

def save_data_n(key, deep_hics, compacts, sizes, high_res, out_dir):
    file = os.path.join(out_dir, f'predict_chr{key}_{high_res}.npz')
    save_data(deep_hics[key], compacts[key], sizes[key], file)

def save_data(deep_hic, compact, size, file):
    deephic = spreadM(deep_hic, compact, size, convert_int=False, verbose=True)
    np.savez_compressed(file, hic=deephic, compact=compact)
    print('Saving file:', file)

def predict(data_dir, out_dir, lr=40000, hr=10000, ckpt_file=None):
    print('WARNING: Predict process needs large memory, thus ensure that your machine have enough memory.')

    # IMPORTANT: The number of Resblock layers[default:5]' in all_parser.py
    res_num = 5
    high_res = str(hr)
    low_res = str(lr)
    in_dir = data_dir
    os.makedirs(out_dir, exist_ok=True)

    files = [f for f in os.listdir(in_dir) if f.find(low_res) >= 0]
    deephic_file = [f for f in files if f.find('.npz') >= 0][0]

    chunk, stride, bound, scale = filename_parser(deephic_file)
    cuda = 0
    device = torch.device(f'cuda:{cuda}' if (torch.cuda.is_available() and cuda>-1 and cuda<torch.cuda.device_count()) else 'cpu')
    print(f'Using device: {device}')
    
    start = time.time()
    print(f'Loading data[DeepHiC]: {deephic_file}')
    deephic_data = np.load(os.path.join(in_dir, deephic_file), allow_pickle=True)
    deephic_loader = dataloader(deephic_data)
    
    indices, compacts, sizes = data_info(deephic_data)
    deep_hics = deephic_predictor(deephic_loader, ckpt_file, scale, res_num, device)

    print(f'Start saving predicted data')
    print(f'Output path: {out_dir}')
    for key in compacts.keys():
        save_data_n(key,deep_hics, compacts, sizes, high_res, out_dir)
    
    print(f'All data saved. Running cost is {(time.time()-start)/60:.1f} min.')