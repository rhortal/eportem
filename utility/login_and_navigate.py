#!/usr/bin/env python

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options as ChromeOptions
import time
import os
from pathlib import Path

def login_and_navigate(driver=None):
    # Get the directory of the current file
    current_dir = os.path.dirname(os.path.realpath(__file__))

    uname = os.getenv('EPORTEM_USERNAME')
    pwd = os.getenv('EPORTEM_PASSWORD')
    headless = os.getenv('HEADLESS_BROWSING')

    # create a new Chrome browser instance if one isn't passed in
    if driver is None:
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--disable-gpu")
        if headless == "YES":
            chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(options=chrome_options)

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
    time.sleep(2)

#    print (driver.page_source)

    return driver

# example usage of the function
if __name__ == '__main__':
    driver = login_and_navigate()

    # find the button element and click it
    button = driver.find_element(By.XPATH,"/html/body[@class='pace-done skin-1 fixed-sidebar']/div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']")
    button.click()

    time.sleep(3)

    # close the browser window
    driver.quit()
