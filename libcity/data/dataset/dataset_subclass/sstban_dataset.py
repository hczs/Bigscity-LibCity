import os

import numpy as np
import pandas as pd

from libcity.data.dataset import TrafficStatePointDataset
from libcity.data.utils import generate_dataloader
from libcity.utils import ensure_dir


def seq2instance_plus(data, num_his, num_pred):
    num_step = data.shape[0]
    num_sample = num_step - num_his - num_pred + 1
    x = []
    y = []
    for i in range(num_sample):
        x.append(data[i: i + num_his])
        y.append(data[i + num_his: i + num_his + num_pred, :, :1])
    x = np.array(x)
    y = np.array(y)
    return x, y


def seq2instance(data, num_his, num_pred):
    num_step, dims = data.shape
    num_sample = num_step - num_his - num_pred + 1
    x = np.zeros(shape=(num_sample, num_his, dims))
    y = np.zeros(shape=(num_sample, num_pred, dims))
    for i in range(num_sample):
        x[i] = data[i: i + num_his]
        y[i] = data[i + num_his: i + num_his + num_pred]
    return x, y


class SSTBANDataset(TrafficStatePointDataset):

    def __init__(self, config):
        super().__init__(config)
        self.feature_name = {'X': 'float', 'y': 'float', 'TE': 'int'}

        self.time_slice_size = self.config.get('time_slice_size', 5)
        self.num_of_vertices = self.config.get('num_of_vertices', 170)
        self.num_his = self.config.get('num_his', 36)
        self.num_pred = self.config.get('num_pred', 36)

    def _generate_data(self):
        """
        生成全量数据集数据信息
        """
        # 处理多数据文件问题
        if isinstance(self.data_files, list):
            data_files = self.data_files.copy()
        else:  # str
            data_files = [self.data_files].copy()
        x_list, y_list = [], []
        for filename in data_files:
            df = super()._load_dyna(filename)
            x, y = seq2instance_plus(df[..., :1].astype("float64"), self.input_window, self.output_window)
            x_list.append(x)
            y_list.append(y)
        x = np.concatenate(x_list)
        y = np.concatenate(y_list)
        # create TE
        time = pd.DatetimeIndex(self.timesolts)
        dayofweek = np.reshape(time.weekday, (-1, 1))
        print(dayofweek.shape)
        time_of_day = (time.hour * 3600 + time.minute * 60 + time.second) \
                      // (self.time_slice_size * 60)  # total seconds
        time_of_day = np.reshape(time_of_day, (-1, 1))
        time = np.concatenate((dayofweek, time_of_day), -1)
        time = seq2instance(time, self.input_window, self.output_window)
        te = np.concatenate(time, 1).astype(np.int32)
        self._logger.info("Dataset created")
        self._logger.info("x shape: " + str(x.shape) + ", y shape: " + str(y.shape) + ", te shape: " + str(te.shape))
        return x, y, te

    def split_train_val_test(self, x, y, te):
        """
        划分训练集、测试集、验证集，并缓存数据集

        Args:
            x(np.ndarray): 输入数据 (num_samples, input_length, ..., feature_dim)
            y(np.ndarray): 输出数据 (num_samples, input_length, ..., feature_dim)
            te(np.ndarray): 时间数据 (num_samples, input_length, (dayofweek, timeofday))

        Returns:
            tuple: tuple contains:
                x_train: (num_samples, input_length, ..., feature_dim) \n
                y_train: (num_samples, input_length, ..., feature_dim) \n
                te_train: (num_samples, input_length, (dayofweek, timeofday)) \n
                x_val: (num_samples, input_length, ..., feature_dim) \n
                y_val: (num_samples, input_length, ..., feature_dim) \n
                te_val: (num_samples, input_length, (dayofweek, timeofday)) \n
                x_test: (num_samples, input_length, ..., feature_dim) \n
                y_test: (num_samples, input_length, ..., feature_dim) \n
                te_test: (num_samples, input_length, (dayofweek, timeofday))
        """
        test_rate = 1 - self.train_rate - self.eval_rate
        num_samples = x.shape[0]
        num_test = round(num_samples * test_rate)
        num_train = round(num_samples * self.train_rate)
        num_val = num_samples - num_test - num_train

        # train
        x_train, y_train, te_train = x[:num_train], y[:num_train], te[:num_train]
        # val
        x_val, y_val, te_val = x[num_train: num_train + num_val], y[num_train: num_train + num_val], \
            te[num_train: num_train + num_val]
        # test
        x_test, y_test, te_test = x[-num_test:], y[-num_test:], te[-num_test:]
        self._logger.info("train\t" + "x: " + str(x_train.shape) + ", y: " + str(y_train.shape)
                          + ", te" + str(te_train.shape))
        self._logger.info("eval\t" + "x: " + str(x_val.shape) + ", y: " + str(y_val.shape)
                          + ", te" + str(te_val.shape))
        self._logger.info("test\t" + "x: " + str(x_test.shape) + ", y: " + str(y_test.shape)
                          + ", te" + str(te_test.shape))

        if self.cache_dataset:
            ensure_dir(self.cache_file_folder)
            np.savez_compressed(
                self.cache_file_name,
                x_train=x_train,
                y_train=y_train,
                te_train=te_train,
                x_test=x_test,
                y_test=y_test,
                te_test=te_test,
                x_val=x_val,
                y_val=y_val,
                te_val=te_val
            )
            self._logger.info('Saved at ' + self.cache_file_name)
        return x_train, y_train, te_train, x_val, y_val, te_val, x_test, y_test, te_test

    def _generate_train_val_test(self):
        """
        加载数据集，并划分训练集、测试集、验证集，并缓存数据集
        """
        x, y, te = self._generate_data()
        return self.split_train_val_test(x, y, te)

    def _load_cache_train_val_test(self):
        """
        加载之前缓存好的训练集、测试集、验证集

        Returns:
            tuple: tuple contains:
                x_train: (num_samples, input_length, ..., feature_dim) \n
                y_train: (num_samples, input_length, ..., feature_dim) \n
                te_train: (num_samples, input_length, (dayofweek, timeofday)) \n
                x_val: (num_samples, input_length, ..., feature_dim) \n
                y_val: (num_samples, input_length, ..., feature_dim) \n
                te_val: (num_samples, input_length, (dayofweek, timeofday)) \n
                x_test: (num_samples, input_length, ..., feature_dim) \n
                y_test: (num_samples, input_length, ..., feature_dim) \n
                te_test: (num_samples, input_length, (dayofweek, timeofday))
        """
        self._logger.info('Loading ' + self.cache_file_name)
        cache_data = np.load(self.cache_file_name)
        x_train = cache_data['x_train']
        y_train = cache_data['y_train']
        te_train = cache_data['te_train']
        x_test = cache_data['x_test']
        y_test = cache_data['y_test']
        te_test = cache_data['te_test']
        x_val = cache_data['x_val']
        y_val = cache_data['y_val']
        te_val = cache_data['te_val']
        self._logger.info("train\t" + "x: " + str(x_train.shape) + ", y: " + str(y_train.shape)
                          + ", te" + str(te_train.shape))
        self._logger.info("eval\t" + "x: " + str(x_val.shape) + ", y: " + str(y_val.shape)
                          + ", te" + str(te_val.shape))
        self._logger.info("test\t" + "x: " + str(x_test.shape) + ", y: " + str(y_test.shape)
                          + ", te" + str(te_test.shape))
        return x_train, y_train, te_train, x_val, y_val, te_val, x_test, y_test, te_test

    def get_data(self):
        # 加载数据集
        x_train, y_train, te_train, x_val, y_val, te_val, x_test, y_test, te_test = [], [], [], [], [], [], [], [], []
        if self.data is None:
            self.data = {}
            if self.cache_dataset and os.path.exists(self.cache_file_name):
                x_train, y_train, te_train, x_val, y_val, te_val, x_test, y_test, te_test = \
                    self._load_cache_train_val_test()
            else:
                x_train, y_train, te_train, x_val, y_val, te_val, x_test, y_test, te_test = \
                    self._generate_train_val_test()
        # 数据归一化
        self.feature_dim = x_train.shape[-1]
        self.ext_dim = self.feature_dim - self.output_dim
        self.scaler = self._get_scalar(self.scaler_type,
                                       x_train[..., :self.output_dim], y_train[..., :self.output_dim])
        self.ext_scaler = self._get_scalar(self.ext_scaler_type,
                                           x_train[..., self.output_dim:], y_train[..., self.output_dim:])
        x_train[..., :self.output_dim] = self.scaler.transform(x_train[..., :self.output_dim])
        y_train[..., :self.output_dim] = self.scaler.transform(y_train[..., :self.output_dim])
        x_val[..., :self.output_dim] = self.scaler.transform(x_val[..., :self.output_dim])
        y_val[..., :self.output_dim] = self.scaler.transform(y_val[..., :self.output_dim])
        x_test[..., :self.output_dim] = self.scaler.transform(x_test[..., :self.output_dim])
        y_test[..., :self.output_dim] = self.scaler.transform(y_test[..., :self.output_dim])
        if self.normal_external:
            x_train[..., self.output_dim:] = self.ext_scaler.transform(x_train[..., self.output_dim:])
            y_train[..., self.output_dim:] = self.ext_scaler.transform(y_train[..., self.output_dim:])
            x_val[..., self.output_dim:] = self.ext_scaler.transform(x_val[..., self.output_dim:])
            y_val[..., self.output_dim:] = self.ext_scaler.transform(y_val[..., self.output_dim:])
            x_test[..., self.output_dim:] = self.ext_scaler.transform(x_test[..., self.output_dim:])
            y_test[..., self.output_dim:] = self.ext_scaler.transform(y_test[..., self.output_dim:])
        # 把训练集的X和y聚合在一起成为list，测试集验证集同理
        # x_train/y_train: (num_samples, input_length, ..., feature_dim)
        # train_data(list): train_data[i]是一个元组，由x_train[i]和y_train[i]组成
        train_data = list(zip(x_train, y_train, te_train))
        eval_data = list(zip(x_val, y_val, te_val))
        test_data = list(zip(x_test, y_test, te_test))
        # 转Dataloader
        self.train_dataloader, self.eval_dataloader, self.test_dataloader = \
            generate_dataloader(train_data, eval_data, test_data, self.feature_name,
                                self.batch_size, self.num_workers, pad_with_last_sample=self.pad_with_last_sample)
        self.num_batches = len(self.train_dataloader)
        return self.train_dataloader, self.eval_dataloader, self.test_dataloader

    def get_data_feature(self):
        """
        返回数据集特征，scaler是归一化方法，adj_mx是邻接矩阵，num_nodes是点的个数，
        feature_dim是输入数据的维度，output_dim是模型输出的维度

        Returns:
            dict: 包含数据集的相关特征的字典
        """
        return {"scaler": self.scaler, "adj_mx": self.adj_mx, "ext_dim": self.ext_dim,
                "num_nodes": self.num_nodes, "feature_dim": self.feature_dim,
                "output_dim": self.output_dim, "num_batches": self.num_batches,
                "time_slice_size": self.time_slice_size}