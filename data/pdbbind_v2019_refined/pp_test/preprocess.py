import glob
import random
from rdkit.Chem import AllChem
from scipy import sparse
import numpy as np
from multiprocessing import Pool
import time
from rdkit import DataStructs
from rdkit.Chem.Fingerprints import FingerprintMols
from rdkit import Chem
import numpy as np
from scipy.spatial import distance_matrix
import os
import tempfile
from Bio.PDB import *
from Bio.PDB.PDBIO import Select
import pickle
import json
import sys
import multiprocessing
from multiprocessing import Pool


def remove_water(m):
    from rdkit.Chem.SaltRemover import SaltRemover
    remover = SaltRemover(defnData="[O]")
    return remover.StripMol(m)


def count_residue(structure):
    count = 0
    for model in structure:
        for chain in model:
            for residue in chain:
                count+=1
    return count


def extract(ligand, pdb):
    parser = PDBParser()
    if not os.path.exists(pdb) :
        print ('AAAAAAAAAAA')
        return None
    structure = parser.get_structure('protein', pdb)
    ligand_positions = ligand.GetConformer().GetPositions()
    # Get distance between ligand positions (N_ligand, 3) and
    # residue positions (N_residue, 3) for each residue
    # only select residue with minimum distance of it is smaller than 5A
    class ResidueSelect(Select):
        def accept_residue(self, residue):
            residue_positions = np.array([np.array(list(atom.get_vector())) \
                for atom in residue.get_atoms() if 'H' not in atom.get_id()])
            if len(residue_positions.shape) < 2:
                print(residue)
                return 0
            min_dis = np.min(distance_matrix(residue_positions, ligand_positions))
            if min_dis < 5.0:
                return 1
            else:
                return 0
    io = PDBIO()
    io.set_structure(structure)
    fn = 'BS_tmp_'+str(np.random.randint(0,1000000,1)[0])+'.pdb'
    io.save(fn, ResidueSelect())
    m2 = Chem.MolFromPDBFile(fn)
    os.system('rm -f ' + fn)
    return m2


def uff(m):
    Chem.SanitizeMol(m)
    m = Chem.AddHs(m)
    cids = AllChem.EmbedMultipleConfs(m, numConfs=20, )
    cenergy = []
    for conf in cids:
        converged = not AllChem.UFFOptimizeMolecule(m, confId=conf)
        cenergy.append(AllChem.UFFGetMoleculeForceField(m, confId=conf).CalcEnergy())
    min_idx = cenergy.index(min(cenergy))
    m = Chem.RemoveHs(m)
    sdf_name = 'sdf_tmp_' + str(np.random.randint(0, 1000000, 1)[0]) + '.pdb'
    w = Chem.SDWriter(sdf_name)
    w.write(m, min_idx)
    w.close()
    retval =  Chem.SDMolSupplier(sdf_name)[0]
    os.system('rm -f '+sdf_name)
    return retval


def preprocessor(l):
    key = l.split('/')[-1]
    print(key)

    # origin
    data_dir = '../data/'
    if os.path.exists(f'{data_dir}/{key}'):
        return
    ligand_sdf_fn = f'{l}/{key}_ligand.sdf'
    ligand_mol2_fn = f'{l}/{key}_ligand.mol2'
    bs_pdb_fn = f'{l}/{key}_protein.pdb'
    rcsb_ligand_dir = f'../../rcsb_pdb/refined_data/{key}'

    m1 = Chem.SDMolSupplier(ligand_sdf_fn)[0]
    if m1 is None:
        if os.path.exists(rcsb_ligand_dir):
            rcsb_ligand_fn = f'{rcsb_ligand_dir}/{key}.sdf'
            m1 = Chem.SDMolSupplier(rcsb_ligand_fn)[0]
        else:
            print(f'{key} no rcsb ligand sdf!')

    if m1 is None:
        m1 = Chem.MolFromMol2File(ligand_mol2_fn)

    if m1 is None:
        print(f'{key} no mol from sdf and mol2 files!')
        return
            
    m1_uff = uff(m1)
    if m1_uff is None:
        print(f'{key} no uff mol from ligand mol!')
        return

    # extract binding pocket
    m2 = extract(m1, bs_pdb_fn)
    if m2 is None :
        print(f'{key} no extracted binding pocket!')
        return
    m2 = remove_water(m2)

    if len(m1.GetConformers())==0:
        return
    if len(m2.GetConformers())==0:
        return
    with open(f'{data_dir}/{key}', 'wb') as fp:
        pickle.dump((m1, m1_uff, m2, []), fp, pickle.HIGHEST_PROTOCOL)
    return


def run(l):
    try:
        return preprocessor(l)
    except:
        return


fn = 'test.txt'
path = '../../CASF-2016/coreset/'
with open(fn, 'r') as r:
    keys = r.readlines()
    keys = [k.split()[0] for k in keys]
    keys = [path+k for k in keys]

pool = Pool(4)
r = pool.map_async(run, keys)
r.wait()
pool.close()
pool.join()
