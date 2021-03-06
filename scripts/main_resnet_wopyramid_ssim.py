from __future__ import print_function
import torch
import torch.nn as nn
import numpy as np
import argparse
import cv2
import models.lapgan_mnist as lapgan
import torch.optim as optim
import torch.backends.cudnn as cudnn
import torchvision.utils as vutils
import os
from ssim_loss import ssim_loss

from torchvision import datasets, transforms
from torch.autograd import Variable
from numpy.random import randn

parser = argparse.ArgumentParser(description='PyTorch MNIST Example')
parser.add_argument('--model', help='basic | woresnet | woresnetup', default='resnetwopyramid_ssim')
parser.add_argument('--dataset', help='lsun | imagenet | mnist', default='folder')
parser.add_argument('--datapath', help='path to dataset', default='/home/user/kaixu/myGitHub/datasets/LSUN/')
parser.add_argument('--batch-size', type=int, default=32, metavar='N',
                    help='input batch size for training (default: 64)')
parser.add_argument('--image-size', type=int, default=64, metavar='N',
                    help='The height / width of the input image to the network')
parser.add_argument('--test-batch-size', type=int, default=1000, metavar='N',
                    help='input batch size for testing (default: 1000)')
parser.add_argument('--epochs', type=int, default=100, metavar='N',
                    help='number of epochs to train (default: 10)')
parser.add_argument('--lr', type=float, default=2e-4, metavar='LR',
                    help='learning rate (default: 0.01)')
parser.add_argument('--momentum', type=float, default=0.5, metavar='M',
                    help='SGD momentum (default: 0.5)')
parser.add_argument('--cuda', action='store_true', default=True,
                    help='enable CUDA training')
parser.add_argument('--ngpu', type=int, default=1,
                    help='number of GPUs to use')
parser.add_argument('--seed', type=int, default=1, metavar='S',
                    help='random seed (default: 1)')
parser.add_argument('--log-interval', type=int, default=10, metavar='N',
                    help='how many batches to wait before logging training status')
parser.add_argument('--layers-gan', type=int, default=3, metavar='N',
                    help='number of hierarchies in the GAN (default: 64)')
parser.add_argument('--gpu', type=int, default=2, metavar='N',
                    help='which GPU do you want to use (default: 1)')
parser.add_argument('--outf', default='./results', help='folder to output images and model checkpoints')
parser.add_argument('--w-loss-mse', type=float, default=0.50, metavar='N.',
                    help='penalty for the mse and bce loss')
parser.add_argument('--w-loss-ssim', type=float, default=0.40, metavar='N.',
                    help='penalty for the mse and bce loss')

opt = parser.parse_args()
if torch.cuda.is_available() and not opt.cuda:
    print("WARNING: please run with GPU")
print(opt)

# torch.cuda.set_device(opt.gpu)
# print('Current gpu device: gpu %d' % (torch.cuda.current_device()))

if opt.seed is None:
    opt.seed = np.random.randint(1, 10000)
print('Random seed: ', opt.seed)
np.random.seed(opt.seed)
torch.manual_seed(opt.seed)
if opt.cuda:
    torch.cuda.manual_seed(opt.seed)

cudnn.benchmark = True

if not os.path.exists('%s/%s/%s/model' % (opt.outf, opt.dataset, opt.model)):
    os.makedirs('%s/%s/%s/model' % (opt.outf, opt.dataset, opt.model))
if not os.path.exists('%s/%s/%s/image' % (opt.outf, opt.dataset, opt.model)):
    os.makedirs('%s/%s/%s/image' % (opt.outf, opt.dataset, opt.model))


def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        m.weight.data.normal_(0.0, 0.02)
    elif classname.find('BatchNorm') != -1:
        m.weight.data.normal_(1.0, 0.02)
        m.bias.data.fill_(0)


