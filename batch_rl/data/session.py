import math
import random
import numpy as np
from .split import groupby_user
from utils.misc import compute_returns


def rolling_window(a, window):
    assert window <= a.shape[-1], "window size too large..."
    shape = a.shape[:-1] + (a.shape[-1] - window + 1, window)
    strides = a.strides + (a.strides[-1],)
    return np.lib.stride_tricks.as_strided(a, shape=shape, strides=strides)


def pad_session(hist_len, hist_num, hist_items, pad_val):
    sess_len = hist_len - 1 if hist_len - 1 < hist_num - 1 else hist_num - 1
    session_first = np.full((sess_len, hist_num + 1), pad_val, dtype=np.int64)
    for i in range(sess_len):
        offset = i + 2
        session_first[i, -offset:] = hist_items[:offset]
    return session_first


def build_session(n_users, n_items, hist_num, train_user_consumed,
                  test_user_consumed=None, train=True, sess_end=None,
                  sess_mode="one", neg_sample=None):
    user_sess, item_sess, reward_sess, done_sess = [], [], [], []
    user_consumed_set = {
        u: set(items) for u, items in train_user_consumed.items()
    }
    for u in range(n_users):
        if train:
            items = np.asarray(train_user_consumed[u])
        else:
            items = np.asarray(
                train_user_consumed[u][-hist_num:] + test_user_consumed[u]
            )

        hist_len = len(items)
        expanded_items = pad_session(hist_len, hist_num, items, pad_val=n_items)

        if hist_len > hist_num:
            full_size_sess = rolling_window(items, hist_num + 1)
            expanded_items = np.concatenate(
                [expanded_items, full_size_sess],
                axis=0
            )

        if train and neg_sample is not None:
            expanded_items, num_neg = sample_neg_session(
                expanded_items, user_consumed_set[u], n_items, neg_sample
            )

        sess_len = len(expanded_items)
        user_sess.append(np.tile(u, sess_len))
        item_sess.append(expanded_items)

        reward = np.ones(sess_len, dtype=np.float32)
        if train and neg_sample is not None:
            reward[-num_neg:] = 0.
        reward_sess.append(reward)

        # if sess_mode == "one":
        #    done = np.zeros(sess_len, dtype=np.float32)
        #    done[-1] = 1.
        # else:
        #    if train:
        #        end_mask = sess_end[u] - hist_num
        #        end_mask = end_mask[end_mask >= 0]
        #    else:
        #        end_mask = sess_end[u]
        #    done = np.zeros(sess_len, dtype=np.float32)
        #    done[end_mask] = 1.
        #    done[-1] = 1.

        done = np.zeros(sess_len, dtype=np.float32)
        if train and sess_mode == "interval":
            end_mask = sess_end[u]
            done[end_mask] = 1.
        if train and neg_sample is not None:
            done[-num_neg - 1] = 1.
        else:
            done[-1] = 1.
        done_sess.append(done)

    res = {"user": np.concatenate(user_sess),
           "item": np.concatenate(item_sess, axis=0),
           "reward": np.concatenate(reward_sess),
           "done": np.concatenate(done_sess)}
    return res


def sample_neg_session(items, consumed, n_items, sample_mode):
    size = len(items)
    if size <= 3:
        return items, 0

    num_neg = size // 2
    item_sampled = []
    for _ in range(num_neg):
        item_neg = math.floor(n_items * random.random())
        while item_neg in consumed:
            item_neg = math.floor(n_items * random.random())
        item_sampled.append(item_neg)

    if sample_mode == "random":
        indices = np.random.choice(size, num_neg, replace=False)
    else:
        indices = np.arange(size - num_neg, size)
    assert len(indices) == num_neg, "indices and num_neg must equal."
    neg_items = items[indices]
    neg_items[:, -1] = item_sampled
    return np.concatenate([items, neg_items], axis=0), num_neg


def build_sess_end(data, sess_mode="one", time_col=None, interval=3600):
    if sess_mode == "one":
        sess_end = one_sess_end(data)
    elif sess_mode == "interval":
        sess_end = interval_sess_end(data, time_col, sess_interval=interval)
    else:
        raise ValueError("sess_mode must be 'one' or 'interval'")
    return sess_end


def one_sess_end(data):
    return data.groupby("user").apply(len).to_dict()


# default sess_interval is 3600 secs
def interval_sess_end(data, time_col="time", sess_interval=3600):
    sess_times = data[time_col].astype('int').to_numpy()
    user_split_indices = groupby_user(data.user.to_numpy())
    sess_end = dict()
    for u in range(len(user_split_indices)):
        u_idxs = user_split_indices[u]
        user_ts = sess_times[u_idxs]
        # if neighbor time interval > sess_interval, then end of a session
        sess_end[u] = np.where(np.ediff1d(user_ts) > sess_interval)[0]
    return sess_end


def build_return_session(n_users, hist_num, train_user_consumed,
                         test_user_consumed=None, train=True, gamma=0.99):
    user_sess, item_sess, return_sess = [], [], []
    for u in range(n_users):
        if train:
            items = np.asarray(train_user_consumed[u])
        else:
            items = np.asarray(
                train_user_consumed[u][-hist_num:] + test_user_consumed[u]
            )

        item_session = rolling_window(items, hist_num + 1)
        sess_len = len(item_session)
        user_sess.append(np.tile(u, sess_len))
        item_sess.append(item_session)
        return_sess.append(compute_returns(
            np.ones(sess_len), gamma, normalize=False))

    res = {"user": np.concatenate(user_sess),
           "item": np.concatenate(item_sess, axis=0),
           "return": np.concatenate(return_sess)}
    return res


