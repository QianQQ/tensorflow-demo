#!/usr/bin/env python2.7
#coding=utf-8

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tables as tb
import tensorflow as tf
import numpy as np
import os

def PReLU(inputs, scope):
    alphas = tf.get_variable(scope, inputs.get_shape()[-1],
                             initializer=tf.constant_initializer(0.0),
                             dtype=tf.float32)
    return tf.nn.relu(inputs) + alphas * (inputs - abs(inputs)) * 0.5


def weight_variable(shape, name='weights'):
    initializer = tf.random_normal_initializer(mean=0, stddev=0.01)
    return tf.get_variable(shape=shape, initializer=initializer, name=name)

def bias_variable(shape, name='biases'):
    initializer = tf.constant_initializer(0.1)
    return tf.get_variable(shape=shape, initializer=initializer, name=name)

def my_conv2d(x, W, b, scope, strides = 1, padding = "VALID"):
    x = tf.nn.conv2d(x, W, strides=[1, strides, strides, 1], padding=padding)
    x = tf.nn.bias_add(x, b)
    return PReLU(x, scope)

def get_cnn_net(inputs, reuse_symbol, FLAGS):
    """
    # inputs = [batch_size, lstm_time, neighbor_dim, feature_dim]
    """
    with tf.variable_scope('cnn', reuse=reuse_symbol) as scope:
        if int(inputs.shape[0]) != int(FLAGS.lstm_time * FLAGS.batch_size):
            print("cnn inputs shape error in lstm_time:", inputs.shape)
            exit(1)

        #conv1
        tf.to_float(inputs)
        if not reuse_symbol:
            print("cnn inputs shape:", inputs.shape)
        #Couv-1
        conv1 = tf.layers.conv2d(
                    inputs=inputs,
                    filters=128,
                    kernel_size=[5, 5],
                    strides=[2, 2],
                    padding="valid",
                    activation=tf.nn.relu
                )
        if not reuse_symbol:
            print("conv1 shape:", conv1.shape)
            conv1_hist = tf.summary.histogram('conv1_out', conv1)
        #max pool
        pool1 = tf.layers.max_pooling2d(inputs=conv1, pool_size=[2,2], stride=2)
        if not reuse_symbol:
            conv1_maxpool_hist = tf.summary.histogram('conv1_pool_out', pool1)
            print("conv1 pool shape:", pool1.shape)
        #Conv-2
        conv2 = tf.layers.conv2d(
                    inputs=pool1,
                    filters=256,
                    kernel_size=[1, 3],
                    padding="valid",
                    activation=tf.nn.relu
                )
        if not reuse_symbol:
            print("conv2 shape:", conv2.shape)
            conv2_hist = tf.summary.histogram('conv2_out', conv2)
        #max pool
        pool2 = tf.layers.max_pooling2d(inputs=conv2, pool_size=[1,2], stride=[1,2])
        if not reuse_symbol:
            conv2_maxpool_hist = tf.summary.histogram('conv2_pool_out', pool2)
            print("conv2 pool shape:", pool2.shape)
        conv3 = tf.layers.conv2d(
                    inputs=pool2,
                    filters=512,
                    kernel_size=[2, 4],
                    padding="valid",
                    activation=tf.nn.relu
                )
        #Fully connected layer
        #  fc = tf.reshape(conv2, [-1, weights['wd'].get_shape().as_list()[0]])
        #  if not reuse_symbol:
        #      print("fc reshape shape:", fc.shape)
        #  fc = tf.add(tf.matmul(fc, weights['wd']), biases['bd'])
        #  if not reuse_symbol:
        #      print("fc connected shape:", fc.shape)
        #  fc = PReLU(fc, 'cnn_fc')
        #  #Apply Dropout
        #  fc = tf.nn.dropout(fc, FLAGS.cnn_dropout)
        #  if not reuse_symbol:
        #      fc_hist = tf.summary.histogram('fc_out', fc)
        #  return fc
        fc = tf.reshape(conv3, [FLAGS.lstm_time * FLAGS.batch_size, 512])
        if not reuse_symbol:
            fc_hist = tf.summary.histogram('fc_out', fc)
        return fc



