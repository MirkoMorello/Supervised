# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.2
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# ----
# # <center>Dataset Preprocessing
#

# %%

import os
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import pandas as pd
import pickle
import cv2
import gc


from torch.nn import Conv2d, MaxPool2d, Linear, ReLU, BatchNorm2d, Dropout, Flatten, Sequential, Module, GELU, LeakyReLU, BatchNorm2d
from torch.utils.tensorboard import SummaryWriter
from torch.utils.data import Dataset, DataLoader
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import confusion_matrix
from torchvision import transforms
import seaborn as sns
from PIL import Image
from tqdm import tqdm
from torchsummary import summary

from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

    

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# %%
# %reload_ext tensorboard
# %tensorboard --logdir={experiment_name}

# %%
# download dataset, if it doesn't exist

if not os.path.exists('dataset'):
    os.makedirs('dataset')

if not os.path.exists('dataset/train_info.csv'):
    os.system('wget https://food-x.s3.amazonaws.com/annot.tar -O dataset/annot.tar')
    os.system('tar -xvf dataset/annot.tar -C dataset')
    os.system('rm dataset/annot.tar')

if not os.path.exists('dataset/train_set'):
    os.system('wget https://food-x.s3.amazonaws.com/train.tar -O dataset/train.tar')
    os.system('tar -xvf dataset/train.tar -C dataset')
    os.system('rm dataset/train.tar')

if not os.path.exists('dataset/test_set'):
    os.system('wget https://food-x.s3.amazonaws.com/test.tar -O dataset/test.tar')
    os.system('tar -xvf dataset/test.tar -C dataset')
    os.system('rm dataset/test.tar')
    
if not os.path.exists('dataset/val_set'):
    os.system('wget https://food-x.s3.amazonaws.com/val.tar -O dataset/val.tar')
    os.system('tar -xvf dataset/val.tar -C dataset')
    os.system('rm dataset/val.tar')


# %%
# load class list, the test set and the train set are handled in different ways since the test set doesn't have labels

def get_df(path, class_list=None):
    
    df = pd.read_csv(path, header=None)
    
    if df.shape[1] == 2:
        df.columns = ['image', 'label']
        df['class'] = df['label'].map(class_list['name'])
    else:
        df.columns = ['image']
    return df

class_list = pd.read_csv('dataset/class_list.txt', header=None, sep=' ', names=['class', 'name'], index_col=0)
class_list['index'] = class_list.index

train_df = get_df('dataset/train_info.csv', class_list)
test_df = get_df('dataset/test_info.csv', class_list)
val_df = get_df('dataset/val_info.csv', class_list)

train_df


# %%
# create a dataset class, the images are loaded on the fly, all the dataset couldn't fit in memory

class FoodDataset(Dataset):
        def __init__(self, df, root_dir, transform=None):
            self.df = df
            self.root_dir = root_dir
            self.transform = transform
            
        def __len__(self):
            return len(self.df)
        
        def __getitem__(self, idx):
            img_name = os.path.join(self.root_dir, self.df.iloc[idx, 0])
            image = Image.open(img_name)
            
            if self.transform:
                image = self.transform(image)
            
            if self.df.shape[1] == 3:
                label = self.df.iloc[idx, 1]
                return image, label
            else:
                return image


# %%
# transform to apply to the images, the training set is augmented, the validation and test set are only resized and normalized, the augmentation are not aggressive

transform_val = transforms.Compose([
    transforms.Resize((128, 128)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[.485, .456, .406], std=[.229, .224, .225]),
])

augmentation_train = transforms.Compose([
    transforms.Resize((128, 128)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[.485, .456, .406], std=[.229, .224, .225]),
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(),
    transforms.RandomAffine(degrees=90, translate=(0.1, 0.1)),
    #transforms.RandomAdjustSharpness(2, p=0.5),
    #transforms.RandomAutocontrast(0.5),
    #transforms.RandomEqualize(0.5),

])

train_ds = FoodDataset(train_df, 'dataset/train_set', augmentation_train)
test_ds = FoodDataset(test_df, 'dataset/test_set', transform_val)
val_ds = FoodDataset(val_df, 'dataset/val_set', transform_val)

train_dl = DataLoader(train_ds, batch_size=512, shuffle=True, num_workers=8)
test_dl = DataLoader(test_ds, batch_size=512, shuffle=False, num_workers=8)
val_dl = DataLoader(val_ds, batch_size=512, shuffle=False, num_workers=8)


# %% [markdown]
# ----
# # <center>Neural Networks

# %%
# create the model, the filter parameters are taken from the arguments since this is a modular design

class tinyNet(Module):
    def __init__(self, c1_filters=8, c2_filters=32, c3_filters=64, c4_filters=128, c5_filters=172, fc1_units=256):
        super(tinyNet, self).__init__()
        self.conv1 = Sequential(
            Conv2d(3, c1_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c1_filters, c2_filters, kernel_size=3, stride=1, padding=1),
            BatchNorm2d(c2_filters),
            GELU(),
            MaxPool2d(kernel_size=2, stride=2, padding=0)
        )
        self.conv2 = Sequential(
            Conv2d(c2_filters, c2_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c2_filters, c3_filters, kernel_size=3, stride=1, padding=1),
            BatchNorm2d(c3_filters),
            GELU(),
            MaxPool2d(kernel_size=2, stride=2, padding=0)
        )
        self.conv3 = Sequential(
            Conv2d(c3_filters, c3_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c3_filters, c4_filters, kernel_size=3, stride=1, padding=1),
            BatchNorm2d(c4_filters),
            GELU(),
            MaxPool2d(kernel_size=2, stride=2, padding=0)
        )

        self.conv4 = Sequential(
            Conv2d(c4_filters, c4_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c4_filters, c5_filters, kernel_size=3, stride=1, padding=1),
            BatchNorm2d(c5_filters),
            GELU(),
            MaxPool2d(kernel_size=2, stride=2, padding=0)
        )

        self.conv5 = Sequential(
            Conv2d(c5_filters, c5_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c5_filters, 32, kernel_size=3, stride=1, padding=1), # 32 is the number of filters in the last conv layer, hardcoded.
            BatchNorm2d(32),
            GELU(),
            MaxPool2d(kernel_size=2, stride=2, padding=0)
        )

        self.fc1 = Sequential(
            Linear(32*4*4, fc1_units), # 32*4*4 is the size of the tensor after the last conv layer, this parameter is hardcoded because it's the key to keep the number of parameters low (that's the secret sauce for you)
            Dropout(.2),
            GELU()
        )

        self.fc2 = Sequential(
            Linear(fc1_units, 251),
            GELU()
        )
    
    def forward(self, x):
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)
        x = self.conv4(x)
        x = self.conv5(x)
        x = x.view(-1, 32*4*4)
        x = self.fc1(x)
        x = self.fc2(x)
        return x


