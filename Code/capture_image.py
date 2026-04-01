import csv
import cv2
import os

def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        pass
    try:
        import unicodedata
        unicodedata.numeric(s)
        return True
    except (TypeError, ValueError):
        pass
    return False

def takeImages():
    Id = input("Enter Your Id: ")
    name = input("Enter Your Name: ")

    if(is_number(Id) and name.isalpha()):
        # FIX 1: Capitalize V and C
        cam = cv2.VideoCapture(0)
        
        # FIX 2: Capitalize C (CascadeClassifier)
        harcascadePath = "haarcascade_default.xml"
        detector = cv2.CascadeClassifier(harcascadePath)
        
        sampleNum = 0

        # Ensure the directory exists before saving
        if not os.path.exists("TrainingImage"):
            os.makedirs("TrainingImage")

        while(True):
            ret, img = cam.read()
            if not ret:
                print("Failed to grab frame")
                break
                
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(gray, 1.3, 5, minSize=(30,30), flags=cv2.CASCADE_SCALE_IMAGE)
            
            for(x,y,w,h) in faces:
                cv2.rectangle(img, (x, y), (x+w, y+h), (10, 159, 255), 2)
                sampleNum = sampleNum + 1
                
                # Saving the captured face
                img_path = "TrainingImage" + os.sep + name + "." + Id + '.' + str(sampleNum) + ".jpg"
                cv2.imwrite(img_path, gray[y:y+h, x:x+w])
                
                # FIX 3: Move imshow outside the loop or ensure it updates every frame
                cv2.imshow('frame', img)
            
            # Use a small delay for the window to refresh
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            elif sampleNum > 100:
                break
                
        cam.release()
        cv2.destroyAllWindows()
        
        # Ensure StudentDetails directory exists
        if not os.path.exists("StudentDetails"):
            os.makedirs("StudentDetails")
            
        res = "Images Saved for ID : " + Id + " Name : " + name
        print(res)
        
        row = [Id, name]
        with open("StudentDetails" + os.sep + "StudentDetails.csv", 'a+', newline='') as csvFile:
            writer = csv.writer(csvFile)
            writer.writerow(row)
        # No need for csvFile.close() when using 'with'
    else:
        if not is_number(Id):
            print("Enter Numeric ID")
        if not name.isalpha():
            print("Enter Alphabetical Name")