def data_loader():
    kwopt = {'num_workers': 2, 'pin_memory': True} if opt.cuda else {}

    if opt.dataset == 'lsun':
        train_dataset = datasets.LSUN(db_path=opt.datapath + 'train/', classes=['bedroom_train'],
                                      transform=transforms.Compose([
                                          transforms.Scale(opt.image_size),
                                          transforms.CenterCrop(opt.image_size),
                                          transforms.ToTensor(),
                                          transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                      ]))
    elif opt.dataset == 'mnist':
        train_dataset = datasets.MNIST('./data', train=True, download=True,
                                       transform=transforms.Compose([
                                           transforms.Scale(opt.image_size),
                                           transforms.CenterCrop(opt.image_size),
                                           transforms.ToTensor(),
                                           transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                       ]))
        val_dataset = datasets.MNIST('./data', train=False,
                                     transform=transforms.Compose([
                                         transforms.Scale(opt.image_size),
                                         transforms.CenterCrop(opt.image_size),
                                         transforms.ToTensor(),
                                         transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                     ]))
    elif opt.dataset == 'folder':
        train_dataset = datasets.ImageFolder(root='/home/user/kaixu/myGitHub/datasets/BSDS500/train-aug/',
                                             transform=transforms.Compose([
                                                 transforms.Scale(opt.image_size),
                                                 transforms.CenterCrop(opt.image_size),
                                                 transforms.ToTensor(),
                                                 transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                             ]))

        val_dataset = datasets.ImageFolder(root='/home/user/kaixu/myGitHub/datasets/BSDS500/test-aug/',
                                           transform=transforms.Compose([
                                               transforms.Scale(opt.image_size),
                                               transforms.CenterCrop(opt.image_size),
                                               transforms.ToTensor(),
                                               transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
                                           ]))

    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=opt.batch_size, shuffle=True, **kwopt)

    val_loader = torch.utils.data.DataLoader(val_dataset, batch_size=opt.batch_size, shuffle=False, **kwopt)

    return train_loader, val_loader

def val(level, m1, m2, channels, valloader, sensing_matrix_left, g1_input, g2_target, g4_target, lapnet1, lapnet2_gen,
        lapnet_gen, criterion_mse):
    for idx, (data, _) in enumerate(valloader, 0):
        if data.size(0) != opt.batch_size:
            continue

        data_array = data.numpy()
        for i in range(opt.batch_size):
            g4_target_temp = data_array[i]  # 1x64x64
            g3_target_temp = g4_target_temp[:, ::2, ::2]  # 1x32x32
            g2_target_temp = g3_target_temp[:, ::2, ::2]  # 1x16x16
            g1_target_temp = g2_target_temp[:, ::2, ::2]  # 1x8x8
            if level == 2:
                g2_target[i] = torch.from_numpy(g2_target_temp)
            elif level == 5:
                g4_target[i] = torch.from_numpy(g4_target_temp)

            for j in range(channels):
                g1_input[i, j, :, :] = torch.from_numpy(
                    np.reshape(sensing_matrix_left.dot(data_array[i, j].flatten()), (m1, m2)))

        g1_input_var = Variable(g1_input)
        if level == 2:
            g2_input = lapnet1(g1_input_var)
            target_var = Variable(g2_target)
            output = lapnet2_gen(g2_input, g1_input_var)
        elif level == 5:
            target_var = Variable(g4_target)
            output = lapnet_gen(g1_input_var, g1_input_var)

        errD_fake_mse = criterion_mse(output, target_var)

        print('Test: [%d/%d] errG_mse: %.4f,' % (idx, len(valloader), errD_fake_mse.data[0]))
    vutils.save_image(g4_target,
                      '%s/%s/%s/image/test_l%d_real_samples.png' % (
                          opt.outf, opt.dataset, opt.model, 2), normalize=True)
    vutils.save_image(output.data,
                      '%s/%s/%s/image/test_l%d_fake_samples.png' % (
                          opt.outf, opt.dataset, opt.model, 2), normalize=True)


