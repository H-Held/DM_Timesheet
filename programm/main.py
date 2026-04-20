import os
import smtplib
from email.message import EmailMessage
import environment_loader



def main():
    gmail, passkey = environment_loader.load_env()
    print("GMAIL: " + gmail)
    print("APP_PASSKEY: " + passkey)

if __name__ == "__main__":
    main()