# %%
# the train design is modular, the model, the dataloaders, the optimizer, the scheduler and the criterion are passed as arguments, the best model is saved in the models folder based on the experiment name

def train(model, train_dl, val_dl, optimizer, scheduler, criterion, epochs, writer, experiment_name, best_experiment_name, device='cuda'):
    train_loss = []
    val_loss = []
    train_acc = []
    val_acc = []
    pbar = tqdm(total=epochs)
    n_iter = 0
    best_acc = 0
    best_running_acc = 0
    # ------------------------------ MODEL LOADING ------------------------------
    
    try:
        checkpoint = torch.load(os.path.join('models', 'best_' + best_experiment_name + '.pth'))
        best_model = checkpoint['model']
        best_optimizer = checkpoint['optimizer']
        best_criterion = checkpoint['criterion']
        start_epoch = checkpoint['epoch'] + 1
        best_acc = checkpoint['best_acc']
        
        print('Best Model loaded, evaluating...')
        best_model.to(device)
        best_model.eval()
        running_loss = 0.0
        correct = 0
        total = 0
        with torch.no_grad():
            for i, data in enumerate(val_dl):
                inputs, labels = data
                inputs, labels = inputs.to(device), labels.to(device)

                outputs = best_model(inputs)
                loss = best_criterion(outputs, labels)

                running_loss += loss.item()

                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
            print(f'Best model Loss: {running_loss/len(test_dl):.3f}, Test Acc: {100*correct/total:.3f}%')
            best_acc = 100*correct/total
        del best_model, best_criterion, best_optimizer, checkpoint
        torch.cuda.empty_cache()
        gc.collect()
        
    except Exception as e:
        print(e)
        print('No best model found, training from scratch...')
        
    
    
    for epoch in range(epochs):
        writer.add_scalar("epoch", epoch, n_iter)
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        
        # ------------------------------ TRAINING LOOP ------------------------------
        for i, data in enumerate(train_dl):
            inputs, labels = data
            inputs, labels = inputs.to(device), labels.to(device)

            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            scheduler.step()
            running_loss += loss.item()
            
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
            writer.add_scalar("train", loss.item(), n_iter)
            n_iter += 1
            
        train_loss.append(running_loss/len(train_dl))
        train_acc.append(100*correct/total)
        
        model.eval()
        running_loss = 0.0
        correct = 0
        total = 0
        
        # ------------------------------ VALIDATION LOOP ------------------------------
        with torch.no_grad():
            for i, data in enumerate(val_dl):
                inputs, labels = data
                inputs, labels = inputs.to(device), labels.to(device)
                
                outputs = model(inputs)
                loss = criterion(outputs, labels)
                
                running_loss += loss.item()
                
                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
                writer.add_scalar("val", loss.item(), n_iter)
        
        # ------------------------------ PRINTING AND MODEL SAVING ------------------------------
        
        pbar.set_description(f'Epoch: {epoch+1}/{epochs}, Train Loss: {train_loss[-1]:.3f}, Train Acc: {train_acc[-1]:.3f}%, Val Loss: {running_loss/len(val_dl):.3f}, Val Acc: {100*correct/total:.3f}%, Acc to beat: {best_acc:.3f}%, best running acc: {best_running_acc:.3f}%')
        val_loss.append(running_loss/len(val_dl))
        val_acc.append(100*correct/total)
        if val_acc[-1] > best_running_acc:
            pbar.set_description(f'Epoch: {epoch+1}/{epochs}, Train Loss: {train_loss[-1]:.3f}, Train Acc: {train_acc[-1]:.3f}%, Val Loss: {running_loss/len(val_dl):.3f}, Val Acc: {100*correct/total:.3f}%, Acc to beat: {best_acc:.3f}%, best running acc beated, saving model')
            best_running_acc = val_acc[-1]
            checkpoint = {
                'model': model,
                'optimizer': optimizer,
                'criterion': criterion,
                'epoch': epoch,
                'best_acc': best_acc,
                'scheduler': scheduler
            }
            torch.save(checkpoint, os.path.join('models', 'best_' + experiment_name + '.pth'))
        pbar.update(1)
    pbar.close()
    
    with open(os.path.join('models', experiment_name + '_train_loss.pkl'), 'wb') as f:
        pickle.dump(train_loss, f)
    with open(os.path.join('models', experiment_name + '_val_loss.pkl'), 'wb') as f:
        pickle.dump(val_loss, f)
    with open(os.path.join('models', experiment_name + '_train_acc.pkl'), 'wb') as f:
        pickle.dump(train_acc, f)
    with open(os.path.join('models', experiment_name + '_val_acc.pkl'), 'wb') as f:
        pickle.dump(val_acc, f)
    
    return val_acc

# %%
model = tinyNet(c1_filters= 16,
                c2_filters= 70,
                c3_filters= 140,
                c4_filters= 140,
                c5_filters= 32,
                fc1_units= 347).to(device)