def get_lstm_net(inputs, reuse_symbol, FLAGS):
    #inputs shape = [batch_size, lstm_time, cnn_out]
    #max_time = left_context + 1(current_frame) + right_context
    #define lstm
    with tf.variable_scope("lstm", reuse=reuse_symbol) as scope:
        if inputs.shape[1] != FLAGS.lstm_time:
            print("lstm inputs error shape in lstm_time:", inputs.shape)
            exit(1)
        weights = {
            'wd': weight_variable([1024, FLAGS.dvector_dim], 'wd'),
            #  'fc': tf.get_variable("fc", tf.random_normal([1024, 600])),
        }
        biases = {
            'bd': bias_variable([FLAGS.dvector_dim], 'bd'),
            #  'fc': tf.get_variable("fc", tf.random_normal([600]))
        }
        if not reuse_symbol:
            inputs_hist = tf.summary.histogram('inputs', inputs)
            w_hist = tf.summary.histogram('lstm_fc/weights', weights['wd'])
            b_hist = tf.summary.histogram('lstm_fc/biases', biases['bd'])
        tf.to_float(inputs)
        if not reuse_symbol:
            print("lstm inputs shape:", inputs.shape)
        lstm_cells = []
        for _ in range(FLAGS.lstm_num_layers):
                lstm_cell = tf.contrib.rnn.GRUCell(FLAGS.lstm_hidden_units)
                lstm_cells.append(lstm_cell)
        stack_lstm = tf.contrib.rnn.MultiRNNCell(lstm_cells)
        initial_state = stack_lstm.zero_state(FLAGS.batch_size, tf.float32)
        outputs, _ = tf.nn.dynamic_rnn(stack_lstm, inputs, dtype=tf.float32, initial_state=initial_state)
        outputs = tf.transpose(outputs, [1,0,2])
        last = outputs[-1]
        last = PReLU(last, 'LSTM_out')
        if not reuse_symbol:
            print("lstm last shape:", last.shape)
            last_hist = tf.summary.histogram('lstm_out', last)
        fc = tf.add(tf.matmul(last, weights['wd']), biases['bd'])
        fc = PReLU(fc, 'lstm_fc')
        if not reuse_symbol:
            print("lstm out shape:", fc.shape)
        #Add hitogram summary
            fc_hist = tf.summary.histogram('fc_out', fc)
        return fc

def prepare_model(inputs, num_speakers, FLAGS):
    #inputs shape = [batch_size, lstm_time, neighbor_dim, feature_dim]
    batch_size = int(FLAGS.batch_size)
    lstm_time = int(FLAGS.lstm_time)
    neighbor_dim = int(FLAGS.left_context + FLAGS.right_context + 1)
    feature_dim = int(FLAGS.feature_dim)
    if int(batch_size) != int(inputs.shape[0]):
        print("error inputs shape[0] != batch_size (%d)" % (batch_size), inputs.shape)
        exit(1)
    with tf.variable_scope('sre_cnn_net') as scope:
        #  print("before trans inputs shape:", inputs.shape)
        #  cnn_input = tf.transpose(inputs, perm=[0,2,3,1])
        #  cnn_outputs = get_cnn_net(cnn_input, False, FLAGS)
        #init lstm param before reuse
        #handle the variable scope error
        #  lstm_input = tf.placeholder(tf.float32, [batch_size, lstm_time, 1024])
        #  init_lstm = get_lstm_net(lstm_input, FLAGS)
        #  cnn_outputs = []
        #  for i in range(batch_size):
        #      cnn_input = tf.reshape(inputs[i], [lstm_time, neighbor_dim, feature_dim, 1])
        #      if i > 0:
        #          cnn_out = get_cnn_net(cnn_input, True, FLAGS)
        #      else:
        #          cnn_out = get_cnn_net(cnn_input, False, FLAGS)
        #      cnn_outputs.append(cnn_out)
        #  cnn_outputs = tf.stack(cnn_outputs)
        print("inputs shape:", inputs.shape)
        cnn_inputs = tf.reshape(inputs, [FLAGS.batch_size * FLAGS.lstm_time, neighbor_dim, feature_dim, 1])
        cnn_outputs = get_cnn_net(cnn_inputs, False, FLAGS)
    with tf.variable_scope('sre_lstm_net') as scope:
        weights = weight_variable([FLAGS.dvector_dim, num_speakers], 'out_weights')
        biases = bias_variable([num_speakers], 'out_biases')
        w_hist = tf.summary.histogram('dvector_out/weights', weights)
        b_hist = tf.summary.histogram('dvector_out/biases', biases)
        print("cnn_outputs shape:", cnn_outputs.shape)
        lstm_inputs = tf.reshape(cnn_outputs, [FLAGS.batch_size, FLAGS.lstm_time, 512])
        out = get_lstm_net(lstm_inputs, False, FLAGS)
        dvector = out
        print("out shape:", out.shape)
        logits = tf.add(tf.matmul(out, weights), biases)
        print("logits shape:", logits.shape)
        logits_hist = tf.summary.histogram('logits', logits)
        if FLAGS.training:
            return logits, None
        else:
            return logits, dvector



