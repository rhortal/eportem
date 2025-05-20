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
    use_mock = os.getenv('USE_MOCK_SERVER', 'NO')

    # create a new Chrome browser instance if one isn't passed in
    if driver is None:
        if use_mock == "YES":
            # Use our custom MockWebDriver
            from mock_server.mock_driver import create_mock_driver
            driver = create_mock_driver()
        else:
            chrome_options = ChromeOptions()
            chrome_options.add_argument("--disable-gpu")
            if headless == "YES":
                chrome_options.add_argument("--headless")
            driver = webdriver.Chrome(options=chrome_options)

        # Determine the base URL based on whether we're using the mock server
        base_url = "http://localhost:8000" if use_mock == "YES" else "https://eportem.es"
        
        try:
            # navigate to the login page
            driver.get(f"{base_url}/Usuario/Login?ReturnUrl=%2faplicaciones")
        except Exception as e:
            if use_mock == "YES":
                print(f"Mock driver warning: {e}")
                print("Continuing with mock test...")
            else:
                raise

    try:
        # find the username and password fields within the login form
        username = driver.find_element(By.NAME, "user")
        password = driver.find_element(By.NAME, "password")

        # Always use test credentials in mock mode
        if use_mock == "YES":
            uname = "test_user"
            pwd = "test_password"
            print("Using mock credentials: test_user / test_password")

        username.send_keys(uname)
        password.send_keys(pwd)

        # submit the login form
        password.send_keys(Keys.RETURN)

        # wait for the page to load
        time.sleep(2)
    except Exception as e:
        if use_mock == "YES":
            print(f"Mock driver warning: {e}")
            print("Continuing with mock test...")
            # If using mock driver, try to navigate to the dashboard directly
            try:
                driver.get(f"http://localhost:8000/aplicaciones")
            except:
                pass
        else:
            raise

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
