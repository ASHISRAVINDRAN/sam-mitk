# Segment Anything model for MITK
This repo contains Segment Anything model wrapper to be used with MITK.
The Medical Imaging Interaction Toolkit (MITK) is a free open-source software system for development of interactive medical image processing software. MITK combines the Insight Toolkit (ITK) and the Visualization Toolkit (VTK) with an application framework. MITK's SAM 2D tool uses this wrapper as its backend for inferencing.

The code runs a daemon monitoring any given folder any input files (`*.nii.gz`) and prompt points in a `trigger.csv` file placed inside the input folder.
Embeddings generated per file is cached for future use during the runtime.

## Installation
```bash
pip install git+https://github.com/ASHISRAVINDRAN/sam-mitk.git
```
The code requires `Python>=3.8`, as well as `Pytorch>=1.7` and `torchvision>=0.8`. Please follow the instructions [here](https://pytorch.org/get-started/locally/) to install both PyTorch and TorchVision dependencies. Installing both PyTorch and TorchVision with CUDA support is strongly recommended.

## Usage
The program can be used independent of MITK.
```bash
python run_inference_daemon.py --input-folder ./input --output-folder ./output --trigger-file trigger.csv --model-type vit_b --checkpoint ./vit_b.pth --device cuda
```
