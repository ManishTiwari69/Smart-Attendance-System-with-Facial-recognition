import os
import check_camera
import capture_image
import train_image
import recognize

def title_bar():
    # 'cls' for Windows, 'clear' for Linux/Mac
    os.system('cls' if os.name == 'nt' else 'clear')
    print("\t***** Face Recognition Attendance System *****")

def mainMenu():
    while True: # Keep the menu running
        title_bar()
        print("\n" + 10 * "*", "WELCOME MENU", 10 * "*")
        print("[1] Check Camera")
        print("[2] Capture Faces")
        print("[3] Train Images")
        print("[4] Recognize & Attendance")
        print("[5] Auto Mail")
        print("[6] Quit")
        
        try:
            choice = input("Enter Choice: ") # Taking input as string is safer
            
            if choice == '1':
                check_camera.camer()
            elif choice == '2':
                capture_image.takeImages()
            elif choice == '3':
                train_image.TrainImages()
            elif choice == '4':
                recognize.recognize_attendence()
            elif choice == '5':
                # It's better to import automail and call a function, 
                # but this works for now:
                os.system("py automail.py")
            elif choice == '6':
                print("Thank You!")
                break # This exits the while loop and ends the program
            else:
                print("Invalid Choice. Enter 1-6")
            
            # This replaces your separate functions and prevents recursion
            if choice in ['1', '2', '3', '4', '5']:
                input("\nPress Enter to return to the Main Menu...")
                
        except Exception as e:
            print(f"An error occurred: {e}")
            input("Press Enter to continue...")

# Only run if this script is executed directly
if __name__ == "__main__":
    mainMenu()