criterion = torch.nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

experiment_name = 'tinyNetv5'

writer = SummaryWriter('runs/'+experiment_name)
epochs = 150
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, epochs, eta_min=0.0001)

print(f'the model has {sum(p.numel() for p in model.parameters())} parameters')

# %%
train(model = model,
      train_dl = train_dl,
      val_dl = val_dl,
      optimizer = optimizer,
      criterion = criterion,
      scheduler = scheduler,
      epochs = epochs,
      writer = writer,
      experiment_name = experiment_name,
      best_experiment_name = experiment_name,
      device = device)


# %%
# this plot is hard to  visualize because of the number of classes, but it's useful to see the training progress

def plot_confusion_matrix(net, test_loader):
    
    net.eval()
    gt = []
    pred = []
    with torch.no_grad():
        for el, labels in test_loader:
            el = el.to(device)
            labels = labels.to(device)
            out = net(el)
            _, predicted = torch.max(out, 1)
            gt.extend(labels.cpu().numpy())
            pred.extend(predicted.cpu().numpy())

    cm = confusion_matrix(gt, pred)
    plt.figure(figsize=(40, 40))
    sns.heatmap(cm, annot=True, fmt='g', cmap='viridis', xticklabels=class_list['name'].values, yticklabels=class_list['name'].values)
    plt.xlabel('Predicted')
    plt.ylabel('Actual')
    plt.show()

plot_confusion_matrix(model, val_dl)


# %% [markdown]
# ----
# # <center>Self Supervised Learning

# %%
# this class is completely modular, the model which will be used for the SSL is passed as an argument and the forward method is implemented to return the output of the encoder bypassing the fully connected layers
# this is handy because the encoder is the only part of the model that will be used for the transfer learning, so we can easily extract it

class SSL_RandomErasing(torch.nn.Module):
    def __init__(self, c1_filters=8, c2_filters=32, c3_filters=64, c4_filters=128, c5_filters=172, fc1_units=256):
        super().__init__()
        

        self.encoder = tinyNet(c1_filters= c1_filters,
                                c2_filters= c2_filters,
                                c3_filters= c3_filters,
                                c4_filters= c4_filters,
                                c5_filters= c5_filters,
                                fc1_units= fc1_units)

        # Decoder
        self.upconv1= Sequential(
            Conv2d(32, c5_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c5_filters, c5_filters, kernel_size=3, stride=1, padding=1),
            GELU(),
            nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        )

        self.upconv2 = Sequential(
            Conv2d(c5_filters, c4_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c4_filters, c4_filters, kernel_size=3, stride=1, padding=1),
            GELU(),
            nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        )

        self.upconv3 = Sequential(
            Conv2d(c4_filters, c3_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c3_filters, c3_filters, kernel_size=3, stride=1, padding=1),
            GELU(),
            nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        )

        self.upconv4 = Sequential(
            Conv2d(c3_filters, c2_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c2_filters, c2_filters, kernel_size=3, stride=1, padding=1),
            GELU(),
            nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        )

        self.upconv5 = Sequential(
            Conv2d(c2_filters, c1_filters, kernel_size=3, stride=1, padding='same'),
            GELU(),
            Conv2d(c1_filters, 3, kernel_size=3, stride=1, padding=1),
            GELU(),
            nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        )

    def forward(self, x):
        x1 = self.encoder.conv1(x)
        x2 = self.encoder.conv2(x1)
        x3 = self.encoder.conv3(x2)
        x4 = self.encoder.conv4(x3)
        x5 = self.encoder.conv5(x4)
        
        x = self.upconv1(x5)
        x = self.upconv2(x + x4)
        x = self.upconv3(x + x3)
        x = self.upconv4(x + x2)
        x = self.upconv5(x + x1)
        return x

        

# %%
# this is the dataset class for the SSL, it's very similar to the previous one, the only difference is that the noisy image is returned as well and no labels are needed, the noisy image are just the images with random erasing applied

class SSL_Dataset(Dataset):
    def __init__(self, df):
        self.df = df
        self.transform = transforms.Compose([
            transforms.Resize((128, 128)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[.485, .456, .406], std=[.229, .224, .225]),
        ])
        self.noisy_transform = transforms.Compose([
            transforms.RandomErasing(p=1, scale=(0.1, 0.3), ratio=(0.3, 3), value=0, inplace=False),
        ])
        
    def __len__(self):
        return len(self.df)
    
    def __getitem__(self, idx):
        img_name = self.df.iloc[idx, 0]
        image = Image.open(img_name)
        image = self.transform(image)
        noisy_image = self.noisy_transform(image)
        return image, noisy_image


# %%
# here we create a custom dataset containing both the training and the test set

img_paths = train_df['image']
img_paths = img_paths.apply(lambda x: 'dataset/train_set/' + x)
img_paths = pd.concat([img_paths, test_df['image'].apply(lambda x: 'dataset/test_set/' + x)])


ssl_df = pd.DataFrame({'image': img_paths})
ssl_ds = SSL_Dataset(ssl_df)
ssl_dl = DataLoader(ssl_ds, batch_size=800, shuffle=False, num_workers=8)

# %%
idx = np.random.randint(0, len(ssl_ds))
clean_image, noisy_image = ssl_ds[idx]


img_name = ssl_ds.df.iloc[idx, 0]


mean = torch.tensor([0.485, 0.456, 0.406])
std = torch.tensor([0.229, 0.224, 0.225])
clean_image = clean_image * std[:, None, None] + mean[:, None, None]  # unnormalize
noisy_image = noisy_image * std[:, None, None] + mean[:, None, None]


clean_image = torch.clamp(clean_image, 0, 1)
noisy_image = torch.clamp(noisy_image, 0, 1)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))

ax1.imshow(clean_image.permute(1, 2, 0)) # permute to change the order of the channels, from CxHxW to HxWxC, which is the format that matplotlib expects because the image is a tensor
ax1.set_title('Clean Image')
ax1.axis('off')

