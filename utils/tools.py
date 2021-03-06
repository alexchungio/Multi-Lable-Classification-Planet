#!/usr/bin/env python
# -*- coding: utf-8 -*-
#------------------------------------------------------
# @ File       : tools.py
# @ Description:  
# @ Author     : Alex Chung
# @ Contact    : yonganzhong@outlook.com
# @ License    : Copyright (c) 2017-2018
# @ Time       : 2020/12/11 下午4:22
# @ Software   : PyCharm
#-------------------------------------------------------

import os
import time
import torch
import numpy as np
import shutil
from sklearn.metrics import fbeta_score

import adabound
from utils.radam import RAdam, AdamW
from configs.cfgs import args


class AverageMeter(object):
    """Computes and stores the average and current value
       Imported from https://github.com/pytorch/examples/blob/master/imagenet/main.py#L247-L262
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


def accuracy(output, target, topk=(1,)):
    """
    Computes the precision@k for the specified values of k
    :param output: [batch_size, num_classes]
    :param target: [batch_size, 1]
    :param topk:
    :return:
    """
    max_k = max(topk)
    batch_size = target.size(0)

    _, pred = output.topk(max_k, dim=1, largest=True, sorted=True)

    # transpose => (max_k, batch_size)
    pred = pred.t()
    # => [batch_size, max_k]
    correct = pred.eq(target.view(1, -1).expand_as(pred))

    res = []
    for k in topk:
        correct_k = correct[:k].view(-1).float().sum(0)
        res.append(correct_k.mul_(1 / batch_size))
    return res


def scores(output, target, threshold=0.5, epsilon=1e-7):
    # Count true positives, true negatives, false positives and false negatives.

    predict = (output > threshold).long()
    target = target.long()
    acc_sum = 0.0
    p_sum = 0.0
    r_sum = 0.0
    f2_sum = 0.0

    def _safe_size(t, n=0):
        if n < len(t.size()):
            return t.size(n)
        else:
            return 0
    count = 0
    for o, t in zip(predict, target):
        tp = _safe_size(torch.nonzero(o * t))
        tn = _safe_size(torch.nonzero((o - 1) * (t - 1)))
        fp = _safe_size(torch.nonzero(o * (t - 1)))
        fn = _safe_size(torch.nonzero((o - 1) * t))
        acc = (tp + tn) / (tp + fp + fn + tn)
        # when all predict label equal to 0 and all target label equal to 0
        if tp == 0 and fp == 0 and fn == 0:
            p = 1.0
            r = 1.0
            f2 = 1.0
        # avoid ZeroDivisionError: float division by zero
        elif tp == 0 and (fp > 0 or fn > 0):
            p = 0.0
            r = 0.0
            f2 = 0.0
        # tp not equal to 0
        else:
            p = tp / (tp + fp)
            r = tp / (tp + fn)
            f2 = (5 * p * r) / (4 * p + r)

        acc_sum += acc
        p_sum += p
        r_sum += r
        f2_sum += f2
        count += 1
    accuracy = acc_sum / count
    precision = p_sum / count
    recall = r_sum / count
    f2_score = f2_sum / count

    return accuracy, precision, recall, f2_score


def f2_score(output, target, threshold):
    output = (output > threshold)
    return fbeta_score(target, output, beta=2, average='samples')


def optimise_f2_thresholds(target, output, verbose=True, resolution=100):
    """ Find optimal threshold values for f2 score. Thanks Anokas
    https://www.kaggle.com/c/planet-understanding-the-amazon-from-space/discussion/32475
    """
    best_score = 0.0
    size = target.shape[1] # size = num_classes

    def f_score(x):
        p2 = np.zeros_like(output)
        for i in range(size):
            p2[:, i] = (output[:, i] > x[i]).astype(np.int)
        score = fbeta_score(target, p2, beta=2, average='samples')
        return score

    class_threshold = [0.2] * size
    for i in range(size):
        best_threshold = 0.0
        best_score = 0.0
        for threshold in range(resolution):
            threshold /= resolution
            class_threshold[i] = threshold
            score = f_score(class_threshold)
            if score > best_score:
                best_threshold = threshold
                best_score = score
        class_threshold[i] = best_threshold
        if verbose:
            print(i, best_threshold, best_score)

    return class_threshold, best_score


def get_optimizer(model, args):

    if args.optimizer == 'sgd':
        return torch.optim.SGD(model.parameters(),
                              # model.parameters(),
                               args.lr,
                               momentum=args.momentum, nesterov=args.nesterov,
                               weight_decay=args.weight_decay)
    elif args.optimizer == 'rmsprop':
        return torch.optim.RMSprop(model.parameters(),
                                # model.parameters(),
                                   args.lr,
                                   alpha=args.alpha,
                                   weight_decay=args.weight_decay)
    elif args.optimizer == 'adam':
        return torch.optim.Adam(model.parameters(),
                                # model.parameters(),
                                args.lr,
                                betas=(args.beta1, args.beta2),
                                weight_decay=args.weight_decay)
    elif args.optimizer == 'AdaBound':
        return adabound.AdaBound(model.parameters(),
                                # model.parameters(),
                                lr=args.lr, final_lr=args.final_lr)
    elif args.optimizer == 'radam':
        return RAdam(model.parameters(), lr=args.lr, betas=(args.beta1, args.beta2),
                          weight_decay=args.weight_decay)

    else:
        raise NotImplementedError


def save_checkpoint(state, model_path, is_best):
    """

    :param state:
    :param path:
    :return:
    """
    try:
        print('Saving state at {}'.format(time.ctime()))
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        torch.save(state, model_path)

        if is_best:
            shutil.copy(model_path, args.best_checkpoint)

    except Exception as e:
        print('Failed due to {}'.format(e))


if __name__ == "__main__":

    # torch.manual_seed(2020)
    threshold_0 = 0.2
    threshold_1 = [0.2] * 6
    output = torch.randn(size=(4, 6))
    target = torch.randint(0, 2, size=(4, 6))

    print(scores(output, target, threshold_1))


