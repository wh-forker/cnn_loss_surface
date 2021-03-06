import os
import mxnet as mx
import random
from mxnet.io import DataBatch, DataIter
import numpy as np
import gzip, struct
from common.util import download_file

def add_data_args(parser):
    data = parser.add_argument_group('Data', 'the input images')
    data.add_argument('--data-train', type=str, help='the training data')
    data.add_argument('--data-val', type=str, help='the validation data')
    data.add_argument('--rgb-mean', type=str, default='123.68,116.779,103.939',
                      help='a tuple of size 3 for the mean rgb')
    data.add_argument('--pad-size', type=int, default=0,
                      help='padding the input image')
    data.add_argument('--image-shape', type=str,
                      help='the image shape feed into the network, e.g. (3,224,224)')
    data.add_argument('--num-classes', type=int, help='the number of classes')
    data.add_argument('--num-examples', type=int, help='the number of training examples')
    data.add_argument('--data-nthreads', type=int, default=4,
                      help='number of threads for data decoding')
    data.add_argument('--benchmark', type=int, default=0,
                      help='if 1, then feed the network with synthetic data')
    return data

def add_data_aug_args(parser):
    aug = parser.add_argument_group(
        'Image augmentations', 'implemented in src/io/image_aug_default.cc')
    aug.add_argument('--random-crop', type=int, default=1,
                     help='if or not randomly crop the image')
    aug.add_argument('--random-mirror', type=int, default=1,
                     help='if or not randomly flip horizontally')
    aug.add_argument('--max-random-h', type=int, default=0,
                     help='max change of hue, whose range is [0, 180]')
    aug.add_argument('--max-random-s', type=int, default=0,
                     help='max change of saturation, whose range is [0, 255]')
    aug.add_argument('--max-random-l', type=int, default=0,
                     help='max change of intensity, whose range is [0, 255]')
    aug.add_argument('--max-random-aspect-ratio', type=float, default=0,
                     help='max change of aspect ratio, whose range is [0, 1]')
    aug.add_argument('--max-random-rotate-angle', type=int, default=0,
                     help='max angle to rotate, whose range is [0, 360]')
    aug.add_argument('--max-random-shear-ratio', type=float, default=0,
                     help='max ratio to shear, whose range is [0, 1]')
    aug.add_argument('--max-random-scale', type=float, default=1,
                     help='max ratio to scale')
    aug.add_argument('--min-random-scale', type=float, default=1,
                     help='min ratio to scale, should >= img_size/input_shape. otherwise use --pad-size')
    return aug

def set_data_aug_level(aug, level):
    if level >= 1:
        aug.set_defaults(random_crop=1, random_mirror=1)
    if level >= 2:
        aug.set_defaults(max_random_h=36, max_random_s=50, max_random_l=50)
    if level >= 3:
        aug.set_defaults(max_random_rotate_angle=10, max_random_shear_ratio=0.1, max_random_aspect_ratio=0.25)


class SyntheticDataIter(DataIter):
    def __init__(self, num_classes, data_shape, max_iter):
        self.batch_size = data_shape[0]
        self.cur_iter = 0
        self.max_iter = max_iter
        label = np.random.randint(0, num_classes, [self.batch_size,])
        data = np.random.uniform(-1, 1, data_shape)
        self.data = mx.nd.array(data)
        self.label = mx.nd.array(label)
    def __iter__(self):
        return self
    @property
    def provide_data(self):
        return [('data',self.data.shape)]
    @property
    def provide_label(self):
        return [('softmax_label',(self.batch_size,))]
    def next(self):
        self.cur_iter += 1
        if self.cur_iter <= self.max_iter:
            return DataBatch(data=(self.data,),
                             label=(self.label,),
                             pad=0,
                             index=None,
                             provide_data=self.provide_data,
                             provide_label=self.provide_label)
        else:
            raise StopIteration
    def __next__(self):
        return self.next()
    def reset(self):
        self.cur_iter = 0

def get_rec_iter(args, kv=None):
    image_shape = tuple([int(l) for l in args.image_shape.split(',')])
    if 'benchmark' in args and args.benchmark:
        data_shape = (args.batch_size,) + image_shape
        train = SyntheticDataIter(args.num_classes, data_shape, 50)
        return (train, None)
    if kv:
        (rank, nworker) = (kv.rank, kv.num_workers)
    else:
        (rank, nworker) = (0, 1)
    rgb_mean = [float(i) for i in args.rgb_mean.split(',')]
    if args.data_train is None:
        train = None
    else:
        train = mx.io.ImageRecordIter(
            path_imgrec         = args.data_train,
            label_width         = 1,
            mean_r              = rgb_mean[0],
            mean_g              = rgb_mean[1],
            mean_b              = rgb_mean[2],
            data_name           = 'data',
            label_name          = 'softmax_label',
            data_shape          = image_shape,
            batch_size          = args.batch_size,
            rand_crop           = args.random_crop,
            max_random_scale    = args.max_random_scale,
            pad                 = args.pad_size,
            fill_value          = 127,
            min_random_scale    = args.min_random_scale,
            max_aspect_ratio    = args.max_random_aspect_ratio,
            random_h            = args.max_random_h,
            random_s            = args.max_random_s,
            random_l            = args.max_random_l,
            max_rotate_angle    = args.max_random_rotate_angle,
            max_shear_ratio     = args.max_random_shear_ratio,
            rand_mirror         = args.random_mirror,
            preprocess_threads  = args.data_nthreads,
            shuffle             = True,
            num_parts           = nworker,
            part_index          = rank)
    if args.data_val is None:
        val = None
    else:
        val = mx.io.ImageRecordIter(
            path_imgrec         = args.data_val,
            label_width         = 1,
            mean_r              = rgb_mean[0],
            mean_g              = rgb_mean[1],
            mean_b              = rgb_mean[2],
            data_name           = 'data',
            label_name          = 'softmax_label',
            batch_size          = args.batch_size,
            data_shape          = image_shape,
            preprocess_threads  = args.data_nthreads,
            rand_crop           = False,
            rand_mirror         = False,
            num_parts           = nworker,
            part_index          = rank)
    return (train, val)

def read_mnist(label, image):
    """
    download and read data into numpy
    """
    base_url = 'http://yann.lecun.com/exdb/mnist/'
    with gzip.open(download_file(base_url+label, os.path.join('data',label))) as flbl:
        magic, num = struct.unpack(">II", flbl.read(8))
        label = np.fromstring(flbl.read(), dtype=np.int8)
    with gzip.open(download_file(base_url+image, os.path.join('data',image)), 'rb') as fimg:
        magic, num, rows, cols = struct.unpack(">IIII", fimg.read(16))
        image = np.fromstring(fimg.read(), dtype=np.uint8).reshape(len(label), rows, cols)
    return (label, image)

def to4d(img):
    """
    reshape to 4D arrays
    """
    return img.reshape(img.shape[0], 1, 28, 28).astype(np.float32)/255

def get_mnist_iter(args, kv):
    """
    create data iterator with NDArrayIter
    """
    (train_lbl, train_img) = read_mnist(
            'train-labels-idx1-ubyte.gz', 'train-images-idx3-ubyte.gz')
    (val_lbl, val_img) = read_mnist(
            't10k-labels-idx1-ubyte.gz', 't10k-images-idx3-ubyte.gz')
    train = mx.io.NDArrayIter(
        to4d(train_img), train_lbl, args.batch_size, shuffle=True)
    val = mx.io.NDArrayIter(
        to4d(val_img), val_lbl, args.batch_size)
    return (train, val)
