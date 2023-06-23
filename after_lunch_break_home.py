#!/usr/bin/env python
from utility.login_and_navigate import login_and_navigate
from selenium import webdriver
from selenium.webdriver.common.by import By
import time
from utility.telegram_send import send_telegram_message

# log in to ePortem
driver = login_and_navigate()

# find the button element and click it
button = driver.find_element(By.XPATH,"/html/body[@class='pace-done skin-1 fixed-sidebar']/div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group']/button[@class='btn btn-outline btn-block btn-warning dropdown-toggle']")
button.click()
button2 = driver.find_element(By.XPATH,"/html/body[@class='pace-done skin-1 fixed-sidebar']/div[@id='wrapper']/div[@id='page-wrapper']/div[@class='wrapper wrapper-content']/div[@class='row']/div[@class='col-lg-6 col-sm-12'][1]/div[@class='ibox']/div[@class='ibox-content']/div[@class='row']/div[@id='buttonsRegBox']/div[@class='btn-group']/div[@class='btn-group open']/ul[@class='dropdown-menu scrollable-menu']/li[1]/ul/li[2]/a[@id='_stini']")
button2.click()

time.sleep(3)

# close the browser window
driver.quit()

# confirm we've done the thing
send_telegram_message("RePortemed back from lunch break")