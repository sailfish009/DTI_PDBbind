import argparse
import utils
import random
random.seed(0)
import numpy as np
from dataset import MolDataset, DTISampler, my_collate_fn
from torch.utils.data import DataLoader                                     
from model import DTIPredictor
import os
import torch
import time
import torch.nn as nn
import pickle
from sklearn.metrics import r2_score, roc_auc_score
from collections import Counter
import sys
import glob

parser = argparse.ArgumentParser() 
parser.add_argument('--lr', help="learning rate", type=float, default = 1e-4)
parser.add_argument("--lr_decay", help="learning rate decay", type=float, default=1.0)
parser.add_argument("--weight_decay", help="weight decay", type=float, default = 0.0)
parser.add_argument('--num_epochs', help='number of epochs', type = int, default = 10000)
parser.add_argument('--batch_size', help='batch size', type = int, default = 1)
parser.add_argument('--num_workers', help = 'number of workers', type = int, default = 7) 
parser.add_argument('--dim_gnn', help = 'dim_gnn', type = int, default = 32) 
parser.add_argument("--n_gnn", help="depth of gnn layer", type=int, default = 3)
parser.add_argument('--ngpu', help = 'ngpu', type = int, default = 1) 
parser.add_argument('--save_dir', help = 'save directory', type = str) 
parser.add_argument('--restart_file', help = 'restart file', type = str) 
parser.add_argument('--filename', help='filename', \
        type = str, default='/home/wykgroup/jaechang/work/data/pdbbind_v2016_refined-set/index/INDEX_refined_data.2016')
parser.add_argument('--train_output_filename', help='train output filename', type = str, default='train.txt')
parser.add_argument('--test_output_filename', help='test output filename', type = str, default='test.txt')
parser.add_argument('--key_dir', help='key directory', type = str, default='keys')
parser.add_argument('--data_dir', help='data file path', type = str, default='../data_pdbbind/data/')
parser.add_argument("--filter_spacing", help="filter spacing", type=float, default=0.1)
parser.add_argument("--filter_gamma", help="filter gamma", type=float, default=10)
parser.add_argument("--dropout_rate", help="dropout rate", type=float, default=0.0)
parser.add_argument("--loss2_ratio", help="loss2 ratio", type=float, default=1.0)

args = parser.parse_args()
print (args)

#Make directory for save files
os.makedirs(args.save_dir, exist_ok=True)

#Read labels
with open(args.filename) as f:
    lines = f.readlines()[6:]
    lines = [l.split() for l in lines]
    id_to_y = {l[0]:float(l[3]) for l in lines}

with open(args.key_dir+'/train_keys.pkl', 'rb') as f:
    train_keys = pickle.load(f)
with open(args.key_dir+'/test_keys.pkl', 'rb') as f:
    test_keys = pickle.load(f)


#Model
cmd = utils.set_cuda_visible_device(args.ngpu)
os.environ['CUDA_VISIBLE_DEVICES']=cmd[:-1]
model = DTIPredictor(args)
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
model = utils.initialize_model(model, device, args.restart_file)

print ('number of parameters : ', sum(p.numel() for p in model.parameters() if p.requires_grad))

#Dataloader
train_dataset = MolDataset(train_keys, args.data_dir, id_to_y)
train_data_loader = DataLoader(train_dataset, args.batch_size, \
		num_workers = args.num_workers, \
		collate_fn=my_collate_fn, shuffle=True)
test_dataset = MolDataset(test_keys, args.data_dir, id_to_y)
test_data_loader = DataLoader(test_dataset, args.batch_size, \
     shuffle=False, num_workers = args.num_workers, collate_fn=my_collate_fn)

#Optimizer and loss
optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, \
                             weight_decay=args.weight_decay)
loss_fn = nn.MSELoss()


