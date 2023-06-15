import time
from typing import Dict
import csv
import torch
import sys
import os
import argparse
from pkg_resources import require
from pathlib import Path
from segment_anything import sam_model_registry, SamPredictor
import multiprocessing as mp
import numpy as np
import glob
import SimpleITK as sitk
import cv2


class Feature:
    def __init__(self, input_size: tuple = None, original_size: tuple = None, feature_space: np.ndarray = None):
        self.input_size = input_size
        self.original_size = original_size
        self.feature_embeddings = feature_space

class SAMRunner:

    def __init__(self, input_dir, output_folder, trigger_file, model_type, checkpoint_path, device):
        self.input_dir: Path = Path(input_dir)
        self.output_folder: Path = Path(output_folder)
        self.model_type = model_type
        self.checkpoint_path: Path = Path(checkpoint_path)
        self.device = torch.device('cuda' if torch.cuda.is_available() and device == 'cuda' else 'cpu')
        self.MASTER_RECORD: Dict[str, Feature] = {}
        self.active_file_name: str = None
        self.stop = False
        self.RETRY_LOADING = 10
        self.trigger_file = os.path.join(input_dir, trigger_file)
        self.control_file = os.path.join(input_dir, 'control.txt')
        try:
            raise Exception('spam', 'eggs')
            sam = sam_model_registry[self.model_type](checkpoint=checkpoint_path)
            sam.to(device=self.device)
            self.predictor = SamPredictor(sam)
        except Exception as e:
            raise e
            print('An Exception occurred while initializing SAM')

    def get_nifti_image(self, file='images/modal_0.nii.gz'):
        n_try = 0
        while n_try < self.RETRY_LOADING:
            try:
                data_itk = sitk.ReadImage(file)
                image_2d = sitk.GetArrayFromImage(data_itk).astype(np.uint8, copy=False).squeeze()
            except:
                print('Exception occured, trying again...')
                n_try += 1
                time.sleep(0.001)
            else:
                break
        return image_2d

    def IsStop(self):
        if not self.stop:
            self.check_control_file()
        return self.stop

    def check_control_file(self):
        try:
            with open(self.control_file, mode='r') as file:
                for line in file:
                    if line == "KILL":
                        self.stop = True
                        print('KILL')
                        break
                else:
                    self.stop = False
        except IOError:
            self.stop = False

    def get_features(self, image: np.ndarray):
        assert image.ndim == 2
        assert image.dtype == np.uint8
        image = np.dstack([image[:, :, None]] * 3)
        self.predictor.set_image(image)

    def get_points_and_labels_from_trigger_file(self):
        with open(self.trigger_file, mode='r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            points = []
            labels = []
            try:
                for row in csv_reader:
                    points.append([int(x) for x in row['Point'].split(' ')])
                    labels.append(int(row['Label']))
            except ValueError:
                self.stop = True
        input_points = np.array(points)
        input_labels = np.array(labels)
        return input_points, input_labels

    def set_features_to_predictor(self, features: Feature):
        self.predictor.features = features.feature_embeddings
        self.predictor.original_size = features.original_size
        self.predictor.input_size = features.input_size
        self.predictor.is_image_set = True

    def start_agent(self):
        path_template = os.path.join(self.input_dir, '*.nii.gz')
        print('READY')
        while not glob.glob(path_template):
            time.sleep(0.1)  # wait until image file is found in the input folder
            if self.IsStop(): break
        while True:  # Main Daemon while loop
            if self.IsStop(): break
            file_path = Path(glob.glob(path_template)[0])
            print('File found:', file_path)
            self.active_file_name = file_path.name
            if self.IsStop(): break
            if self.active_file_name not in self.MASTER_RECORD:
                print('File NOT found in MASTER RECORD:', self.active_file_name)
                image_2d = self.get_nifti_image(file_path)
                image_2d = cv2.normalize(image_2d, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                self.get_features(image_2d)
                feature_object = Feature(self.predictor.input_size, self.predictor.original_size, self.predictor.features)
                self.MASTER_RECORD[self.active_file_name] = feature_object
            else:
                print('File found in MASTER RECORD:', file_path)
                feature_object = self.MASTER_RECORD[self.active_file_name]
                self.set_features_to_predictor(feature_object)
            try:
                os.remove(file_path)
            except:
                print('Delete failed...')
            _cached_stamp = 0
            while not glob.glob(self.trigger_file):
                time.sleep(0.01)  # wait until trigger file is found in the input folder
                if self.IsStop(): break
            while True:  # Loop to monitor changes in trigger file
                stamp = os.stat(self.trigger_file).st_mtime
                if stamp != _cached_stamp:
                    input_points, input_labels = self.get_points_and_labels_from_trigger_file()
                    print('input points', input_points)
                    print('input labels', input_labels)
                    if self.IsStop():
                        break
                    mask, _, _ = self.predictor.predict(point_coords=input_points, point_labels=input_labels,
                                                        multimask_output=False)
                    print(mask.shape)
                    seg_resized_itk = sitk.GetImageFromArray(mask.astype(np.uint8, copy= False))
                    output_path = os.path.join(self.output_folder, self.active_file_name)
                    print('Output path', output_path)
                    sitk.WriteImage(seg_resized_itk, output_path)
                    _cached_stamp = stamp
                    print('SUCCESS')
                if self.IsStop() or glob.glob(path_template): break
            if self.IsStop(): break
        print('SAM agent has stopped...')


parser = argparse.ArgumentParser(description="Runs embedding generation on an input image or directory of images. "
                                             "Requires SimpleITK. Saves resulting embeddings as .pth files.")
parser.add_argument("--input-folder", type=str, required=True,
                    help="Path to folder of NIfTI files. Each file is expected to "
                         "be in dim order DxHxW or HxW")
parser.add_argument("--output-folder", type=str, required=True, help="Folder to where masks is be exported.")
parser.add_argument("--trigger-file", type=str, required=True, help="Path to the file where points will be written to.")
parser.add_argument("--model-type", type=str, required=True, help="The type of model to load, in "
                                                                  "['default', 'vit_h', 'vit_l', 'vit_b']")
parser.add_argument("--checkpoint", type=str, required=True, help="The path to the SAM checkpoint to use for mask "
                                                                  "generation.")
parser.add_argument("--device", type=str, default="cuda", help="The device to run generation on.")

args = parser.parse_args()

if __name__ == "__main__":
    start = time.time()
    print('Starting python...')
    args = parser.parse_args()
    print(args.input_folder)
    print(args.output_folder)
    print(args.model_type)
    sam_runner = SAMRunner(args.input_folder, args.output_folder, args.trigger_file, args.model_type, args.checkpoint,
                          args.device)
    try:
        sam_runner.start_agent()
    except torch.cuda.OutOfMemoryError:
        print('CudaOutOfMemoryError')
        torch.cuda.empty_cache()
    except Exception as e:
        print(e)
    print('Stopping daemon...')
    print('KILL')

