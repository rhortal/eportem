#!/usr/bin/env python
from config.login_and_navigate import login_and_navigate
from selenium import webdriver
from selenium.webdriver.common.by import By
import time

# log in to ePortem
driver = login_and_navigate()

# find the button element and click it
button = driver.find_element(By.XPATH,"/html/body[@class='pace-done skin-1 fixed-sidebar']/div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-primary dropdown-toggle']")
button.click()

time.sleep(3)

# close the browser window
driver.quit()