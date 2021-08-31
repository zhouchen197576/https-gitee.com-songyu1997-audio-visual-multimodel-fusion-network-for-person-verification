import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import math
from data_preprocess import *

from torch.utils import data
from torch.nn.parameter import Parameter
from torch.autograd import Variable


class Gated_Feature_Fusion(nn.Module):
    def __init__(self, d_args):
        super(Gated_Feature_Fusion, self).__init__()
        # DNNs
        self.fc_a = nn.Linear(in_features=1024, out_features=1024)      # 1024,1024
        self.fc_v = nn.Linear(in_features=512,  out_features=1024)      # 512, 1024
        self.fc_att = nn.Linear(in_features=1536,  out_features=1024)   # 1536,1024
        self.fc_out = nn.Linear(in_features=d_args['nb_space_node'], out_features=d_args['nb_classes']) # 1024, 1211/5994
        # BatchNormalizer
        self.bn_a = nn.BatchNorm1d(1024)  
        self.bn_v = nn.BatchNorm1d(512) 
        self.bn_cat = nn.BatchNorm1d(1536) 
        # Dropout
        self.dropout = torch.nn.Dropout(0.5) 
        # loss
        self.LogSoftmax = nn.LogSoftmax(dim=1)  # LogSoftmax与nn.NLLLoss()结合使用,求交叉熵损失

    def forward(self, x, is_test=False):
        x_cat = x             # x_cat.size() 是 torch.Size([16, 1536])  # 以batch size为16为例
        x_a = x[:, 0:1024]    # x_a.size() 是 torch.Size([16, 1024])
        x_v = x[:, 1024:]     # x_v.size() 是 torch.Size([16, 512]) 
        # Batch Normalization操作
        if not is_test:
            x_a = self.bn_a(x_a)
            x_v = self.bn_v(x_v)
            x_cat = self.bn_cat(x_cat)
        # 定义各自的全连接层
        x_A = self.fc_a(x_a)
        x_V = self.fc_v(x_v)
        x_Cat = self.fc_att(x_cat)
        # dropout操作
        x_A = self.dropout(x_A)
        x_V = self.dropout(x_V)
        x_Cat = self.dropout(x_Cat)
        # activation操作
        h_a = torch.tanh(x_A)
        h_v = torch.tanh(x_V)
        z = torch.sigmoid(x_Cat)   # z.size() 是 torch.Size([16, 1024]) 
        # print('z[0,:] 是 {}'.format(z[0,:]))  # tensor([0.5000, 0.5000, 0.7757,  ..., 0.5000, 0.5000, 0.5000]
        #                                       # tensor([0.5000, 0.5000, 0.8208,  ..., 0.6791, 0.2238, 0.5000]
        # print('z[1,:] 是 {}'.format(z[1,:]))  # tensor([0.1821, 0.5000, 0.0757,  ..., 0.5000, 0.5000, 0.5000]  
        #                                       # tensor([0.5000, 0.0149, 0.6856,  ..., 0.0377, 0.5000, 0.5000]
        # gate組合
        E_p = torch.mul(z,h_a) + torch.mul(1-z,h_v)  # 維度是1024
        if not is_test:
            E_p  = self.bn_a(E_p)    #  加上这一行还是有效果
        embedding = E_p.view(E_p.size(0),-1)
        # 对于test，则不需要经过最后一层全连接层（输出层），在这里直接得到person embedding
        if is_test:
            return embedding
        output = self.fc_out(embedding)      # 输入embedding维度为1024，输出out维度为 1211 / 5994
        # output = self.LogSoftmax(output)   # 计算LogSoftmax，后面还需要加NLLLoss
        return embedding, output