ax2.imshow(noisy_image.permute(1, 2, 0)) 
ax2.set_title('Noisy Image')
ax2.axis('off')

plt.tight_layout()
print(f'showing image {img_name}')
plt.show()


# %%
# this is a simple training loop for the SSL

def train_ssl(model, ssl_dl, optimizer, loss, epochs, device, experiment_name):
    model.train()
    train_loss = []
    train_loss_mean = []
    print(f'training {experiment_name}')
    for epoch in range(epochs):
        running_loss = 0.0
        progress_bar = tqdm(ssl_dl, desc=f'Epoch {epoch+1}/{epochs}', unit='batch')
        
        for data in progress_bar:
            clean, noisy = data
            clean, noisy = clean.to(device), noisy.to(device)
            optimizer.zero_grad()
            noisy_out = model(noisy)
            loss_out = loss(noisy_out, clean)
            loss_out.backward()
            optimizer.step()
            running_loss += loss_out.item()
            progress_bar.set_postfix({'Loss': loss_out.item(), 'Mean Loss': (running_loss/(progress_bar.n + 1))})
            train_loss.append(loss_out.item())
            train_loss_mean.append(running_loss/(progress_bar.n + 1))
        torch.save(model, f'models/ssl/ssl_{experiment_name}.pth')
        
    with open(os.path.join('models', f'ssl_{experiment_name}_train_loss.pkl'), 'wb') as f:
        pickle.dump(train_loss, f)
    with open(os.path.join('models', f'ssl_{experiment_name}_train_loss_mean.pkl'), 'wb') as f:
        pickle.dump(train_loss_mean, f)
    return train_loss


# %%
ssl_model = SSL_RandomErasing(
                    c1_filters= 8,
                    c2_filters= 32,
                    c3_filters= 64,
                    c4_filters= 128,
                    c5_filters= 172,
                    fc1_units= 256
                ).to(device)
ssl_optimizer = torch.optim.Adam(ssl_model.parameters(), lr=0.001)
ssl_loss = torch.nn.MSELoss()

train_ssl(model=ssl_model,
          ssl_dl=ssl_dl,
          optimizer=ssl_optimizer,
          loss=ssl_loss,
          epochs=60,
          device=device,
          experiment_name=experiment_name)

# %%
# again, just to visualize the results

idx = np.random.randint(0, len(ssl_ds))
clean_image, noisy_image = ssl_ds[idx]

img_name = ssl_ds.df.iloc[idx, 0]

mean = torch.tensor([0.485, 0.456, 0.406])
std = torch.tensor([0.229, 0.224, 0.225])
clean_image = clean_image * std[:, None, None] + mean[:, None, None]
noisy_image = noisy_image * std[:, None, None] + mean[:, None, None]

clean_image = torch.clamp(clean_image, 0, 1)
noisy_image = torch.clamp(noisy_image, 0, 1)

with torch.no_grad():
    noisy_image_tensor = noisy_image.unsqueeze(0).to(device)
    reconstructed_image = ssl_model(noisy_image_tensor).squeeze(0).cpu()

reconstructed_image = reconstructed_image * std[:, None, None] + mean[:, None, None]
reconstructed_image = torch.clamp(reconstructed_image, 0, 1)

fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 5))
ax1.imshow(clean_image.permute(1, 2, 0))
ax1.set_title('Clean')
ax1.axis('off')

ax2.imshow(noisy_image.permute(1, 2, 0))
ax2.set_title('Noisy')
ax2.axis('off')

ax3.imshow(reconstructed_image.permute(1, 2, 0))
ax3.set_title('Reconstructed')
ax3.axis('off')

plt.tight_layout()
print(f'Showing image {img_name}')
plt.show()

# %% [markdown]
# ----
# # <center>Transfer Learning from SSL

# %%
# this is the transfer learning part, the encoder is extracted from the SSL model and used to train a new model

ssl_model_ = torch.load(f'models/ssl/ssl_{experiment_name}.pth')

tinynet = ssl_model_.encoder

optimizer = torch.optim.Adam(tinynet.parameters(), lr=0.001)
criterion = torch.nn.CrossEntropyLoss()
epochs = 150
writer = SummaryWriter('runs/tinynet_ssl')
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, epochs, eta_min=0.0001)


train(model=tinynet,
        train_dl=train_dl,
        val_dl=val_dl,
        optimizer=optimizer,
        criterion=criterion,
        scheduler=scheduler,
        epochs=epochs,
        writer=writer,
        experiment_name=experiment_name+ '_ssl',
        best_experiment_name=experiment_name + '_ssl',
        device=device)

# %%
plot_confusion_matrix(tinynet, val_dl)

# %% [markdown]
# ----
# # <center>Plots

# %%
#experiment_name = 'tinyNetv3'

train_acc = pickle.load(open(f'models/{experiment_name}_train_acc.pkl', 'rb'))
val_acc = pickle.load(open(f'models/{experiment_name}_val_acc.pkl', 'rb'))
train_loss = pickle.load(open(f'models/{experiment_name}_train_loss.pkl', 'rb'))
val_loss = pickle.load(open(f'models/{experiment_name}_val_loss.pkl', 'rb'))

plt.figure(figsize=(30, 10))
plt.subplot(1, 2, 1)
plt.plot(train_acc, label='train')
plt.plot(val_acc, label='val')
plt.title('Accuracy')
plt.xlabel('Epoch')
plt.ylabel('Accuracy')
plt.legend()

plt.subplot(1, 2, 2)
plt.plot(train_loss, label='train')
plt.plot(val_loss, label='val')
plt.title('Loss')
plt.xlabel('Epoch')
plt.ylabel('Loss')
plt.legend()
plt.show()


