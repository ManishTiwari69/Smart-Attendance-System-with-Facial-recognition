def camer():
    import cv2
    import os

    # Check if cascade file exists to prevent silent failure
    cascade_path = 'haarcascade_default.xml'
    if not os.path.exists(cascade_path):
        print(f"Error: {cascade_path} not found in the current directory.")
        return

    cascade_face = cv2.CascadeClassifier(cascade_path)
    cap = cv2.VideoCapture(0)

    # Optional: Set resolution (helpful for consistent performance)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("Webcam started. Press 'q' to exit.")

    while True:
        ret, img = cap.read()
        
        # If camera fails to read, break the loop instead of crashing
        if not ret:
            print("Error: Could not read frame from camera.")
            break

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = cascade_face.detectMultiScale(
            gray, 
            scaleFactor=1.3, 
            minNeighbors=5, 
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE
        )

        for (a, b, c, d) in faces:
            # Draw rectangle
            cv2.rectangle(img, (a, b), (a + c, b + d), (10, 159, 255), 2)
            # Add a label (useful for your attendance system later)
            cv2.putText(img, "Face Detected", (a, b-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (10, 159, 255), 2)

        cv2.imshow('Webcam Check', img)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()