def train(epochs, trainloader, valloader):
    # Initialize variables
    input, _ = trainloader.__iter__().__next__()
    input = input.numpy()
    sz_input = input.shape
    cr = 8
    channels = sz_input[1]
    n1 = sz_input[2]
    m1 = n1 / cr
    n2 = sz_input[3]
    m2 = n2 / cr

    n = sz_input[2] * sz_input[3]
    m = n / cr ** 2

    sensing_matrix_left = randn(m, n)

    g1_input = torch.FloatTensor(opt.batch_size, sz_input[1], m1, m2)
    g2_input = torch.FloatTensor(opt.batch_size, sz_input[1], m1 * 2, m2 * 2)
    g3_input = torch.FloatTensor(opt.batch_size, sz_input[1], m1 * 4, m2 * 4)
    g4_input = torch.FloatTensor(opt.batch_size, sz_input[1], m1 * 8, m2 * 8)

    g1_target = torch.FloatTensor(opt.batch_size, sz_input[1], m1, m2)
    g2_target = torch.FloatTensor(opt.batch_size, sz_input[1], m1 * 2, m2 * 2)
    g3_target = torch.FloatTensor(opt.batch_size, sz_input[1], m1 * 4, m2 * 4)
    g4_target = torch.FloatTensor(opt.batch_size, sz_input[1], m1 * 8, m2 * 8)

    label = torch.FloatTensor(opt.batch_size)

    fake_label = 0
    real_label = 0.9

    # Instantiate models
    lapnet1 = lapgan.LAPGAN_Generator_level1(channels, opt.ngpu)
    lapnet2_gen = lapgan.LAPGAN_Generator_level2(channels, opt.ngpu, channels * m1 * m2)
    lapnet2_disc = lapgan.LAPGAN_Discriminator_level2(channels, opt.ngpu)
    lapnet3_gen = lapgan.LAPGAN_Generator_level3(channels, opt.ngpu, channels * m1 * m2)
    lapnet3_disc = lapgan.LAPGAN_Discriminator_level3(channels, opt.ngpu)
    lapnet4_gen = lapgan.LAPGAN_Generator_level4(channels, opt.ngpu, channels * m1 * m2)
    lapnet4_disc = lapgan.LAPGAN_Discriminator_level4(channels, opt.ngpu)

    # Weight initialization
    lapnet1.apply(weights_init)
    lapnet2_disc.apply(weights_init)
    lapnet2_gen.apply(weights_init)
    lapnet3_disc.apply(weights_init)
    lapnet3_gen.apply(weights_init)
    lapnet4_disc.apply(weights_init)
    lapnet4_gen.apply(weights_init)

    print(lapnet1)
    print(lapnet2_disc)
    print(lapnet2_gen)
    print(lapnet3_disc)
    print(lapnet3_gen)
    print(lapnet4_disc)
    print(lapnet4_gen)

    optimizer_lapnet1 = optim.Adam(lapnet1.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    optimizer_lapnet2_disc = optim.Adam(lapnet2_disc.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    optimizer_lapnet2_gen = optim.Adam(lapnet2_gen.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    optimizer_lapnet3_disc = optim.Adam(lapnet3_disc.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    optimizer_lapnet3_gen = optim.Adam(lapnet3_gen.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    optimizer_lapnet4_disc = optim.Adam(lapnet4_disc.parameters(), lr=opt.lr, betas=(0.5, 0.999))
    optimizer_lapnet4_gen = optim.Adam(lapnet4_gen.parameters(), lr=opt.lr, betas=(0.5, 0.999))

    criterion_mse = nn.MSELoss()
    criterion_bce = nn.BCELoss()
    criterion_ssim1 = ssim_loss()
    criterion_ssim2 = ssim_loss()
    criterion_ssim3 = ssim_loss()
    criterion_ssim4 = ssim_loss()
    criterion_ssim5 = ssim_loss()

    #    torch.cuda.set_device(gpus[0])
    if opt.gpu:
        lapnet1.cuda()
        lapnet2_gen.cuda(), lapnet2_disc.cuda()
        lapnet3_gen.cuda(), lapnet3_disc.cuda()
        lapnet4_gen.cuda(), lapnet4_disc.cuda()

        criterion_mse.cuda()
        criterion_bce.cuda()
        criterion_ssim1.cuda(), criterion_ssim2.cuda()
        criterion_ssim3.cuda(), criterion_ssim4.cuda()
        criterion_ssim5.cuda()

        g1_input, g2_input, g3_input, g4_input = g1_input.cuda(), g2_input.cuda(), g3_input.cuda(), g4_input.cuda()
        g1_target, g2_target, g3_target, g4_target = g1_target.cuda(), g2_target.cuda(), g3_target.cuda(), g4_target.cuda()
        label = label.cuda()

    for epoch in range(epochs):
        # training level 1
        for idx, (data, _) in enumerate(trainloader, 0):
            if data.size(0) != opt.batch_size:
                continue

            data_array = data.numpy()
            for i in range(opt.batch_size):
                g4_target_temp = data_array[i]  # 1x64x64
                g3_target_temp = g4_target_temp[:, ::2, ::2]  # 1x32x32
                g2_target_temp = g3_target_temp[:, ::2, ::2]  # 1x16x16
                g1_target_temp = g2_target_temp[:, ::2, ::2]  # 1x8x8
                g2_target[i] = torch.from_numpy(g2_target_temp)
                g1_target[i] = torch.from_numpy(g1_target_temp)

                for j in range(channels):
                    g1_input[i, j, :, :] = torch.from_numpy(
                        np.reshape(sensing_matrix_left.dot(data_array[i, j].flatten()), (m1, m2)))

            g1_input_var = Variable(g1_input)
            target_var = Variable(g1_target)

            optimizer_lapnet1.zero_grad()
            outputs = lapnet1(g1_input_var)
            err_ssim = criterion_ssim1(outputs, target_var)
            err_mse = criterion_mse(outputs, target_var)
            loss = opt.w_loss_ssim * err_ssim + opt.w_loss_mse * err_mse
            # loss = criterion_mse(outputs, target_var)
            loss.backward()
            optimizer_lapnet1.step()
            criterion_ssim1.w_x.weight.data += abs(criterion_ssim1.w_x.weight.min().data[0])
            print('Level %d [%d/%d][%d/%d] loss_mse: %.4f, loss_ssim: %.4f' % (1, epoch, epochs, idx, len(trainloader),
                                                                              err_mse.data[0], err_ssim.data[0]))

        # training level 2
        for idx, (data, _) in enumerate(trainloader, 0):
            if data.size(0) != opt.batch_size:
                continue

            data_array = data.numpy()
            for i in range(opt.batch_size):
                g4_target_temp = data_array[i]  # 1x64x64
                g3_target_temp = g4_target_temp[:, ::2, ::2]  # 1x32x32
                g2_target_temp = g3_target_temp[:, ::2, ::2]  # 1x16x16
                g2_target[i] = torch.from_numpy(g2_target_temp)
                for j in range(channels):
                    g1_input[i, j, :, :] = torch.from_numpy(
                        np.reshape(sensing_matrix_left.dot(data_array[i, j].flatten()), (m1, m2)))

            g1_input_var = Variable(g1_input)
            g2_input = lapnet1(g1_input_var)

            # Train disc2 with true images
            g2_target_var = Variable(g2_target)
            optimizer_lapnet2_disc.zero_grad()
            d2_output = lapnet2_disc(g2_target_var)
            d2_label_var = Variable(label.fill_(real_label))
            errD_d2_real_bce = criterion_bce(d2_output, d2_label_var)
            errD_d2_real_bce.backward()
            d2_real_mean = d2_output.data.mean()

            # Train disc2 with fake images
            g2_output = lapnet2_gen(g2_input, g1_input_var)
            d2_output = lapnet2_disc(g2_output.detach())
            d2_label_var = Variable(label.fill_(fake_label))
            errD_d2_fake_bce = criterion_bce(d2_output, d2_label_var)
            errD_d2_fake_bce.backward()
            optimizer_lapnet2_disc.step()

            # Train gen2 with fake images, disc2 is not updated
            optimizer_lapnet2_gen.zero_grad()
            d2_label_var = Variable(label.fill_(real_label))
            d2_output = lapnet2_disc(g2_output)
            errD_g2_fake_bce = criterion_bce(d2_output, d2_label_var)
            errD_g2_fake_ssim = criterion_ssim2(g2_output, g2_target_var)
            errD_g2_fake_mse = criterion_mse(g2_output, g2_target_var)
            errD_g2 = (1 - opt.w_loss_mse - opt.w_loss_ssim) * errD_g2_fake_bce +\
                      opt.w_loss_mse * errD_g2_fake_mse + \
                      opt.w_loss_ssim * errD_g2_fake_ssim
            errD_g2.backward()
            optimizer_lapnet2_gen.step()
            criterion_ssim2.w_x.weight.data += abs(criterion_ssim2.w_x.weight.min().data[0])
            d2_fake_mean = d2_output.data.mean()

            print('Level %d [%d/%d][%d/%d] errD_real: %.4f, errD_fake: %.4f, errG_bce: %.4f errG_mse: %.4f,'
                  'errG_ssim: %.4f, D(x): %.4f, D(G(z)): %.4f' % (
                      2, epoch, epochs, idx, len(trainloader),
                      errD_d2_real_bce.data[0],
                      errD_d2_fake_bce.data[0],
                      errD_g2_fake_bce.data[0],
                      errD_g2_fake_mse.data[0],
                      errD_g2_fake_ssim.data[0],
                      d2_real_mean,
                      d2_fake_mean))

        torch.save(lapnet2_gen.state_dict(),
                   '%s/%s/%s/model/lapnet2_gen_epoch_%d.pth' % (opt.outf, opt.dataset, opt.model, epoch))
        torch.save(lapnet2_disc.state_dict(),
                   '%s/%s/%s/model/lapnet2_disc_epoch_%d.pth' % (opt.outf, opt.dataset, opt.model, epoch))
        vutils.save_image(g2_target,
                          '%s/%s/%s/image/l%d_real_samples_epoch_%03d.png' % (
                          opt.outf, opt.dataset, opt.model, 2, epoch),
                          normalize=True)
        vutils.save_image(g2_output.data,
                          '%s/%s/%s/image/l%d_fake_samples_epoch_%02d.png' % (
                          opt.outf, opt.dataset, opt.model, 2, epoch),
                          normalize=True)

        # training level 3
        for idx, (data, _) in enumerate(trainloader, 0):
            if data.size(0) != opt.batch_size:
                continue

            data_array = data.numpy()
            for i in range(opt.batch_size):
                g4_target_temp = data_array[i]  # 1x64x64
                g3_target_temp = g4_target_temp[:, ::2, ::2]  # 1x32x32
                g3_target[i] = torch.from_numpy(g3_target_temp)
                for j in range(channels):
                    g1_input[i, j, :, :] = torch.from_numpy(
                        np.reshape(sensing_matrix_left.dot(data_array[i, j].flatten()), (m1, m2)))
            g1_input_var = Variable(g1_input)
            g2_input = lapnet1(g1_input_var)  # 1x8x8
            g3_input = lapnet2_gen(g2_input, g1_input_var)  # 1x16x16

            # Train disc3 with true images
            g3_target_var = Variable(g3_target)
            optimizer_lapnet3_disc.zero_grad()
            d3_output = lapnet3_disc(g3_target_var)
            d3_label_var = Variable(label.fill_(real_label))
            errD_d3_real_bce = criterion_bce(d3_output, d3_label_var)
            errD_d3_real_bce.backward()
            d3_real_mean = d3_output.data.mean()
            # Train disc3 with fake images
            g3_output = lapnet3_gen(g3_input, g1_input_var)
            d3_output = lapnet3_disc(g3_output.detach())
            d3_label_var = Variable(label.fill_(fake_label))
            errD_d3_fake_bce = criterion_bce(d3_output, d3_label_var)
            errD_d3_fake_bce.backward()
            optimizer_lapnet3_disc.step()
            # Train gen3 with fake images, disc3 is not updated
            optimizer_lapnet3_gen.zero_grad()
            d3_label_var = Variable(label.fill_(real_label))
            d3_output = lapnet3_disc(g3_output)
            errD_g3_fake_bce = criterion_bce(d3_output, d3_label_var)
            errD_g3_fake_ssim = criterion_ssim3(g3_output, g3_target_var)
            errD_g3_fake_mse = criterion_mse(g3_output, g3_target_var)
            errD_g3 = (1 - opt.w_loss_mse - opt.w_loss_ssim) * errD_g3_fake_bce +\
                      opt.w_loss_mse * errD_g3_fake_mse + \
                      opt.w_loss_ssim * errD_g3_fake_ssim
            errD_g3.backward()
            optimizer_lapnet3_gen.step()
            criterion_ssim3.w_x.weight.data += abs(criterion_ssim3.w_x.weight.min().data[0])
            d3_fake_mean = d3_output.data.mean()
            print('Level %d [%d/%d][%d/%d] errD_real: %.4f, errD_fake: %.4f, errG_bce: %.4f errG_mse: %.4f,'
                  'errG_ssim: %.4f, D(x): %.4f, D(G(z)): %.4f' % (
                      3, epoch, epochs, idx, len(trainloader),
                      errD_d3_real_bce.data[0],
                      errD_d3_fake_bce.data[0],
                      errD_g3_fake_bce.data[0],
                      errD_g3_fake_mse.data[0],
                      errD_g3_fake_ssim.data[0],
                      d3_real_mean,
                      d3_fake_mean))
        torch.save(lapnet3_gen.state_dict(),
                   '%s/%s/%s/model/lapnet3_gen_epoch_%d.pth' % (opt.outf, opt.dataset, opt.model, epoch))
        torch.save(lapnet3_disc.state_dict(),
                   '%s/%s/%s/model/lapnet3_disc_epoch_%d.pth' % (opt.outf, opt.dataset, opt.model, epoch))
        vutils.save_image(g3_target,
                          '%s/%s/%s/image/l%d_real_samples_epoch_%03d.png' % (
                          opt.outf, opt.dataset, opt.model, 3, epoch),
                          normalize=True)
        vutils.save_image(g3_output.data,
                          '%s/%s/%s/image/l%d_fake_samples_epoch_%02d.png' % (
                          opt.outf, opt.dataset, opt.model, 3, epoch),
                          normalize=True)

        # training level 4
        for idx, (data, _) in enumerate(trainloader, 0):
            if data.size(0) != opt.batch_size:
                continue

            data_array = data.numpy()
            for i in range(opt.batch_size):
                g4_target_temp = data_array[i]  # 1x64x64
                g4_target[i] = torch.from_numpy(g4_target_temp)

                for j in range(channels):
                    g1_input[i, j, :, :] = torch.from_numpy(
                        np.reshape(sensing_matrix_left.dot(data_array[i, j].flatten()), (m1, m2)))
            g1_input_var = Variable(g1_input)
            g2_input = lapnet1(g1_input_var)  # 1x8x8
            g3_input = lapnet2_gen(g2_input, g1_input_var)  # 1x16x16
            g4_input = lapnet3_gen(g3_input, g1_input_var)  # 1x32x32

            # Train disc4 with true images
            g4_target_var = Variable(g4_target)
            optimizer_lapnet4_disc.zero_grad()
            d4_output = lapnet4_disc(g4_target_var)
            d4_label_var = Variable(label.fill_(real_label))
            errD_d4_real_bce = criterion_bce(d4_output, d4_label_var)
            errD_d4_real_bce.backward()
            d4_real_mean = d4_output.data.mean()
            # Train disc4 with fake images
            g4_output = lapnet4_gen(g4_input, g1_input_var)
            d4_output = lapnet4_disc(g4_output.detach())
            d4_label_var = Variable(label.fill_(fake_label))
            errD_d4_fake_bce = criterion_bce(d4_output, d4_label_var)
            errD_d4_fake_bce.backward()
            optimizer_lapnet4_disc.step()
            # Train gen4 with fake images, disc4 is not updated
            optimizer_lapnet4_gen.zero_grad()
            d4_label_var = Variable(label.fill_(real_label))
            d4_output = lapnet4_disc(g4_output)
            errD_g4_fake_bce = criterion_bce(d4_output, d4_label_var)
            errD_g4_fake_ssim = criterion_ssim4(g4_output, g4_target_var)
            errD_g4_fake_mse = criterion_mse(g4_output, g4_target_var)
            errD_g4 = (1 - opt.w_loss_ssim - opt.w_loss_mse) * errD_g4_fake_bce +\
                      opt.w_loss_mse * errD_g4_fake_mse + \
                      opt.w_loss_ssim * errD_g4_fake_ssim
            errD_g4.backward()
            optimizer_lapnet4_gen.step()
            criterion_ssim4.w_x.weight.data += abs(criterion_ssim4.w_x.weight.min().data[0])
            d4_fake_mean = d4_output.data.mean()
            print('Level %d [%d/%d][%d/%d] errD_real: %.4f, errD_fake: %.4f, errG_bce: %.4f errG_mse: %.4f,'
                  'errG_ssim: %.4f, D(x): %.4f, D(G(z)): %.4f' % (
                      4, epoch, epochs, idx, len(trainloader),
                      errD_d4_real_bce.data[0],
                      errD_d4_fake_bce.data[0],
                      errD_g4_fake_bce.data[0],
                      errD_g4_fake_mse.data[0],
                      errD_g4_fake_ssim.data[0],
                      d4_real_mean,
                      d4_fake_mean))
        torch.save(lapnet4_gen.state_dict(),
                   '%s/%s/%s/model/lapnet4_gen_epoch_%d.pth' % (opt.outf, opt.dataset, opt.model, epoch))
        torch.save(lapnet4_disc.state_dict(),
                   '%s/%s/%s/model/lapnet4_disc_epoch_%d.pth' % (opt.outf, opt.dataset, opt.model, epoch))
        vutils.save_image(g4_target,
                          '%s/%s/%s/image/l%d_real_samples_epoch_%03d.png' % (
                          opt.outf, opt.dataset, opt.model, 4, epoch),
                          normalize=True)
        vutils.save_image(g4_output.data,
                          '%s/%s/%s/image/l%d_fake_samples_epoch_%02d.png' % (
                          opt.outf, opt.dataset, opt.model, 4, epoch),
                          normalize=True)

        # training the whole model from all the sub-models
        lapnet_gen = lapgan.LAPGAN(channels, opt.ngpu, lapnet1, lapnet2_gen, lapnet3_gen, lapnet4_gen)
        optimizer_lapnet_gen = optim.Adam(lapnet_gen.parameters(), lr=opt.lr, betas=(0.5, 0.999))

        for idx, (data, _) in enumerate(trainloader, 0):
            if data.size(0) != opt.batch_size:
                continue

            data_array = data.numpy()
            for i in range(opt.batch_size):
                g4_target_temp = data_array[i]  # 1x64x64
                g4_target[i] = torch.from_numpy(g4_target_temp)
                for j in range(channels):
                    g1_input[i, j, :, :] = torch.from_numpy(
                        np.reshape(sensing_matrix_left.dot(data_array[i, j].flatten()), (m1, m2)))

            # Train lapnet_disc with true images
            g1_input_var = Variable(g1_input)
            g4_target_var = Variable(g4_target)
            optimizer_lapnet4_disc.zero_grad()
            d4_output = lapnet4_disc(g4_target_var)
            d4_label_var = Variable(label.fill_(real_label))
            errD_d4_real_bce = criterion_bce(d4_output, d4_label_var)
            errD_d4_real_bce.backward()
            d4_real_mean = d4_output.data.mean()

            # Train lapnet_disc with fake images
            g4_output = lapnet_gen(g1_input_var, g1_input_var)
            d4_output = lapnet4_disc(g4_output.detach())
            d4_label_var = Variable(label.fill_(fake_label))
            errD_d4_fake_bce = criterion_bce(d4_output, d4_label_var)
            errD_d4_fake_bce.backward()
            optimizer_lapnet4_disc.step()

            # Train lapnet_gen with fake images, lapgen_disc is not updated
            optimizer_lapnet_gen.zero_grad()
            d4_label_var = Variable(label.fill_(real_label))
            d4_output = lapnet4_disc(g4_output)
            errD_g4_fake_bce = criterion_bce(d4_output, d4_label_var)
            errD_g4_fake_ssim = criterion_ssim5(g4_output, g4_target_var)
            errD_g4_fake_mse = criterion_mse(g4_output, g4_target_var)
            errD_g4 = (1 - opt.w_loss_ssim - opt.w_loss_mse) * errD_g4_fake_bce +\
                      opt.w_loss_mse * errD_g4_fake_mse + \
                      opt.w_loss_ssim * errD_g4_fake_ssim
            errD_g4.backward()
            optimizer_lapnet_gen.step()
            criterion_ssim5.w_x.weight.data += abs(criterion_ssim5.w_x.weight.min().data[0])
            d4_fake_mean = d4_output.data.mean()
            print('Level %d [%d/%d][%d/%d] errD_real: %.4f, errD_fake: %.4f, errG_bce: %.4f errG_mse: %.4f,'
                  'errG_ssim: %.4f, D(x): %.4f, D(G(z)): %.4f' % (
                      5, epoch, epochs, idx, len(trainloader),
                      errD_d4_real_bce.data[0],
                      errD_d4_fake_bce.data[0],
                      errD_g4_fake_bce.data[0],
                      errD_g4_fake_mse.data[0],
                      errD_g4_fake_ssim.data[0],
                      d4_real_mean,
                      d4_fake_mean))

            if idx % 100 == 0:
                val(5, m1, m2, channels, valloader, sensing_matrix_left, g1_input, g2_target, g4_target, lapnet1,
                    lapnet2_gen, lapnet_gen, criterion_mse)

        torch.save(lapnet_gen.state_dict(),
                   '%s/%s/%s/model/lapnet_gen_epoch_%d.pth' % (opt.outf, opt.dataset, opt.model, epoch))
        torch.save(lapnet4_disc.state_dict(),
                   '%s/%s/%s/model/lapnet_disc_epoch_%d.pth' % (opt.outf, opt.dataset, opt.model, epoch))
        vutils.save_image(g4_target,
                          '%s/%s/%s/image/l%d_real_samples_epoch_%03d.png' % (
                          opt.outf, opt.dataset, opt.model, 5, epoch),
                          normalize=True)
        vutils.save_image(g4_output.data,
                          '%s/%s/%s/image/l%d_fake_samples_epoch_%02d.png' % (
                          opt.outf, opt.dataset, opt.model, 5, epoch),
                          normalize=True)


def main():
    train_loader, val_loader = data_loader()
    train(opt.epochs, train_loader, val_loader)


if __name__ == '__main__':
    main()
