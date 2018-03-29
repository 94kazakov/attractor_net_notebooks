import tensorflow as tf
import numpy as np
from helper_functions import get_batches


#
# SMALL STUFF:
#
################ mozer_get_variable #####################################################
def mozer_get_variable(vname, mat_dim):
    if (len(mat_dim) == 1): # bias
        val = 0.1 * tf.random_normal(mat_dim)
        var = tf.get_variable(vname, initializer=val)

    else:
        #var = tf.get_variable(vname, shape=mat_dim,
        #                    initializer=tf.contrib.layers.xavier_initializer())

        #val = tf.random_normal(mat_dim)
        #var = tf.get_variable(vname, initializer=val)

        val = tf.random_normal(mat_dim)
        val = 2 * val / tf.reduce_sum(tf.abs(val),axis=0, keep_dims=True)
        var = tf.get_variable(vname, initializer=val)
    return var


def batch_tensor_collect(sess, input_tensors, X, Y, X_data, Y_data, batch_size):
    batches = get_batches(batch_size, X_data, Y_data)
    collect_outputs = [[] for i in range(len(input_tensors))]
    for (batch_x, batch_y) in batches:
        outputs = sess.run(input_tensors, feed_dict={X: batch_x, Y: batch_y})
        for i, output in enumerate(outputs):
            collect_outputs[i].append(output)

    # merge all
    for i in range(len(input_tensors)):
        output = np.array(collect_outputs[i])
        # import pdb;pdb.set_trace()
        if len(output[0].flatten()) > 1: # for actual tensor collections, merge batches
            output = np.concatenate(output, axis=0)
        else: # for just values, find the average
            output = np.mean(output)
        collect_outputs[i] = output

    return collect_outputs


#
# ATTRACTOR NETWORK:
#
############### RUN_ATTRACTOR_NET #################################################
def run_attractor_net(input_bias, attr_net, ops):
    # input_bias - nonsquashed hidden state
    a_clean_collection = []  # for mutual inf estimation

    if (ops['n_attractor_iterations'] > 0):
        if ops['attractor_dynamics'] == 'projection2':
            # task -> attractor space
            input_bias = tf.matmul(input_bias, attr_net['W_in']) + attr_net['b']

            a_clean = tf.zeros(tf.shape(input_bias))
            for i in range(ops['n_attractor_iterations']):
                # my version:
                #                 a_clean = tf.tanh(tf.matmul(a_clean, attr_net['Wconstr']) \
                #                           +  input_bias #attr_net['scale'] *
                a_clean = tf.matmul(tf.tanh(a_clean), attr_net['Wconstr']) \
                          + input_bias
                a_clean_collection.append(a_clean)

            # attractor space -> task
            a_clean = tf.tanh(tf.matmul(a_clean, attr_net['W_out']) + attr_net['b_out'])
        elif ops['attractor_dynamics'] == 'projection3':
            # task -> attractor space
            h_bias = tf.matmul(tf.tanh(input_bias), attr_net['W_in']) + attr_net['b']

            a_clean = tf.zeros(tf.shape(h_bias))
            for i in range(ops['n_attractor_iterations']):
                a_clean = tf.tanh(tf.matmul(a_clean, attr_net['Wconstr']) + h_bias)
                a_clean_collection.append(a_clean)

            # attractor space -> tasky
            a_clean = tf.tanh(tf.matmul(a_clean, attr_net['W_out']) + attr_net['b_out'] + input_bias)
        else:
            a_clean = tf.zeros(tf.shape(input_bias))
            for i in range(ops['n_attractor_iterations']):
                a_clean = tf.matmul(tf.tanh(a_clean), attr_net['Wconstr']) \
                          + attr_net['scale'] * input_bias + attr_net['b']
                a_clean_collection.append(a_clean)
            # a_clean = tf.tanh(tf.matmul(a_clean, attr_net['Wconstr']) \
            #                                   +  attr_net['scale'] * input_bias + attr_net['b'])

            a_clean = tf.tanh(a_clean)
    else:
        a_clean = tf.tanh(input_bias)
    return a_clean, a_clean_collection