class Attention_Feature_Fusion(nn.Module):
    def __init__(self, d_args):
        super(Attention_Feature_Fusion, self).__init__()
        # DNNs
        self.fc_a = nn.Linear(in_features=1024, out_features=1024)  # 1024,1024
        self.fc_v = nn.Linear(in_features=512,  out_features=1024)  # 512,1024
        self.attention = nn.Linear(in_features=1536,  out_features=2)  # 1536,2
        self.fc_out = nn.Linear(in_features=d_args['nb_space_node'], out_features=d_args['nb_classes']) # 1024, 1211/5994
        # BatchNormalizer
        self.bn_a = nn.BatchNorm1d(1024)  
        self.bn_v = nn.BatchNorm1d(512) 
        self.bn_cat = nn.BatchNorm1d(1536) 
        # Dropout
        self.dropout = torch.nn.Dropout(0.5)  # 0.5最優
        # loss
        self.LogSoftmax = nn.LogSoftmax(dim=1)  # LogSoftmax与nn.NLLLoss()结合使用,求交叉熵损失
        self.Softmax = nn.Softmax(dim=1)     # dim=1表示對每一行的所有元素進行softmax計算，並使得每一行所有元素和爲1

    def forward(self, x, is_test=False):
        x_cat = x             # x_cat.size() 是 torch.Size([64, 1536])  # 以batch size为64为例
        x_a = x[:, 0:1024]    # x_a.size() 是 torch.Size([64, 1024])
        x_v = x[:, 1024:]     # x_v.size() 是 torch.Size([64, 512]) 
        # Batch Normalization操作
        if not is_test:
            x_a = self.bn_a(x_a)
            x_v = self.bn_v(x_v)
            x_cat = self.bn_cat(x_cat)
        # 定义各自的全连接层
        x_A = self.fc_a(x_a)
        x_V = self.fc_v(x_v)
        score = self.attention(x_cat)
        # dropout操作
        x_A = self.dropout(x_A)
        x_V = self.dropout(x_V)
        # attention計算
        att_score = self.Softmax(score) # 歸一化  # torch.Size([64, 2])
        score_a = att_score[:, 0]  # torch.Size([64])
        score_b = att_score[:, 1]
        att_score_a = score_a.detach().unsqueeze(dim=1).repeat(1,1024)  # torch.Size([64, 1024])
        att_score_b = score_b.detach().unsqueeze(dim=1).repeat(1,1024)
        E_p = torch.mul(x_A, att_score_a) + torch.mul(x_V, att_score_b) # torch.Size([64, 1024])  
        if not is_test:
            E_p  = self.bn_a(E_p)    #  加上这一行还是有效果
        embedding = E_p.view(E_p.size(0),-1)
        # 对于test，则不需要经过最后一层全连接层（输出层），在这里直接得到person embedding
        if is_test:
            return embedding
        output = self.fc_out(embedding)      # 输入embedding维度为1024，输出out维度为 1211 / 5994
        return embedding, output


class Cat_Feature_Fusion(nn.Module):
    def __init__(self, d_args):
        super(Cat_Feature_Fusion, self).__init__()
        self.fc1 = nn.Linear(in_features=d_args['cat_emb_dim'], out_features=d_args['nb_fc1_node'])  # 1536, 2048
        self.fc2 = nn.Linear(in_features=d_args['nb_fc1_node'], out_features=d_args['nb_fc2_node'])  # 2048, 1024
        self.fc_out = nn.Linear(in_features=d_args['nb_fc2_node'], out_features=d_args['nb_classes']) # 1024, 1211/5994
        self.dropout = torch.nn.Dropout(0.7)  # 這裏設爲0.7最佳
        self.LogSoftmax = nn.LogSoftmax(dim=1)  # LogSoftmax与nn.NLLLoss()结合使用,求交叉熵损失

    def forward(self, x, is_test=False):
        x = self.fc1(x)  # 输入的cat嵌入向量的维度是1536，输出2048
        x = self.dropout(x)
        x = F.relu(x)
        x = self.fc2(x)  # 输入维度2048，输出维度1024
        x = self.dropout(x)
        x = F.relu(x)
        # if not is_test:
        #     x= self.bn_a(x)    #  加上这一行还是有效果
        embedding = x.view(x.size(0),-1)
        # 如果用于test，则不需要经过最后一层全连接层（输出层），直接得到embedding用作比较
        if is_test:
            return embedding
        output = self.fc_out(embedding)     # 输入1024，输出维度1211 / 5994
        return embedding, output


       




# class FeatureEnsemble(LoadableModule):
#     def __init__(self, cfg, acoustic_model=None, linguistic_model=None):
#         super(FeatureEnsemble, self).__init__()
#         self.acoustic_model = acoustic_model if acoustic_model is not None else CNN(cfg.acoustic_config)
#         self.linguistic_model = linguistic_model if linguistic_model is not None else AttentionLSTM(cfg.linguistic_config)
#
#         self.feature_size = self.linguistic_model.hidden_size + self.acoustic_model.flat_size
#         self.fc = nn.Linear(self.feature_size, 4)
#         self.dropout = torch.nn.Dropout(0.7)
#
#     def forward(self, input_tuple):
#         acoustic_features, linguistic_features = input_tuple
#         # 从模型中提取 语音 和 语言 特征
#         acoustic_output_features = self.acoustic_model.extract(acoustic_features)
#         linguistic_output_features = self.linguistic_model.extract(linguistic_features)
#         # 将两个特征进行拼接
#         all_features = torch.cat((acoustic_output_features, linguistic_output_features), 1)
#         return self.fc(self.dropout(all_features))
#
#     @property
#     def name(self):
#         return "Feature Ensemble"