#train
for epoch in range(args.num_epochs):
    st = time.time()
    
    train_losses1 = []
    train_losses2 = []
    test_losses1 = []
    test_losses2 = []
    
    train_pred1 = dict()
    train_pred2 = dict()
    train_true = dict()
    
    test_pred1 = dict()
    test_pred2 = dict()
    test_true = dict()
    
    model.train()
    for i_batch, sample in enumerate(train_data_loader):
        model.zero_grad()
        if sample is None : continue
        H1, A1, H2, A2, DM, DM_rot, V, Y, keys = sample

        H1, A1, H2, A2, DM, DM_rot, V, Y = \
                H1.to(device), A1.to(device), H2.to(device), A2.to(device), \
                DM.to(device), DM_rot.to(device), \
                V.to(device), Y.to(device)
        pred1 = model(H1, A1, H2, A2, DM, V)
        pred2 = model(H1, A1, H2, A2, DM_rot, V)
        #print ('pred1', torch.max(pred1), torch.min(pred1)) 
        #print ('pred2', torch.max(pred2), torch.min(pred2)) 
        loss1 = loss_fn(pred1, Y)
        loss2 = torch.mean(torch.max(torch.zeros_like(pred2), pred1.detach()-pred2+10))
        loss = loss1+loss2*args.loss2_ratio
        
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)

        optimizer.step()
        train_losses1.append(loss1.data.cpu().numpy())
        train_losses2.append(loss2.data.cpu().numpy())
        Y = Y.data.cpu().numpy()
        pred1 = pred1.data.cpu().numpy()

        for i in range(len(keys)):
            train_pred1[keys[i]] = pred1[i]
            train_pred2[keys[i]] = pred2[i]
            train_true[keys[i]] = Y[i]
            #if pred1[i]>0: print (keys[i], pred1[i], Y[i])
    
    model.eval()
    for i_batch, sample in enumerate(test_data_loader):
        model.zero_grad()
        if sample is None : continue
        H1, A1, H2, A2, DM, DM_rot, V, Y, keys = sample

        H1, A1, H2, A2, DM, DM_rot, V, Y = \
                H1.to(device), A1.to(device), H2.to(device), A2.to(device), \
                DM.to(device), DM_rot.to(device),\
                V.to(device), Y.to(device)
        with torch.no_grad(): 
            pred1 = model(H1, A1, H2, A2, DM, V)
            pred2 = model(H1, A1, H2, A2, DM_rot, V)

        loss1 = loss_fn(pred1, Y)
        loss2 = torch.mean(torch.max(torch.zeros_like(pred2), pred1.detach()-pred2+10))
        loss = loss1+loss2
        test_losses1.append(loss1.data.cpu().numpy())
        test_losses2.append(loss2.data.cpu().numpy())
        Y = Y.data.cpu().numpy()
        pred1 = pred1.data.cpu().numpy()

        for i in range(len(keys)):
            test_pred1[keys[i]] = pred1[i]
            test_pred2[keys[i]] = pred2[i]
            test_true[keys[i]] = Y[i]

    #Write prediction
    w_train = open(args.train_output_filename, 'w')
    w_test = open(args.test_output_filename, 'w')
    
    for k in train_pred1.keys():
        w_train.write(f'{k}\t{train_true[k]}\t{train_pred1[k]}\t{train_pred2[k]}\n')
    for k in test_pred1.keys():
        w_test.write(f'{k}\t{test_true[k]}\t{test_pred1[k]}\t{test_pred2[k]}\n')
    end = time.time()
    
    w_train.close()
    w_test.close()

    #Cal loss
    train_losses1 = np.mean(np.array(train_losses1))
    train_losses2 = np.mean(np.array(train_losses2))
    test_losses1 = np.mean(np.array(test_losses1))
    test_losses2 = np.mean(np.array(test_losses2))

    #Cal R2
    train_r2 = r2_score([train_true[k] for k in train_true.keys()], \
            [train_pred1[k] for k in train_true.keys()])
    test_r2 = r2_score([test_true[k] for k in test_true.keys()], \
            [test_pred1[k] for k in test_true.keys()])
    

    end = time.time()
    print ("%s\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f" \
        %(epoch, train_losses1, train_losses2, \
        test_losses1, test_losses2, train_r2, test_r2, end-st))
    
    name = args.save_dir+'/save_'+str(epoch)+'.pt'
    torch.save(model.state_dict(), name)
    
    lr = args.lr * ((args.lr_decay)**epoch)
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr             
