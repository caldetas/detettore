#!/usr/bin/env python3
# -*- coding: utf-8 -*-


""" Combine single sample vcf files

Adds new INFO fields:
    
    #QD: quality by depth
    AC: allele count
    AF: allele frequency
    NHET: number of heterozygous genotypes
    
      
class args:
    def __init__(self):
        
        self.vcf_path = '/home/cristobal/TB/analyses/detettore/tb_1227_v2/vcfs'
        #self.vcf_path = '/home/cristobal/TB/analyses/detettore/benchmark/simReads_Modlin/detettore'
        self.filters =  ['require_DR_and_SR', 'no_het']
        self.keep_invariant = True
              
args = args()

   
Created on Thu Jun 17 11:46:10 2021
@author: cristobal

"""

import argparse
import gzip
import os
import re
import sys
import time


def get_args():

    parser = argparse.ArgumentParser(
        description='Detect TE polymorphisms from paired-end read data',
        formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument(
        "-p",
        dest="vcf_path",
        required=True,
        help='Path to folder containing vcf.gz output of detettore.')

    parser.add_argument(
        '--keep_invariant',
        action='store_true',
        help='Keep invariant sites.')
    
    parser.add_argument(
        "-f",
        dest="filters",
        nargs='+', 
        choices=['require_split', 'no_het', 'require_DR_and_SR'],
        
        help='Apply filters:\n\
        require_split: only keep genotypes with split read support\n\
        no_het: discard heterozygous genotypes\n\
        require_DR_and_SR: only keep genotypes supported by both discordant read pairs and split reads')

    args=parser.parse_args()

    return args



def parse_vcf_lines(handler, sample_order, vard, imprecise, filters):
    
    for line in handler:
        
        try:
            line = line.decode('utf-8')
        except AttributeError:
            pass
        
        if line.startswith("##"):
            continue

        fields = line.strip().split('\t')
        
        if line.startswith('#CHROM'):
            sample = fields[-1]
            sample_order.append(sample)
            continue
        
        
        var_type = fields[4][1:7]
        
        # Filtering
        if var_type == 'INS:ME' and filters:
            
            SR = re.search(r'SR=(.*?);', fields[7]).group(1)
            DR = re.search(r'DR=(.*?);', fields[7]).group(1)
            
            if 'require_split' in filters and SR == '0':
                continue
            
            if 'require_DR_and_SR' in filters and (SR == '0' or DR == '0'):
                continue
            
        gt = fields[9].split(':')[0]
        if 'no_het' in filters and gt == '0/1':
            continue
        
        chromosome, pos = fields[0], int(fields[1])
        
        meinfo = re.search(r'MEINFO=(.*?);', fields[7]).group(1)
        te = meinfo.split(',')[0]  
        uniq_id = (chromosome, pos, te)
        
        imprec = True if 'IMPRECISE' in fields[7] else False
        
    
        # TAPs and precise TIPs
        if (var_type == 'DEL:ME') or (var_type == 'INS:ME' and not imprec):
            
            if uniq_id not in vard[var_type]:
                
                vard[var_type][uniq_id] = {}
            
            vard[var_type][uniq_id][sample] = fields
            
        # Imprecise into separate list
        elif imprec:
            
            imprecise.append((sample, fields))
    
    
#%% MAIN
def main():

    args = get_args()
    
    filters = args.filters if args.filters else []
    
    #%% Load variants
    vard = { 'INS:ME' : {}, 'DEL:ME' : {} }
    
    sample_order = []
    imprecise = []
    
    for subdir, dirs, files in os.walk(args.vcf_path):
        
        for f in files:
                   
            if f.endswith('.vcf.gz'):
                handler = gzip.open(subdir + '/' + f)
                
            elif f.endswith('.vcf'):
                handler = open(subdir + '/' + f)
             
            else: 
                continue
            
            parse_vcf_lines(handler, sample_order, vard, imprecise, filters)
            
            handler.close()
                
            
    #%% Add imprecise variants
    
    """
    Join if the confidence interval of their position (CIPOS) overlaps with 
    precise or other imprecise variants    
    """        
                  
    for sample, fields in imprecise:
            
        chromosome, pos = fields[0], int(fields[1])                    
        meinfo = re.search(r'MEINFO=(.*?);', fields[7]).group(1)
        te = meinfo.split(',')[0]
        
        cipos = re.search(r'CIPOS=(.*?);', fields[7]).group(1).split(',')
    
        closest = [int(), float('inf')]
           
        for i in range(int(cipos[0]), int(cipos[1])):
            
            if (chromosome, i, te) in vard['INS:ME']:
                
                if abs(pos-i) < closest[1]:
                    closest[0] = i
                    closest[1] = abs(pos-i)
                    
        if closest[0]:
            vard['INS:ME'][(chromosome, closest[0], te)][sample] = fields
     
        else:
            vard['INS:ME'][(chromosome, pos, te)] = {sample : fields}
                

    #%% Write combined vcf
    """
    New INFO fields:
        
        QD: quality by depth
        AC: allele count
        AF: allele frequency
    
    """
    
    metainfo = [
        '##fileFormat=VCFv4.2',
        '##fileDate=%s' % time.strftime("%d/%m/%Y"),
        '##source==detettore v2.0 combineVCF',

        '##INFO=<ID=MEINFO,Number=4,Type=String,Description="Mobile element info of the form NAME,START,END,POLARITY">',
        '##INFO=<ID=AC,Number=1,Type=Integer,Description="Allele count">',
        '##INFO=<ID=AF,Number=1,Type=Integer,Description="Allele frequency">',
        '##INFO=<ID=NHET,Number=1,Type=Integer,Description="Number of heterozygous genotypes">',
     
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
        '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">',
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths for the ref and alt alleles in the order listed">',
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Approximate read depth">',

        '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t%s' % ('\t'.join(sample_order))
        
        ]
    
    
    combined = []
    
    for var_type in ['DEL:ME', 'INS:ME']:
        
        for site in vard[var_type]:
            
            variants = vard[var_type][site]
            samples = list(variants.keys())
    
            # Fields 1-5 do not change
            outline = variants[samples[0]][:5]
            
            # Only INS:ME in ALT field for insertions, rather than element family,
            # which SNPeff cannot parse
            # if var_type == 'INS:ME':
            #     outline[4] = 1000*'N'
            
            # allele count and frequency
            genotypes = []
            
            for sample in sample_order:
                if sample in variants:
                    #GT = variants[sample][9]
                    GT = variants[sample][9].split(':')[0]
                    
                else:
                    #GT = '0/0:.:.,.:.'
                    GT = '0/0'
                    
                genotypes.append(GT)
            
            genotypes_str = [x.split(':')[0] for x in genotypes]
            NHET = genotypes_str.count('0/1')
        
            ref = ''.join(genotypes_str).count('0')
            AC = ''.join(genotypes_str).count('1')
            
            # All missing
            if AC + ref == 0:
                continue
            
            # Invariant sites
            if AC == 0 and not args.keep_invariant:
                continue
        
            AF = AC / (AC + ref)
            
            INFO = 'MEINFO=%s;AC=%i;AF=%f;NHET=%s' % \
                (site[2], AC, AF, NHET)
            
        
            #outline = outline + [str(QUAL), 'PASS', INFO, 'GT:GQ:AD:DP'] + genotypes
            outline = outline + ['.', 'PASS', INFO, 'GT'] + genotypes
            
            combined.append(outline)
        
    combined = sorted(combined, key=lambda x: (x[0], int(x[1])))  
    

    #%% Write to stdout
    
    for line in metainfo:
        sys.stdout.write(line + '\n')
        
    for line in combined:
        sys.stdout.write('\t'.join(line) + '\n')
        
        
if __name__ == '__main__':
    main()




#%% Verworfnes
# class detettore_vcf:
    
#     def __init__(self, vcf_path):
        
#         self.TIPs = {}
#         self.TAPs = {}
#         self.stats = {}
        
#         with gzip.open(vcf_path) as handler:
            
#             for line in handler:
        
#                 try:
#                     line = line.decode('utf-8')
#                 except AttributeError:
#                     pass
        
#                 if line.startswith("#"):
#                     continue

#                 fields = line.strip().split('\t')

#                 var_type = fields[4][1:7]

#                 chromosome, pos = fields[0], int(fields[1])
#                 meinfo = re.search(r'MEINFO=(.*?);', fields[7]).group(1)
#                 te = meinfo.split(',')[0]  
#                 uniq_id = (chromosome, pos, te)
                
#                 imprec = True if 'IMPRECISE' in fields[7] else False

#                 # INFO fields
#                 info = fields[7].split(';')
#                 info_d = {}
#                 for x in info:
#                     parts = x.split('=')
#                     info_d[parts[0]] = parts[1] if len(parts) == 2 else 'NA'

#                 # GT fields
#                 gt = fields[9].split(':')
#                 gt_d = {
#                     'GT' : gt[0],
#                     'GQ' : int(gt[1]),
#                     'AD_REF' : int(gt[2].split(',')[0]),
#                     'AD_ALT' : int(gt[2].split(',')[1]),
#                     'DP' : int(gt[3])
#                     }
                
#                 if var_type == 'INS:ME':
#                     self.TIPs[uniq_id] = (info_d, gt_d, imprec)
#                 else:
#                     self.TAPs[uniq_id] = (info_d, gt_d)
                    
  
    
# vcf_path = '/home/cristobal/TB/analyses/detettore/tb_1227_v2/vcfs'
# sample_d = {}

# for subdir, dirs, files in os.walk(vcf_path):
        
#         for f in files:
                   
#             if f.endswith('.gz'):
#                 sample = f.split('.')[0]
#                 sample_d[sample] = detettore_vcf(subdir + '/' + f)




# # Join genotypes
# vard = { 'INS:ME' : {}, 'DEL:ME' : {} }
# sample_order = []
# imprecise = []

# for sample in sample_d:
    
#     for uniq_id in sample_d[sample].TIPs:
        
#         info = sample_d[sample].TIPs[uniq_id][0]
#         gt = sample_d[sample].TIPs[uniq_id][1]
#         imprec = sample_d[sample].TIPs[uniq_id][2]
        
        
#         if imprec:
                       
            
        
        
        
        
#         if uniq_id not in vard['INS:ME']:
                
#                 vard[var_type][uniq_id] = {}
            
#             vard[var_type][uniq_id][sample] = fields
        
        
                
        
        
        
        
#     for uniq_id in sample_d[sample].TAPs:
        
        