# %%
train_acc_ssl = pickle.load(open(f'models/{experiment_name}_ssl_train_acc.pkl', 'rb'))
val_acc_ssl = pickle.load(open(f'models/{experiment_name}_ssl_val_acc.pkl', 'rb'))
train_loss_ssl = pickle.load(open(f'models/{experiment_name}_ssl_train_loss.pkl', 'rb'))
val_loss_ssl = pickle.load(open(f'models/{experiment_name}_ssl_val_loss.pkl', 'rb'))

plt.figure(figsize=(30, 10))
plt.subplot(1, 2, 1)
plt.plot(train_acc_ssl, label='train')
plt.plot(val_acc_ssl, label='val')
plt.title('Accuracy')
plt.xlabel('Epoch')
plt.ylabel('Accuracy')
plt.legend()

plt.subplot(1, 2, 2)
plt.plot(train_loss_ssl, label='train')
plt.plot(val_loss_ssl, label='val')
plt.title('Loss')
plt.xlabel('Epoch')
plt.ylabel('Loss')
plt.legend()
plt.show()

# %%
plt.figure(figsize=(30, 10))
plt.subplot(1, 2, 1)
plt.plot(val_acc, label='tinynet')
plt.plot(val_acc_ssl, label='tinynet_ssl')
plt.title('Accuracy')
plt.xlabel('Epoch')
plt.ylabel('Accuracy')
plt.legend()

plt.subplot(1, 2, 2)
plt.plot(val_loss, label='tinynet')
plt.plot(val_loss_ssl, label='tinynet_ssl')
plt.title('Loss')
plt.xlabel('Epoch')
plt.ylabel('Loss')
plt.legend()
plt.show()


# %%
ssl_loss = pickle.load(open(f'models/ssl_{experiment_name}_train_loss_mean.pkl', 'rb'))

plt.figure(figsize=(30, 10))
plt.plot(ssl_loss)
plt.title('SSL Loss')
plt.xlabel('Batch')
plt.ylabel('Loss')
plt.show()


# %%
# load the model
experiment_name = 'tinyNetClassic_ssl'

checkpoint = torch.load(f'models/best_{experiment_name}.pth')
model = checkpoint['model']
model.to(device)
model.eval()




# %%
# count the number of images that there are for every class, in order to see if the model is biased towards some classes

count_classes = val_df['class'].value_counts()

plt.figure(figsize=(40, 10))
plt.bar(count_classes.index, count_classes.values)
plt.xticks(rotation=90)

plt.title('Class Count')
plt.xlabel('Class')
plt.ylabel('Count')
plt.show()


# %%
# calculate the precision for every class, this is useful to see if the model is biased towards some classes

def class_precision(model, test_dl, class_labels):
    model.eval()
    gt = []
    pred = []
    with torch.no_grad():
        for el, labels in test_dl:
            el = el.to(device)
            labels = labels.to(device)
            out = model(el)
            _, predicted = torch.max(out, 1)
            gt.extend(labels.cpu().numpy())
            pred.extend(predicted.cpu().numpy())

    class_indices = sorted(set(gt))
    
    cm = confusion_matrix(gt, pred, labels=class_indices)
    precision = np.diag(cm) / np.sum(cm, axis=1)
    
    precision_dict = {}
    for label in class_labels:
        if label in class_indices:
            precision_dict[label] = precision[label]
        else:
            precision_dict[label] = 0.0  # Assign 0.0 precision for missing classes
    
    return precision_dict



# create a tuple with the class name and the precision, so that i can later sort it
precision = class_precision(model, val_dl, class_list['index'].values)
precision = {k: v for k, v in sorted(precision.items(), key=lambda item: item[1], reverse=True)}
precision = {class_list.loc[k, 'name']: v for k, v in precision.items()}


plt.figure(figsize=(40, 10))
plt.bar(precision.keys(), precision.values())
plt.xticks(rotation=90)
plt.title('Class Precision')
plt.xlabel('Class')
plt.ylabel('Precision')
plt.show()



# %%
import matplotlib.pyplot as plt
import numpy as np
import torch
from sklearn.metrics import confusion_matrix

def class_recall(model, test_dl, class_labels):
    model.eval()
    gt, pred = [], []
    with torch.no_grad():
        for el, labels in test_dl:
            el, labels = el.to(device), labels.to(device)
            out = model(el)
            _, predicted = torch.max(out, 1)
            gt.extend(labels.cpu().numpy())
            pred.extend(predicted.cpu().numpy())

    classes = sorted(set(gt))
    class_indices = {label: i for i, label in enumerate(classes)}
    cm = confusion_matrix(gt, pred, labels=classes)
    recall = np.nan_to_num(np.diag(cm) / np.sum(cm, axis=0), nan=0.0)
    
    return {label: recall[class_indices[label]] if label in class_indices else 0.0 for label in class_labels}

recall = class_recall(model, val_dl, class_list['index'].values)
recall = {class_list.loc[k, 'name']: v for k, v in recall.items()}

sorted_recall = dict(sorted(recall.items(), key=lambda x: x[1], reverse=True))
class_names, recall_values = list(sorted_recall.keys()), list(sorted_recall.values())

plt.figure(figsize=(40, 10))
plt.bar(range(len(class_names)), recall_values)
plt.xticks(range(len(class_names)), class_names, rotation=90)
plt.title('Class Recall')
plt.xlabel('Class')
plt.ylabel('Recall')
plt.ylim(0, 1)
plt.tight_layout()
plt.show()


# %%
def class_f1(model, test_dl, class_labels):
    model.eval()
    gt, pred = [], []
    with torch.no_grad():
        for el, labels in test_dl:
            el, labels = el.to(device), labels.to(device)
            out = model(el)
            _, predicted = torch.max(out, 1)
            gt.extend(labels.cpu().numpy())
            pred.extend(predicted.cpu().numpy())

    classes = sorted(set(gt))
    class_indices = {label: i for i, label in enumerate(classes)}
    cm = confusion_matrix(gt, pred, labels=classes)
    
    precision = np.nan_to_num(np.diag(cm) / np.sum(cm, axis=1), nan=0.0)
    recall = np.nan_to_num(np.diag(cm) / np.sum(cm, axis=0), nan=0.0)
    f1 = np.nan_to_num(2 * (precision * recall) / (precision + recall), nan=0.0)
    
    return {label: f1[class_indices[label]] if label in class_indices else 0.0 for label in class_labels}