############### ATTRACTOR NET LOSS FUNCTION #####################################

def attractor_net_loss_function(attractor_tgt_net, attr_net, ops):
    # attractor_tgt_net has dimensions #examples X #hidden
    #                   where the target value is tanh(attractor_tgt_net)

    # clean-up for attractor net training
    if (ops['attractor_noise_level'] >= 0.0):  # Gaussian mean-zero noise
        input_bias = attractor_tgt_net + ops['attractor_noise_level'] \
                                         * tf.random_normal(tf.shape(attractor_tgt_net))
    else:  # Bernoulli dropout
        input_bias = attractor_tgt_net * \
                     tf.cast((tf.random_uniform(tf.shape(attractor_tgt_net)) \
                              >= -ops['attractor_noise_level']), tf.float32)

    a_cleaned, _ = run_attractor_net(input_bias, attr_net, ops)

    # loss is % reduction in noise level
    attr_tgt = tf.tanh(attractor_tgt_net)
    attr_loss = tf.reduce_mean(tf.pow(attr_tgt - a_cleaned, 2)) / \
                tf.reduce_mean(tf.pow(attr_tgt - tf.tanh(input_bias), 2))

    if ops['attractor_regularization'] == 'l2':
        print("L2 Regularization")
        attr_loss += ops['attractor_regularization_lambda'] * tf.norm(attr_net['W'], ord=2)

    return attr_loss, input_bias


def attractor_net_init(ops):
    # attr net weights
    # NOTE: i tried setting attractor_W = attractor_b = 0 and attractor_scale=1.0
    # which is the default "no attractor" model, but that doesn't learn as well as

    ATTRACTOR_TYPE = ops['attractor_dynamics']
    N_HIDDEN = ops['hid']
    N_H_HIDDEN = ops['h_hid']
    with tf.variable_scope("ATTRACTOR_WEIGHTS"):
        attr_net = {}
        if ATTRACTOR_TYPE == 'projection2' or ATTRACTOR_TYPE == "projection3":  # attractor net 2
            attr_net['W_in'] = tf.get_variable("attractor_W_in", initializer=tf.eye(N_HIDDEN, num_columns=N_H_HIDDEN) +
                                                                             .01 * tf.random_normal(
                                                                                 [N_HIDDEN, N_H_HIDDEN]))
            attr_net['W_out'] = tf.get_variable("attractor_Wout", initializer=tf.eye(N_H_HIDDEN, num_columns=N_HIDDEN) +
                                                                              .01 * tf.random_normal(
                                                                                  [N_H_HIDDEN, N_HIDDEN]))
            attr_net['b_out'] = mozer_get_variable("attractor_b_out", [N_HIDDEN])
            attr_net['W'] = tf.get_variable("attractor_W", initializer=.01 * tf.random_normal([N_H_HIDDEN, N_H_HIDDEN]))
            attr_net['b'] = tf.get_variable("attractor_b", initializer=.01 * tf.random_normal([N_H_HIDDEN]))
        else:
            attr_net = {
                'W': tf.get_variable("attractor_W", initializer=.01 * tf.random_normal([N_HIDDEN, N_HIDDEN])),
                'b': tf.get_variable("attractor_b", initializer=.01 * tf.random_normal([N_HIDDEN]))
            }
        attr_net['scale'] = tf.get_variable("attractor_scale", initializer=.01 * tf.ones([1]))

    # if ATTR_WEIGHT_CONSTRAINTS:  # symmetric + nonnegative diagonal weight matrix
    Wdiag = tf.matrix_band_part(attr_net['W'], 0, 0)  # diagonal
    Wlowdiag = tf.matrix_band_part(attr_net['W'], -1, 0) - Wdiag  # lower diagonal
    # the normalization will happen here automatically since we defined it as a TF op
    attr_net['Wconstr'] = Wlowdiag + tf.transpose(Wlowdiag) + tf.abs(Wdiag)
    # attr_net['Wconstr'] = .5 * (attr_net['W'] + tf.transpose(attr_net['W'])) * \
    #                      (1.0-tf.eye(N_HIDDEN)) + tf.abs(tf.matrix_band_part(attr_net['W'],0,0))

    # else:
    #     attr_net['Wconstr'] = attr_net['W']
    return attr_net

    #
