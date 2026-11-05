#!/usr/bin/env python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
import time
import os

# ePortem added reCAPTCHA v3 to the login form (2026-10-29). Its score rejects
# plain headless Chrome, so the browser is made to look like a normal desktop one.
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
LOGIN_URL = "https://eportem.es/Usuario/Login?ReturnUrl=%2faplicaciones"
PAGE_LOAD_TIMEOUT_SECONDS = 90


def uses_recaptcha(driver):
    return driver.execute_script(
        "return [...document.scripts].some(s => /recaptcha/i.test(s.src))")


def create_driver():
    headless = os.getenv('HEADLESS_BROWSING')
    chrome_options = ChromeOptions()
    chrome_options.add_argument("--disable-gpu")
    if headless == "YES":
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1366,900")
    chrome_options.add_argument("--lang=es-ES")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(f"user-agent={USER_AGENT}")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def login_and_navigate(driver=None):
    uname = os.getenv('EPORTEM_USERNAME')
    pwd = os.getenv('EPORTEM_PASSWORD')

    # create a new Chrome browser instance if one isn't passed in
    if driver is None:
        driver = create_driver()
        driver.get(LOGIN_URL)

    # ePortem has turned reCAPTCHA v3 on (2026-10-29) and off again (2026-10-30). When
    # the page loads its script, wait for it, since the form submit handler needs it
    # for its token; otherwise log in straight away.
    if uses_recaptcha(driver):
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return typeof grecaptcha !== 'undefined' && !!grecaptcha.execute"))
    time.sleep(3)

    # find the username and password fields within the login form
    username = driver.find_element(By.NAME, "usuario")
    password = driver.find_element(By.NAME, "password")

    username.click()
    username.send_keys(uname)
    time.sleep(0.7)
    password.click()
    password.send_keys(pwd)
    time.sleep(0.8)

    # submit the login form
    driver.find_element(By.ID, "submit").click()

    # wait for the redirect away from the login page, then for the page to load
    WebDriverWait(driver, 20).until(lambda d: "/Usuario/Login" not in d.current_url)
    time.sleep(3)

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