f1 = class_f1(model, val_dl, class_list['index'].values)
f1 = {class_list.loc[k, 'name']: v for k, v in f1.items()}
sorted_f1 = dict(sorted(f1.items(), key=lambda x: x[1], reverse=True))
class_names, f1_values = list(sorted_f1.keys()), list(sorted_f1.values())

plt.figure(figsize=(40, 10))
plt.bar(class_names, f1_values)
plt.xticks(rotation=90)
plt.title('Class F1')
plt.xlabel('Class')
plt.ylabel('F1')
plt.ylim(0, 1)
plt.tight_layout()
plt.show()


# %%
# calculate mean precision, recall and f1

mean_precision = np.mean(list(precision))

mean_recall = np.mean(list(recall))

mean_f1 = np.mean(list(f1))

print(f'Mean Precision: {mean_precision:.3f}')
print(f'Mean Recall: {mean_recall:.3f}')
print(f'Mean F1: {mean_f1:.3f}')

# %%
import torch
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix
from torch.utils.data import DataLoader

# Assuming `device`, `model`, `val_dl`, and `class_list` are defined and loaded appropriately

# Helper function to calculate confusion matrix and related metrics
def get_confusion_matrix(model, test_dl):
    model.eval()
    gt, pred = [], []
    with torch.no_grad():
        for el, labels in test_dl:
            el = el.to(device)
            labels = labels.to(device)
            out = model(el)
            _, predicted = torch.max(out, 1)
            gt.extend(labels.cpu().numpy())
            pred.extend(predicted.cpu().numpy())
    return gt, pred

# Helper function to calculate precision, recall, and f1 score
def calculate_metrics(cm):
    precision = np.diag(cm) / np.sum(cm, axis=1)
    recall = np.diag(cm) / np.sum(cm, axis=0)
    f1 = 2 * (precision * recall) / (precision + recall)
    return np.nan_to_num(precision, nan=0.0), np.nan_to_num(recall, nan=0.0), np.nan_to_num(f1, nan=0.0)

# Calculate the confusion matrix and metrics
gt, pred = get_confusion_matrix(model, val_dl)
classes = sorted(set(gt))
cm = confusion_matrix(gt, pred, labels=classes)
precision, recall, f1 = calculate_metrics(cm)

# Find indices of images with lowest scores
low_f1_indices = np.argsort(f1)[:5]
low_recall_indices = np.argsort(recall)[:5]
low_precision_indices = np.argsort(precision)[:5]

# Helper function to plot images
def plot_images(indices, title, gt_labels, pred_labels, dataset, num_images=5):
    mean = torch.tensor([0.485, 0.456, 0.406])
    std = torch.tensor([0.229, 0.224, 0.225])
    
    fig, axes = plt.subplots(1, num_images, figsize=(20, 5))
    for i, idx in enumerate(indices):
        img, label = dataset[idx]
        img = img * std[:, None, None] + mean[:, None, None]  # Unnormalize
        img = torch.clamp(img, 0, 1)
        
        axes[i].imshow(img.permute(1, 2, 0))
        axes[i].set_title(f'True: {class_list.loc[gt_labels[idx], "name"]}\nPred: {class_list.loc[pred_labels[idx], "name"]}')
        axes[i].axis('off')
    
    plt.suptitle(title)
    plt.tight_layout()
    plt.show()

# Plot images with lowest F1 scores
plot_images(low_f1_indices, 'Lowest F1 Scores', gt, pred, val_dl.dataset)

# Plot images with lowest Recall scores
plot_images(low_recall_indices, 'Lowest Recall Scores', gt, pred, val_dl.dataset)

# Plot images with lowest Precision scores
plot_images(low_precision_indices, 'Lowest Precision Scores', gt, pred, val_dl.dataset)


# %% [markdown]
# ----
# # <center>SIFT and Bag of Words for feature extraction

# %%
def extract_sift_features(image_path):
    image = cv2.imread(image_path)
    if image is None:
        print(f"Failed to load image at {image_path}")
        return np.empty((0, 128), dtype=np.float32)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # resize image
    gray = cv2.resize(gray, (128, 128))
    sift = cv2.SIFT_create()
    keypoints, descriptors = sift.detectAndCompute(gray, None)
    if descriptors is None:
        # No descriptors found, return an empty array
        descriptors = np.empty((0, 128), dtype=np.float32)
    return descriptors

def extract_sift_features_from_df(df, root_dir):
    features = []
    for i in tqdm(range(len(df))):
        img_name = os.path.join(root_dir, df.iloc[i, 0])
        features.append(extract_sift_features(img_name))
    return features



# %%
def extract_bag_of_words(features, dictionary):
    bow = []
    for i in tqdm(range(len(features))):
        if features[i].size > 0:  # Skip if features[i] is empty
            words = dictionary.predict(features[i].astype(np.float32))
            bow.append(np.bincount(words, minlength=dictionary.n_clusters))
        else:
            bow.append(np.zeros(dictionary.n_clusters, dtype=np.float32))  # Append zeros if no features
    return np.array(bow)


