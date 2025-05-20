#!/usr/bin/env python3
import os
from utility.login_and_navigate import login_and_navigate
from selenium import webdriver
from selenium.webdriver.common.by import By
import time
from utility.telegram_send import send_telegram_message
from utility.env_check import check_env_variable

import argparse

# check if we should run
check_env_variable()

def main(driver=None):
    # log in to ePortem
    driver = login_and_navigate(driver)

    # find the button element and click it
    # button = driver.find_element(By.XPATH,"/html/body[@class='pace-done skin-1 fixed-sidebar']/div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']")
    button = driver.find_element(By.XPATH,"//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']")
    button.click()
    # button2 = driver.find_element(By.XPATH,"/html/body[@class='pace-done skin-1 fixed-sidebar']/div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group open']/ul[@class='dropdown-menu scrollable-menu']/li[2]/a[@id='_ststop']")
    button2 = driver.find_element(By.XPATH,"//div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group open']/ul[@class='dropdown-menu scrollable-menu']/li[2]/a[@id='_ststop']")
    button2.click()

    time.sleep(3)

    # close the browser window
    driver.quit()

    # confirm we've done the thing
    send_telegram_message("RePortemed done for the day")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stop the day script.")
    parser.add_argument("--mock", action="store_true", help="Run with a mock driver.")
    args = parser.parse_args()

    if args.mock:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        chrome_options = ChromeOptions()
        chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(options=chrome_options)
        main(driver)
    else:
        main()