# GRU
#
############### GRU ###############################################################
def GRU_params_init(ops):
    N_INPUT = ops['in']
    N_HIDDEN = ops['hid']
    N_CLASSES = ops['out']
    with tf.variable_scope("TASK_WEIGHTS"):
        W = {'out': mozer_get_variable("W_out", [N_HIDDEN, N_CLASSES]),
             'in_stack': mozer_get_variable("W_in_stack", [N_INPUT, 3*N_HIDDEN]),
             'rec_stack': mozer_get_variable("W_rec_stack", [N_HIDDEN,3*N_HIDDEN]),
            }

        b = {'out': mozer_get_variable("b_out", [N_CLASSES]),
             'stack': mozer_get_variable("b_stack", [3 * N_HIDDEN]),
            }

    params = {
        'W': W,
        'b': b
    }
    return params

def GRU(X, ops, params):
    with tf.variable_scope("GRU"):
        W = params['W']
        b = params['b']
        attr_net = params['attr_net']
        N_HIDDEN = ops['hid']
        block_size = [-1, N_HIDDEN]

        def _step(accumulated_vars, input_vars):
            h_prev, _, _ = accumulated_vars
            x = input_vars

            preact = tf.matmul(x, W['in_stack'][:,:N_HIDDEN*2]) + \
                     tf.matmul(h_prev, W['rec_stack'][:,:N_HIDDEN*2]) + \
                     b['stack'][:N_HIDDEN*2]
            z = tf.sigmoid(tf.slice(preact, [0, 0 * N_HIDDEN], block_size))
            r = tf.sigmoid(tf.slice(preact, [0, 1 * N_HIDDEN], block_size))
            # new potential candidate for memory vector
            c_cand = tf.tanh( tf.matmul(x, W['in_stack'][:,N_HIDDEN*2:]) + \
                              tf.matmul(h_prev * r, W['rec_stack'][:,N_HIDDEN*2:]) + \
                              b['stack'][N_HIDDEN*2:])
            h = z * h_prev + (1.0 - z) * c_cand

            # insert attractor net
            h_net = tf.atanh(tf.minimum(.99999, tf.maximum(-.99999, h)))
            h_cleaned, h_attractor_collection = run_attractor_net(h_net, attr_net, ops)
            return [h_cleaned, h_net, h_attractor_collection]

        # X:                       (batch_size, SEQ_LEN, N_HIDDEN)
        # expected shape for scan: (SEQ_LEN, batch_size, N_HIDDEN)
        batch_size = tf.shape(X)[0]
        [h_clean_seq, h_net_seq, h_attractor_collection] = tf.scan(_step,
                  elems=tf.transpose(X, [1, 0, 2]),
                  initializer=[tf.zeros([batch_size, N_HIDDEN], tf.float32),  # h_clean
                               tf.zeros([batch_size, N_HIDDEN], tf.float32),  # h_net
                                [tf.zeros([batch_size, ops['h_hid']], tf.float32) for i in range(ops['n_attractor_iterations'])] ],
                                  name='GRU/scan')

        if 'pos' in ops['problem_type']:
            # for efficiency's sake just do one matmul.
            h_clean_seq_trans = tf.transpose(h_clean_seq, [1,0,2]) # [seq_len, batch_size, n_hid] -> [batch_size, seq_len, n_hid]
            h_clean_seq_trans = tf.reshape(h_clean_seq_trans, [-1, N_HIDDEN])  # [batch_size, seq_len, n_hid]-> [-1, n_hid]
            out = tf.nn.sigmoid(tf.matmul(h_clean_seq_trans, W['out']) + b['out'])
            out = tf.reshape(out, [batch_size, ops['seq_len'], ops['out']])
        else:
            out = tf.nn.sigmoid(tf.matmul(h_clean_seq[-1], W['out']) + b['out'])
        return [out, h_net_seq, h_attractor_collection, h_clean_seq]