# %%
def extract_save_bag_of_words(features, dictionary, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    for i in tqdm(range(len(features))):
        if features[i].size > 0:  # Skip if features[i] is empty
            words = dictionary.predict(features[i].astype(np.float32))
            bow_features = np.bincount(words, minlength=dictionary.n_clusters)
        else:
            bow_features = np.zeros(dictionary.n_clusters, dtype=np.float32)  # Append zeros if no features
        # take the name from the df
        filename = f"bow_features_{i}.npy"
        np.save(os.path.join(output_dir, filename), bow_features)


# %%
force_recompute_sift = False
force_recompute_bow = False

if not os.path.exists('dataset/train_features.pkl') or force_recompute_sift:
    train_features = extract_sift_features_from_df(train_df, 'dataset/train_set')
    pickle.dump(train_features, open('dataset/train_features.pkl', 'wb'))
    #test_features = extract_sift_features_from_df(test_df, 'dataset/test_set')
    #pickle.dump(test_features, open('dataset/test_features.pkl', 'wb'))
    val_features = extract_sift_features_from_df(val_df, 'dataset/val_set')
    pickle.dump(val_features, open('dataset/val_features.pkl', 'wb'))
else:
    train_features = pickle.load(open('dataset/train_features.pkl', 'rb'))
    val_features = pickle.load(open('dataset/val_features.pkl', 'rb'))

# %%
n_clusters = 1000

if not os.path.exists('dataset/dictionary.pkl') or force_recompute_bow:
    dictionary = MiniBatchKMeans(n_clusters=n_clusters, random_state=0)
    dictionary.fit(np.concatenate(train_features))
    pickle.dump(dictionary, open('dataset/dictionary.pkl', 'wb'))
else:
    dictionary = pickle.load(open('dataset/dictionary.pkl', 'rb'))


# %%
extract_save_bag_of_words(train_features, dictionary, 'dataset/train_bow')
extract_save_bag_of_words(val_features, dictionary, 'dataset/val_bow')


# %%
#train_bow = extract_bag_of_words(train_features, dictionary)
#del train_features
#extract_bag_of_words(val_features, dictionary)
#del val_features

# %%
# SVM
# clf = SVC()
# clf.fit(train_bow, train_df.iloc[:, 1], )
# train_pred = clf.predict(train_bow)
# val_pred = clf.predict(val_bow)
# # save to file
# pickle.dump(train_pred, open('dataset/svm_train_pred.pkl', 'wb'))
# pickle.dump(val_pred, open('dataset/svm_val_pred.pkl', 'wb'))

# train_acc = accuracy_score(train_df.iloc[:, 1], train_pred)
# val_acc = accuracy_score(val_df.iloc[:, 1], val_pred)

# print(f'SVM Train Accuracy: {train_acc:.3f}, Val Accuracy: {val_acc:.3f}')

# %% [markdown]
# ----
# # <center>CNN with BoW features

# %%
class FoodBowDataset(Dataset):
    def __init__(self, df, bow_dir, root_dir, transform=None):
        self.df = df
        self.bow_dir = bow_dir
        self.root_dir = root_dir
        self.transform = transform
        
    def __len__(self):
        return len(self.df)
    
    def __getitem__(self, idx):
        bow = np.load(os.path.join(self.bow_dir, f'bow_features_{idx}.npy'))
        bow = bow.astype(np.float32)  # Convert bow features to float
        img_name = os.path.join(self.root_dir, self.df.iloc[idx, 0])
        image = Image.open(img_name)

        if self.transform:
            image = self.transform(image)

        if self.df.shape[1] == 3:
            label = self.df.iloc[idx, 1]
            return bow, image, label
        return bow, image


# %%
transform = transforms.Compose([
    transforms.Resize((128, 128)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[.485, .456, .406], std=[.229, .224, .225]),
])

train_bow_ds = FoodBowDataset(train_df, 'dataset/train_bow', 'dataset/train_set', transform)
val_bow_ds = FoodBowDataset(val_df, 'dataset/val_bow', 'dataset/val_set', transform)

train_bow_dl = DataLoader(train_bow_ds, batch_size=256, shuffle=True, num_workers=8)
val_bow_dl = DataLoader(val_bow_ds, batch_size=256, shuffle=False, num_workers=8)


# %%
class FoodBowCNN(nn.Module):
    def __init__(self, n_clusters, n_classes):
        super(FoodBowCNN, self).__init__()
        self.n_clusters = n_clusters
        self.n_classes = n_classes
        
        # Convolutional layers for image feature extraction
        self.conv1 = nn.Conv2d(3, 32, kernel_size=3, stride=1, padding=1)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, stride=1, padding=1)
        self.pool = nn.MaxPool2d(kernel_size=2, stride=2)
        self.dropout = nn.Dropout(p=0.25)
        
        # Fully connected layers for image features
        self.fc1 = nn.Linear(64 * 32 * 32, 512)
        self.fc2 = nn.Linear(512, 256)
        
        # Fully connected layers for BoW features
        self.bow_fc1 = nn.Linear(n_clusters, 256)
        self.bow_fc2 = nn.Linear(256, 128)
        
        # Fully connected layers for combined features
        self.combined_fc1 = nn.Linear(256 + 128, 512)
        self.combined_fc2 = nn.Linear(512, n_classes)
        
        self.relu = nn.ReLU()
        
    def forward(self, bow_features, image):
        # Image feature extraction
        x = self.pool(self.relu(self.conv1(image)))
        x = self.pool(self.relu(self.conv2(x)))
        x = x.view(-1, 64 * 32 * 32)
        x = self.relu(self.fc1(x))
        img_features = self.relu(self.fc2(x))
        
        # BoW feature processing
        bow_features = self.relu(self.bow_fc1(bow_features))
        bow_features = self.relu(self.bow_fc2(bow_features))
        
        # Combine image and BoW features
        combined_features = torch.cat((img_features, bow_features), dim=1)
        
        # Final classification
        x = self.relu(self.combined_fc1(combined_features))
        x = self.dropout(x)
        out = self.combined_fc2(x)
        
        return out


