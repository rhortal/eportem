#!/usr/bin/env python

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
import os

# Get the directory of the current file
current_dir = os.path.dirname(os.path.realpath(__file__))

# Construct the file path
file_path = os.path.join(current_dir, 'credentials.txt')

with open(file_path, "r") as f:
    uname, pwd = f.read().splitlines()

# create a new Chrome browser instance
driver = webdriver.Chrome()

# navigate to the login page
driver.get("https://eportem.es/Usuario/Login?ReturnUrl=%2faplicaciones")

# find the username and password fields within the login form
username = driver.find_element(By.NAME, "user")
password = driver.find_element(By.NAME, "password")

username.send_keys(uname)
password.send_keys(pwd)
 
# submit the login form
password.send_keys(Keys.RETURN)

# wait for the page to load
time.sleep(3)

# find the button element and click it
button = driver.find_element(By.XPATH,"/html/body[@class='pace-done skin-1 fixed-sidebar']/div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']")
button.click()

time.sleep(3)

# close the browser window
driver.quit()