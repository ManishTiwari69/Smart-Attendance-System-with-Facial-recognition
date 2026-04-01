import os
import time
import cv2
import numpy as np
from PIL import Image
from threading import Thread


def getImagesAndLabels(path):
    # path of all the files in the folder
    imagePaths = [os.path.join(path, f) for f in os.listdir(path)]
    faces = []
    # empty ID list
    Ids = []
    for imagePath in imagePaths:
        pilImage = Image.open(imagePath).convert('L')
        imageNp = np.array(pilImage, 'uint8')
        Id = int(os.path.split(imagePath)[-1].split(".")[1])
        faces.append(imageNp)
        Ids.append(Id)
    return faces, Ids


def TrainImages():
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    harcascadePath = "haarcascade_default.xml"
    detector = cv2.CascadeClassifier(harcascadePath)
    faces, Id = getImagesAndLabels("TrainingImage")
    Thread(target = recognizer.train(faces, np.array(Id))).start()
    Thread(target = counter_img("TrainingImage")).start()
    recognizer.save("TrainingImageLabel"+os.sep+"Trainner.yml")
    print("All Images")
    if len(faces) == 0:
        print("No images found in TrainingImage folder.")
        return
    print("Training started... please wait.")
    
    # We thread the counter only to show progress while the main thread trains
    progress_thread = Thread(target=counter_img, args=("TrainingImage",))
    progress_thread.start()
    
    recognizer.train(faces, np.array(Id))
    
    # Wait for the progress thread to finish showing the count
    progress_thread.join()
    if not os.path.exists("TrainingImageLabel"):
        os.makedirs("TrainingImageLabel")
        
    recognizer.save("TrainingImageLabel" + os.sep + "Trainner.yml")
    print("\n[SUCCESS] All Images Trained and Model Saved.")

def counter_img(path):
    imagePaths = [os.path.join(path, f) for f in os.listdir(path)]
    for i, _ in enumerate(imagePaths, 1):
        print(f"{i} Images Processed", end="\r")
        time.sleep(0.01) # Small delay for visual effect