# %%
def bow_train(model, train_dl, val_dl, optimizer, criterion, epochs):
    train_loss = []
    val_loss = []
    train_acc = []
    val_acc = []

    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        correct = 0
        total = 0
        for i, data in enumerate(train_dl):
            bow, image, labels = data
            bow, image, labels = bow.to(device), image.to(device), labels.to(device)
            
            optimizer.zero_grad()
            
            outputs = model(bow, image)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            
            running_loss += loss.item()
            
            _, predicted = torch.max(outputs.data, 1)
            total += labels.size(0)
            correct += (predicted == labels).sum().item()
            
        train_loss.append(running_loss/len(train_dl))
        train_acc.append(100*correct/total)
        
        model.eval()
        running_loss = 0.0
        correct = 0
        total = 0
        with torch.no_grad():
            for i, data in enumerate(val_dl):
                bow, image, labels = data
                bow, image, labels = bow.to(device), image.to(device), labels.to(device)
                
                outputs = model(bow, image)
                loss = criterion(outputs, labels)
                
                running_loss += loss.item()
                
                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
                
        val_loss.append(running_loss/len(val_dl))
        val_acc.append(100*correct/total)
        
        print(f'Epoch: {epoch+1}/{epochs}, Train Loss: {train_loss[-1]:.3f}, Train Acc: {train_acc[-1]:.3f}%, Val Loss: {val_loss[-1]:.3f}, Val Acc: {val_acc[-1]:.3f}%')
        
model = FoodBowCNN(n_clusters, 251).to(device)
criterion = torch.nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
epochs = 100
print(f'the model has {sum(p.numel() for p in model.parameters())} parameters')

train(model, train_bow_dl, val_bow_dl, optimizer, criterion, epochs)


# %% [markdown]
# ----
# # <center> Hyperparameter tuning

# %%
import optuna
from optuna.pruners import BasePruner

class MaxParameterPruner(BasePruner):
    def __init__(self, max_params):
        self.max_params = max_params

    def prune(self, study, trial):
            # Define the hyperparameters to tune
        c1_filters = trial.suggest_int('num_filters1', 8, 32)
        c2_filters = trial.suggest_int('num_filters2', 16, 64)
        c3_filters = trial.suggest_int('num_filters3', 32, 128)
        c4_filters = trial.suggest_int('num_filters4', 64, 256)
        c5_filters = trial.suggest_int('num_filters5', 64, 256)
        fc1_units = trial.suggest_int('fc1_units', 128, 512)

        # Create the model with the given hyperparameters
        model = tinyNet(c1_filters, c2_filters, c3_filters, c4_filters, c5_filters, fc1_units).to(device)

        # Calculate the number of parameters
        num_params = sum(p.numel() for p in model.parameters())

        # If the number of parameters exceeds 1 million, return a large negative value
        if num_params > self.max_params:
            study.set_user_attr('num_params', num_params)
            return optuna.exceptions.TrialPruned()


def objective(trial):
    # Define the hyperparameters to tune
    c1_filters = trial.suggest_int('num_filters1', 8, 32)
    c2_filters = trial.suggest_int('num_filters2', 16, 64)
    c3_filters = trial.suggest_int('num_filters3', 32, 128)
    c4_filters = trial.suggest_int('num_filters4', 64, 256)
    c5_filters = trial.suggest_int('num_filters5', 64, 256)
    fc1_units = trial.suggest_int('fc1_units', 128, 512)

    # Create the model with the given hyperparameters

    model = tinyNet(c1_filters, c2_filters, c3_filters, c4_filters, c5_filters, fc1_units).to(device)

    # Calculate the number of parameters

    train_ds = FoodDataset(get_fraction_of_data(train_df, 0.1), 'dataset/train_set', aug_transform)
    val_ds = FoodDataset(get_fraction_of_data(val_df, 0.1), 'dataset/val_set', transform)

    train_dl = DataLoader(train_ds, batch_size=128, shuffle=True, num_workers=8)
    val_dl = DataLoader(val_ds, batch_size=128, shuffle=False, num_workers=8)

    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = torch.nn.CrossEntropyLoss()
    epochs = 15
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, epochs, eta_min=0.0001)
    experiment_name = 'tinyNetHT'
    writer = SummaryWriter('runs/'+experiment_name)


    accuracy = train(model=model,
                     train_dl=train_dl, 
                     val_dl=val_dl, 
                     optimizer=optimizer, 
                     criterion=criterion, 
                     scheduler=scheduler,
                     epochs=epochs, 
                     writer=writer, 
                     experiment_name=experiment_name, 
                     best_experiment_name='tinyNetv2', 
                     device=device)

    return accuracy

def get_fraction_of_data(df, fraction, stratified=True):
    if stratified:
        _, train_df = train_test_split(df, test_size=fraction, stratify=df['label'])
    else:
        _, train_df = train_test_split(df, test_size=fraction)
    # return DataLoader(FoodDataset(df.iloc[train_df], 'dataset/train_set', transform), batch_size=128, shuffle=True, num_workers=8)
    return train_df


# %%
get_fraction_of_data(train_df, 0.1).head(4)


# %%
def run_trial(trial):
    try:
        accuracy = objective(trial)
        return accuracy
    except Exception as e:
        raise optuna.exceptions.TrialPruned()


# %%
study = optuna.create_study(direction='maximize', study_name='tinyNetHT')
study.optimize(objective, n_trials=100)

study.best_params

# %% [markdown]
# ----
# # <center>Playground

# %%
# extract sift from 1/4 of the images in the training set
#train_14_features = extract_sift_features_from_df(train_df.iloc[::4], 'dataset/train_set')

# %%
# extract bow from 1/4 of the images in the training set
#dictionary = MiniBatchKMeans(n_clusters=1000, random_state=0)
#ictionary.fit(np.concatenate(train_14_features))
#train_14_bow = extract_bag_of_words(train_14_features, dictionary)

# %%
# visualize the bow of the first image
plt.bar(range(len(train_14_bow[0])), train_14_bow[0])
plt.xlabel('Visual Word Index')
plt.ylabel('Frequency')
plt.title('Bag of Words')
plt.show()

