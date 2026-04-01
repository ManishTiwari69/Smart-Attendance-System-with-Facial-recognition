import datetime
import os
import time
import cv2
import pandas as pd


def recognize_attendence():
    recognizer = cv2.face.LBPHFaceRecognizer_create()  
    recognizer.read("TrainingImageLabel"+os.sep+"Trainner.yml")
    harcascadePath = "haarcascade_default.xml"
    faceCascade = cv2.CascadeClassifier(harcascadePath)
    df = pd.read_csv("StudentDetails"+os.sep+"StudentDetails.csv")
    font = cv2.FONT_HERSHEY_SIMPLEX
    col_names = ['Id', 'Name', 'Date', 'Time']
    attendance = pd.DataFrame(columns=col_names)

    # start realtime video capture
    cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cam.set(3, 640) 
    cam.set(4, 480) 
    minW = 0.1 * cam.get(3)
    minH = 0.1 * cam.get(4)

    if not os.path.exists("Attendance"):
        os.makedirs("Attendance")

    while True:
        ret, im = cam.read()
        if not ret: break
        
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        faces = faceCascade.detectMultiScale(gray, 1.2, 5, minSize=(int(minW), int(minH)))

        for (x, y, w, h) in faces:
            cv2.rectangle(im, (x, y), (x+w, y+h), (10, 159, 255), 2)
            Id, conf = recognizer.predict(gray[y:y+h, x:x+w])
            
            # LBPH confidence: lower is better. 0 is a perfect match.
            match_confidence = round(100 - conf)

            if conf < 100:
                name_results = df.loc[df['Id'] == Id]['Name'].values
                name = name_results[0] if len(name_results) > 0 else "Unknown"
                display_text = f"{Id}-{name}"
            else:
                Id = "Unknown"
                name = "Unknown"
                display_text = "Unknown"

            # Mark attendance if confidence is high (e.g., > 67%)
            if match_confidence > 67 and Id != "Unknown":
                ts = time.time()
                date = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                timestamp = datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S')
                
                # Only add if not already present in today's session
                if Id not in attendance['Id'].values:
                    attendance.loc[len(attendance)] = [Id, name, date, timestamp]
                
                color = (0, 255, 0) # Green for pass
                label = f"{display_text} [Pass]"
            else:
                color = (0, 0, 255) # Red for fail/unknown
                label = display_text

            # Visual Feedback
            cv2.putText(im, label, (x+5, y-5), font, 1, (255, 255, 255), 2)
            cv2.putText(im, f"{match_confidence}%", (x+5, y+h-5), font, 1, color, 1)

        cv2.imshow('Attendance', im)
        if cv2.waitKey(1) == ord('q'):
            break
    ts = time.time()
    date = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    timeStamp = datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S')
    Hour, Minute, Second = timeStamp.split(":")
    fileName = "Attendance"+os.sep+"Attendance_"+date+"_"+Hour+"-"+Minute+"-"+Second+".csv"
    attendance.to_csv(fileName, index=False)
    print("Attendance Successful")
    cam.release()
    cv2.destroyAllWindows()